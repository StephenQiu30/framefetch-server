"""macOS project startup with automatic platform session acquisition."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx
from app.workers.session.contracts import STATUS_PATH, StatusRequest, StatusResponse
from app.workers.session.rpc import RpcError, SignedClient
from app.workers.session.seed import PROJECT_ROOT, load_settings
from app.workers.session.source import reconcile, source_directory
from sqlalchemy.engine import make_url


def agent_label(env_file: Path) -> str:
    return f"com.framefetch.session-source.{source_directory(env_file).name}"


def agent_spec(env_file: Path, interval: int) -> dict[str, object]:
    return {
        "Label": agent_label(env_file),
        "ProgramArguments": [
            sys.executable,
            "-m",
            "app.workers.session.source",
            "supervise",
            "--env-file",
            str(env_file),
        ],
        "WorkingDirectory": str(PROJECT_ROOT / "backend"),
        "RunAtLoad": True,
        "StartInterval": interval,
        "ProcessType": "Background",
        "ExitTimeOut": 5,
        "Umask": 0o077,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def _launchctl(*args: str, check: bool = True) -> None:
    subprocess.run(
        ["/bin/launchctl", *args],
        check=check,
        timeout=15,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install_agent(env_file: Path, interval: int) -> None:
    directory = Path.home() / "Library/LaunchAgents"
    directory.mkdir(parents=True, exist_ok=True)
    label = agent_label(env_file)
    destination = directory / f"{label}.plist"
    payload = plistlib.dumps(agent_spec(env_file, interval))
    # Do not interrupt a current acquisition when the installed spec is unchanged.
    if destination.exists() and destination.read_bytes() == payload:
        try:
            _launchctl("print", f"gui/{os.getuid()}/{label}")
            return
        except subprocess.CalledProcessError:
            pass
    _launchctl("bootout", f"gui/{os.getuid()}/{label}", check=False)
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    temporary.replace(destination)
    _launchctl("bootstrap", f"gui/{os.getuid()}", str(destination))


def uninstall_agent(env_file: Path) -> None:
    label = agent_label(env_file)
    _launchctl("bootout", f"gui/{os.getuid()}/{label}", check=False)
    (Path.home() / "Library/LaunchAgents" / f"{label}.plist").unlink(missing_ok=True)


def request_access_check(env_file: Path) -> str:
    request_id = uuid4().hex
    directory = source_directory(env_file)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
        stream.write(request_id)
        temporary = Path(stream.name)
    temporary.replace(directory / "access-request")
    _launchctl("kickstart", f"gui/{os.getuid()}/{agent_label(env_file)}", check=False)
    return request_id


def wait_access_check(env_file: Path, request_id: str, *, timeout: float = 150) -> bool:
    deadline = time.monotonic() + timeout
    report = source_directory(env_file) / "access-status.json"
    while time.monotonic() < deadline:
        if report.exists():
            data = json.loads(report.read_text())
            if data.get("request_id") == request_id:
                sites = data["sites"]
                print("后台自动接入检查：" + json.dumps(sites), flush=True)
                if "chrome_permission_required" in sites.values():
                    print(
                        "请为后台 Python 授予 macOS 完全磁盘访问权限，"
                        "并允许 Chrome Safe Storage 钥匙串访问："
                        + str(Path(sys.executable).resolve()),
                        flush=True,
                    )
                return all(value == "readable" for value in sites.values())
        time.sleep(1)
    print("后台自动接入检查尚未完成，请检查 macOS 授权和后台运行状态。")
    return False


async def apply_schema(env_file: Path) -> None:
    url = make_url(load_settings(env_file).database_url)
    connection = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port or 5432,
        database=url.database,
        timeout=10,
        command_timeout=120,
    )
    try:
        await connection.execute("SET lock_timeout = '5s'")
        await connection.execute((PROJECT_ROOT / "backend/sql/schema.sql").read_text())
    finally:
        await connection.close()


async def verify_sites(sites: list[str], *, timeout: float = 150) -> dict[str, str]:
    """Run inside the broker: its RPC proves this process verified the browser."""
    results = dict.fromkeys(sites, "not_ready")
    deadline = asyncio.get_running_loop().time() + timeout
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:19200", timeout=5
    ) as client:
        rpc = SignedClient(client, os.environ["SITE_SESSION_RPC_SECRET"].encode())
        while True:
            for site in sites:
                try:
                    await rpc.post(
                        STATUS_PATH, StatusRequest(site=site), StatusResponse
                    )
                    results[site] = "ready"
                except (RpcError, httpx.HTTPError):
                    results[site] = "not_ready"
            if all(v == "ready" for v in results.values()):
                return results
            if asyncio.get_running_loop().time() >= deadline:
                return results
            await asyncio.sleep(3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "uninstall-source", "verify"))
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--sites", nargs="*", default=[])
    args = parser.parse_args()
    try:
        if args.command == "verify":
            result = asyncio.run(verify_sites(args.sites))
            print(json.dumps(result), flush=True)
            return 0 if all(v == "ready" for v in result.values()) else 2
        if sys.platform != "darwin":
            print("自动读取本机 Chrome 的启动入口要求 macOS。", flush=True)
            return 2
        env_file = args.env_file.resolve()
        if args.command == "uninstall-source":
            uninstall_agent(env_file)
            print("已移除自动接入服务；已保存的平台会话仍由容器维护。")
            return 0
        if not env_file.is_file() or shutil.which("docker") is None:
            print("请先配置现有 .env 并启动 Docker。")
            return 2
        settings = load_settings(env_file)
        if settings.site_session_encryption_key is None:
            print("请先配置稳定的 SITE_SESSION_ENCRYPTION_KEY。")
            return 2
        print("检查当前数据库结构并自动准备平台连接…", flush=True)
        asyncio.run(apply_schema(env_file))
        print("先启动业务服务；平台接入不阻塞核心 API…", flush=True)
        compose = [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(PROJECT_ROOT / "docker-compose.yml"),
        ]
        command = compose + ["up", "-d", "--wait", "--wait-timeout", "180"]
        if not args.no_build:
            command.append("--build")
        subprocess.run(command, cwd=PROJECT_ROOT, check=True, timeout=1200)
        print(json.dumps(reconcile(env_file)), flush=True)
        install_agent(env_file, settings.site_session_source_interval_seconds)
        request_id = request_access_check(env_file)
        print("服务已启动，等待所有已启用平台实际验证…", flush=True)
        result_code = subprocess.run(
            compose
            + [
                "exec",
                "-T",
                "session-broker",
                "python",
                "-m",
                "app.workers.session.startup",
                "verify",
                "--sites",
                *settings.site_session_source_sites,
            ],
            cwd=PROJECT_ROOT,
            timeout=180,
            check=False,
        ).returncode
        if result_code:
            print("部分平台未就绪；核心服务继续运行，启动报告保留失败。", flush=True)
        print("验证固定公开平台的实际解析接口…", flush=True)
        public_code = subprocess.run(
            compose
            + [
                "exec",
                "-T",
                "provider-canary",
                "python",
                "-m",
                "app.workers.canary.fixed_matrix",
                "--native-public",
                "--stage",
                "metadata",
            ],
            cwd=PROJECT_ROOT,
            timeout=600,
            check=False,
        ).returncode
        if public_code:
            print(
                "部分公开平台探测失败，已保留真实失败状态；不切换访问路线。", flush=True
            )
        access_ready = wait_access_check(env_file, request_id)
        if not access_ready:
            print(
                "自动重新获取尚需处理系统权限或 Chrome 登录；"
                "已有平台会话仍由容器维护，启动报告保留失败。",
                flush=True,
            )
        return result_code or public_code or (0 if access_ready else 2)
    except Exception:
        print(
            "启动操作未完成；请检查数据库、Docker 与 macOS 接入权限。"
            "未输出可能包含密钥的底层异常。",
            file=sys.stderr,
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
