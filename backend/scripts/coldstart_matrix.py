"""Design 17 cold-start matrix through the authenticated public HTTP API.

The runtime lock covers rebuilding, cold start, every case, and restoration.
Samples lacking independent metadata remain blocked even if a file is delivered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import subprocess
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
LOCK = Path("/tmp/framefetch-runtime.lock")
SERVICES = ["api", "worker", "session-runner"]
Json = dict[str, Any]


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    kind: str
    field: str
    checked_at: str | None = None
    status: str = Field(pattern="^(verified|unverified)$")
    note: str

    @model_validator(mode="after")
    def verified_source(self) -> SourceEvidence:
        if self.status == "verified":
            if (
                not self.url.startswith(("https://", "http://"))
                or not self.field.strip()
                or not self.note.strip()
                or self.kind
                not in {
                    "platform_page_or_api",
                    "platform_api",
                    "public_page",
                    "official_player_metadata",
                }
                or not self.checked_at
                or (
                    len(self.checked_at) != 10
                    and datetime.fromisoformat(self.checked_at).tzinfo is None
                )
            ):
                raise ValueError(
                    "verified evidence needs dated independent platform source"
                )
            datetime.fromisoformat(self.checked_at)
        return self


class MinimumSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    audio: bool = True


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern="^[a-z0-9_-]+$")
    platform: str
    url: str
    expected_media_id: str
    kind: str = Field(pattern="^(positive|protected)$")
    expected_failure_class: str = Field(
        default="content_protected", pattern="^(content_protected|content_unavailable)$"
    )
    expected_gate: str | None = Field(default=None, pattern="^(①|②|③|none)$")
    content_scope: str = Field(pattern="^(public|personal_full)$")
    needs_identity: bool = False
    duration_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    duration_source: SourceEvidence
    availability_source: SourceEvidence
    minimum_spec: MinimumSpec

    @model_validator(mode="after")
    def boundaries(self) -> Case:
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("sample must be an HTTP(S) URL")
        if self.content_scope == "personal_full" and (
            self.platform not in {"qqvideo", "youku"} or not self.needs_identity
        ):
            raise ValueError("personal_full requires qqvideo/youku and needs_identity")
        if self.kind == "positive" and self.duration_source.status == "verified":
            if self.duration_seconds is None or not self.duration_source.checked_at:
                raise ValueError("verified duration needs value and checked_at")
        if self.availability_source.status == "verified":
            if not self.availability_source.checked_at:
                raise ValueError("verified availability needs checked_at")
        return self

    def qualification_gaps(self) -> list[str]:
        gaps = []
        if self.availability_source.status != "verified":
            gaps.append(
                "protection not independently verified"
                if self.kind == "protected"
                else "public/free/non-DRM availability not independently verified"
            )
        if self.kind == "positive" and (
            self.duration_seconds is None or self.duration_source.status != "verified"
        ):
            gaps.append("independent full duration missing")
        return gaps


def load_cases(path: Path) -> list[Case]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("cases must be a JSON array")
    cases = [Case.model_validate(item) for item in payload]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("duplicate sample id")
    return cases


def select_cases(
    cases: list[Case], registry: set[str], platforms: str | None
) -> list[Case]:
    wanted = registry if platforms is None else set(platforms.split(","))
    if not wanted or not wanted <= registry:
        raise ValueError(f"unknown platforms: {sorted(wanted - registry)}")
    selected = [case for case in cases if case.platform in wanted]
    if platforms is None and {case.platform for case in cases} != registry:
        raise ValueError(
            "--all fixture platform set must equal Registry: "
            f"missing={sorted(registry - {c.platform for c in cases})}, "
            f"extra={sorted({c.platform for c in cases} - registry)}"
        )
    for platform in sorted(wanted):
        positives = [
            c for c in selected if c.platform == platform and c.kind == "positive"
        ]
        if len(positives) < 2 or len({c.expected_media_id for c in positives}) != len(
            positives
        ):
            raise ValueError(
                f"{platform}: at least two independent positive works required"
            )
        if len({c.url for c in positives}) != len(positives):
            raise ValueError(f"{platform}: duplicate positive URL")
    return selected


class MatrixFailure(Exception):
    def __init__(self, category: str, evidence: Json | None = None):
        super().__init__(category)
        self.category = category
        self.evidence = evidence or {}


def run_command(argv: list[str], *, timeout: float, log: Path) -> str:
    """Bound subprocess output on disk and kill the whole process group on exit."""
    with log.open("w") as output:
        process = subprocess.Popen(
            argv,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=ROOT,
        )
        try:
            code = process.wait(timeout=timeout)
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    if code:
        raise MatrixFailure(
            "command_failed", {"command": argv[0], "exit_code": code, "log": log.name}
        )
    return log.read_text()


def compose_project(output: Path) -> str:
    """A worktree basename must never create another shared runtime project."""
    projects = run_command(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "com.docker.compose.project"}}',
            "video-api",
            "video-worker",
            "session-runner",
        ],
        timeout=15,
        log=output / "project.log",
    ).splitlines()
    if len(projects) != 3 or len(set(projects)) != 1 or not projects[0].strip():
        raise MatrixFailure("shared_compose_project_not_found")
    return projects[0].strip()


@contextmanager
def runtime(args: argparse.Namespace, output: Path, facts: Json) -> Iterator[None]:
    acquired = False
    changed = False
    suffix = uuid4().hex
    volumes = [
        f"framefetch-coldstart-browser-{suffix}",
        f"framefetch-coldstart-work-{suffix}",
    ]
    override = output / "compose.coldstart.json"
    compose: list[str] = []
    try:
        while True:
            try:
                LOCK.mkdir()
                acquired = True
                break
            except FileExistsError:
                print("Waiting for /tmp/framefetch-runtime.lock", flush=True)
                time.sleep(20)
        owner = getattr(args, "runtime_owner", "coldstart")
        (LOCK / "owner").write_text(f"{owner} {datetime.now(UTC).isoformat()}\n")
        print(f"{owner} runtime lock acquired", flush=True)
        project = compose_project(output)
        facts["compose_project"] = project
        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(args.env_file),
            "-f",
            str(ROOT / "docker-compose.yml"),
        ]
        isolated = compose + ["-f", str(override)]
        facts.update(
            {
                "browser_volume": volumes[0],
                "work_volume": volumes[1],
                "shared_services_restarted": False,
            }
        )
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "session-runner": {
                            "volumes": [
                                "coldstart_browser:/var/lib/video-browser",
                                "coldstart_work:/work",
                            ],
                            "environment": {
                                "XDG_CACHE_HOME": "/tmp/coldstart-cache",
                                "HOME": "/tmp/coldstart-home",
                            },
                        },
                        "worker": {"volumes": ["coldstart_work:/work"]},
                    },
                    "volumes": {
                        "coldstart_browser": {"name": volumes[0]},
                        "coldstart_work": {"name": volumes[1]},
                    },
                },
                indent=2,
            )
        )
        run_command(
            compose + ["build", *SERVICES], timeout=1800, log=output / "build.log"
        )
        changed = True
        run_command(
            isolated
            + ["up", "-d", "--no-deps", "--force-recreate", "--wait", *SERVICES],
            timeout=300,
            log=output / "startup.log",
        )
        # Recreated tmpfs and an empty HOME/XDG cache leave no previous yt-dlp state.
        facts["tmpfs_recreated"] = True
        facts["cache_empty"] = True
        if args.cookie_source_label:
            run_command(
                [
                    "launchctl",
                    "kickstart",
                    "-k",
                    f"gui/{os.getuid()}/{args.cookie_source_label}",
                ],
                timeout=15,
                log=output / "cookie-source.log",
            )
        facts["cookie_source"] = (
            "restarted"
            if args.cookie_source_label
            else "existing_host_service_reused"
            if getattr(args, "reuse_cookie_source", False)
            else "not_cold_started"
        )
        inspect = run_command(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Name}} {{.Image}} {{range .Mounts}}"
                "{{.Destination}}={{.Name}} {{end}}",
                "video-api",
                "video-worker",
                "session-runner",
            ],
            timeout=15,
            log=output / "containers.log",
        )
        if (
            f"/var/lib/video-browser={volumes[0]}" not in inspect
            or f"/work={volumes[1]}" not in inspect
        ):
            raise MatrixFailure("coldstart_volume_not_mounted")
        facts["containers"] = inspect.splitlines()
        yield
    finally:
        try:
            if changed:
                run_command(
                    compose
                    + [
                        "up",
                        "-d",
                        "--no-deps",
                        "--force-recreate",
                        "--wait",
                        *SERVICES,
                    ],
                    timeout=300,
                    log=output / "restore.log",
                )
                facts["daily_volumes_restored"] = True
                run_command(
                    ["docker", "volume", "rm", *volumes],
                    timeout=30,
                    log=output / "volume-cleanup.log",
                )
        except (MatrixFailure, subprocess.TimeoutExpired) as exc:
            facts["restoration_error"] = str(exc)
        finally:
            if acquired:
                (LOCK / "owner").unlink(missing_ok=True)
                LOCK.rmdir()
                print(f"{owner} runtime lock released", flush=True)


class Api:
    def __init__(self, base: str):
        self.client = httpx.Client(
            base_url=base.rstrip("/"),
            timeout=30,
            trust_env=False,
            follow_redirects=False,
        )
        self.client.headers["Origin"] = base.rstrip("/")

    def request(self, method: str, path: str, **kwargs: Any) -> Json:
        response = self.client.request(method, path, **kwargs)
        if response.is_error:
            # Persist the safe public code, never headers or credentials.
            try:
                code = response.json().get("code", "http_error")
            except ValueError:
                code = "http_error"
            raise MatrixFailure(
                str(code), {"http_status": response.status_code, "endpoint": path}
            )
        payload = response.json()
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise MatrixFailure("api_response_shape")
        return data

    def login(self) -> None:
        cookie = os.environ.get("COLDSTART_COOKIE")
        if cookie:
            self.client.headers["Cookie"] = cookie
        else:
            email, password = (
                os.environ.get("COLDSTART_EMAIL"),
                os.environ.get("COLDSTART_PASSWORD"),
            )
            if not email or not password:
                raise MatrixFailure("matrix_auth_missing")
            self.request(
                "POST", "/api/auth/login", json={"email": email, "password": password}
            )
        self.request("GET", "/api/auth/me")

    def poll(self, path: str, active: set[str], timeout: float) -> Json:
        deadline = time.monotonic() + timeout
        while True:
            payload = self.request("GET", path)
            if payload["status"] not in active:
                return payload
            if time.monotonic() >= deadline:
                self.request("POST", f"{path}/cancel")
                raise MatrixFailure(
                    "matrix_timeout", {"endpoint": path, "cancel_requested": True}
                )
            time.sleep(1)

    def file(
        self, job_id: str, path: Path, max_bytes: int, timeout: float = 900
    ) -> Json:
        digest, size = hashlib.sha256(), 0
        deadline = time.monotonic() + timeout
        with self.client.stream("GET", f"/api/downloads/{job_id}/file") as response:
            if response.status_code != 200:
                raise MatrixFailure(
                    "file_http_error", {"http_status": response.status_code}
                )
            length = int(response.headers.get("Content-Length", "0"))
            if length < 1 or length > max_bytes:
                raise MatrixFailure("file_size_limit")
            with path.open("wb") as target:
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise MatrixFailure("file_timeout")
                    size += len(chunk)
                    if size > max_bytes:
                        raise MatrixFailure("file_size_limit")
                    digest.update(chunk)
                    target.write(chunk)
            sha = digest.hexdigest()
            if size != length or response.headers.get("ETag", "").strip('"') != sha:
                raise MatrixFailure("artifact_integrity_mismatch")
        return {"size_bytes": size, "sha256": sha, "file": path.name}


def choose_format(inspection: Json, case: Case) -> Json:
    valid = []
    for candidate in inspection["formats"]:
        plan = candidate.get("plan")
        if (
            plan
            and plan["width"] >= case.minimum_spec.width
            and plan["height"] >= case.minimum_spec.height
        ):
            if not case.minimum_spec.audio or plan["audio_codec_family"] != "none":
                valid.append(candidate)
    if not valid:
        raise MatrixFailure("minimum_spec_unavailable")
    return min(valid, key=lambda item: item["plan"]["width"] * item["plan"]["height"])


def verify_probe(probe: Json, case: Case, plan: Json, tolerance_seconds: float) -> Json:
    duration = float(probe["format"]["duration"])
    videos = [s for s in probe["streams"] if s["codec_type"] == "video"]
    audios = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    if not math.isfinite(duration) or duration <= 0 or len(videos) != 1:
        raise MatrixFailure("invalid_artifact")
    video = videos[0]
    if (video["width"], video["height"]) != (plan["width"], plan["height"]):
        raise MatrixFailure("spec_mismatch")
    if (
        video["width"] < case.minimum_spec.width
        or video["height"] < case.minimum_spec.height
    ):
        raise MatrixFailure("minimum_spec_mismatch")
    codecs = {"h264": "h264", "hevc": "hevc", "vp9": "vp9", "av1": "av1"}
    audio_codecs = {"aac": "aac", "opus": "opus", "vorbis": "vorbis"}
    if codecs.get(video["codec_name"]) != plan["video_codec_family"]:
        raise MatrixFailure("codec_mismatch")
    if case.minimum_spec.audio and not audios:
        raise MatrixFailure("audio_missing")
    if plan["audio_codec_family"] == "none":
        if audios:
            raise MatrixFailure("audio_mismatch")
    elif (
        not audios
        or audio_codecs.get(audios[0]["codec_name"]) != plan["audio_codec_family"]
    ):
        raise MatrixFailure("audio_mismatch")
    if plan.get("fps_bucket"):
        try:
            fps = float(Fraction(video.get("avg_frame_rate", "0")))
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            raise MatrixFailure("frame_rate_missing") from exc
        if not math.isfinite(fps) or fps <= 0:
            raise MatrixFailure("frame_rate_missing")
        bucket = "fps_30" if fps <= 30.01 else "fps_60" if fps <= 60.01 else "above_60"
        if bucket != plan["fps_bucket"]:
            raise MatrixFailure(
                "frame_rate_mismatch",
                {
                    "expected": plan["fps_bucket"],
                    "actual": bucket,
                    "avg_frame_rate": video.get("avg_frame_rate"),
                },
            )
    if plan.get("dynamic_range"):
        dynamic_range = (
            "hdr"
            if video.get("color_transfer") in {"smpte2084", "arib-std-b67"}
            else "sdr"
        )
        if dynamic_range != plan["dynamic_range"]:
            raise MatrixFailure("dynamic_range_mismatch")
    names = set(probe["format"]["format_name"].split(","))
    container = plan.get("container_preference")
    if container == "mp4" and "mp4" not in names:
        raise MatrixFailure("container_mismatch")
    if container == "webm" and not names & {"webm", "matroska"}:
        raise MatrixFailure("container_mismatch")
    if case.duration_seconds is not None:
        # Same tolerance rule as workers/runner/verification.py.
        tolerance = max(tolerance_seconds, case.duration_seconds * 0.02)
        if abs(duration - case.duration_seconds) > tolerance:
            raise MatrixFailure(
                "full_duration_mismatch",
                {
                    "expected": case.duration_seconds,
                    "actual": duration,
                    "tolerance": tolerance,
                },
            )
    return {
        "duration_seconds": duration,
        "width": video["width"],
        "height": video["height"],
        "video_codec": video["codec_name"],
        "audio_codecs": [s["codec_name"] for s in audios],
        "avg_frame_rate": video.get("avg_frame_rate"),
        "color_transfer": video.get("color_transfer"),
    }


def failure_result(case: Case, category: str) -> str:
    if category == case.expected_failure_class and case.kind == "protected":
        return "protected_negative"
    if category in {
        "identity_unavailable",
        "login_required",
        "runtime_unavailable",
        "provider_unsupported",
    }:
        return "blocked"
    return "failed"


def run_case(api: Api, case: Case, args: argparse.Namespace, output: Path) -> Json:
    start = time.monotonic()
    result: Json = {
        "sample": case.model_dump(),
        "result": "failed",
        "execution_context": None,
        "qualification_gaps": case.qualification_gaps(),
    }
    try:
        intent = api.request(
            "POST",
            "/api/download-intents",
            json={"input": case.url},
            headers={"Idempotency-Key": uuid4().hex},
        )
        result["intent_id"] = intent["id"]
        intent = api.poll(
            f"/api/download-intents/{intent['id']}",
            {"queued", "resolving", "cancelling"},
            args.resolve_timeout,
        )
        if intent["status"] != "ready":
            failure = intent.get("failure") or {}
            result["failure"] = failure
            result["failure_attempt"] = failure.get("evidence") or {}
            raise MatrixFailure(
                failure.get("failure_class")
                or intent.get("reason_code")
                or intent["status"],
                failure,
            )
        inspection = api.request("GET", f"/api/inspections/{intent['inspection_id']}")
        result["inspection_id"] = inspection["id"]
        result["execution_context"] = inspection.get("execution_context")
        result["actual_media_id"] = inspection["provider_media_id"]
        if inspection["provider_media_id"] != case.expected_media_id:
            raise MatrixFailure(
                "work_identity_mismatch", {"actual": inspection["provider_media_id"]}
            )
        context = result["execution_context"]
        if not context or context["provider_key"] != case.platform:
            raise MatrixFailure("execution_context_missing_or_mismatched")
        if case.needs_identity and not context["identity_used"]:
            raise MatrixFailure("identity_unavailable", {"identity_used": False})
        if case.kind == "protected":
            raise MatrixFailure("protected_content_not_rejected")
        if inspection["protection_state"] != "clear":
            raise MatrixFailure("content_protected")
        if inspection.get("access_decision", "downloadable") != "downloadable":
            raise MatrixFailure("content_protected")
        result["content_evidence"] = {
            key: inspection.get(key)
            for key in ("access_decision", "entitlement_state", "protection_state")
        }
        chosen = choose_format(inspection, case)
        result["confirmed_plan"] = chosen["plan"]
        job = api.request(
            "POST",
            "/api/downloads",
            json={"inspection_id": inspection["id"], "format_id": chosen["id"]},
            headers={"Idempotency-Key": uuid4().hex},
        )
        result["job_id"] = job["id"]
        job = api.poll(
            f"/api/downloads/{job['id']}",
            {"queued", "running", "retry_wait"},
            args.download_timeout,
        )
        result["execution_context"] = job.get("execution_context")
        if job["status"] != "succeeded" or not job["file_available"]:
            raise MatrixFailure(
                job.get("error_code") or job["status"], {"stage": job.get("stage")}
            )
        if not job.get("execution_context") or job["execution_context"] != context:
            raise MatrixFailure("context_changed")
        target = output / f"{case.id}.media"
        result["artifact"] = api.file(
            job["id"], target, args.max_file_bytes, args.download_timeout
        )
        probe = json.loads(
            run_command(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(target),
                ],
                timeout=30,
                log=output / f"{case.id}.ffprobe.json",
            )
        )
        result["ffprobe"] = verify_probe(
            probe, case, chosen["plan"], args.duration_tolerance
        )
        run_command(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(target),
                "-map",
                "0:v",
                "-map",
                "0:a?",
                "-f",
                "null",
                "-",
            ],
            timeout=args.decode_timeout,
            log=output / f"{case.id}.decode.log",
        )
        result["full_decode_exit_code"] = 0
        # User decision (Design 17 §3.4): the current datacenter upstream
        # is valid with the logged-in session. Keep actual egress diagnostics.
        if (
            case.platform == "youtube"
            and context.get("egress_class") != "residential"
            and not context.get("identity_used")
        ):
            result["qualification_gaps"].append(
                "YouTube datacenter egress requires logged-in identity"
            )
        if case.needs_identity and not (
            args.cookie_source_label or getattr(args, "reuse_cookie_source", False)
        ):
            result["qualification_gaps"].append("cookie-source was not cold-started")
        result["result"] = "blocked" if result["qualification_gaps"] else "passed"
        if result["qualification_gaps"]:
            result["failure_class"] = "sample_evidence_missing"
    except MatrixFailure as exc:
        result.update(
            {
                "result": failure_result(case, exc.category),
                "failure_class": exc.category,
                "evidence": exc.evidence,
            }
        )
        if result["result"] == "protected_negative" and result["qualification_gaps"]:
            result["result"] = "blocked"
        if (
            result["result"] == "protected_negative"
            and case.expected_gate is not None
            and exc.evidence.get("gate") != case.expected_gate
        ):
            result["result"] = "failed"
    except (
        httpx.HTTPError,
        subprocess.TimeoutExpired,
        OSError,
        ValueError,
        KeyError,
        ZeroDivisionError,
    ) as exc:
        result.update(
            {
                "result": "failed",
                "failure_class": "matrix_runtime_error",
                "evidence": {"exception_type": type(exc).__name__},
            }
        )
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return result


def platform_results(results: list[Json]) -> Json:
    summary = {}
    for platform in sorted({r["sample"]["platform"] for r in results}):
        positives = [
            r
            for r in results
            if r["sample"]["platform"] == platform and r["sample"]["kind"] == "positive"
        ]
        summary[platform] = (
            "passed"
            if len(positives) >= 2 and all(r["result"] == "passed" for r in positives)
            else "blocked"
            if any(r["result"] == "blocked" for r in positives)
            else "failed"
        )
    return summary


def write_report(report: Json, output: Path) -> None:
    (output / "matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "# 冷启动矩阵",
        "",
        "本次运行是当前 worktree 的基线，不能作为其他阶段或全部平台的验收结论。",
        "",
        f"平台结果：{json.dumps(report.get('platforms', {}), ensure_ascii=False)}",
        "",
        "| 平台 | 样本 | 结果 | 层级 / 客户端 | 出口类别 / IP | "
        "身份 | 秒 | 失败类别 / 证据 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["results"]:
        ctx = row.get("execution_context") or row.get("failure_attempt") or {}
        evidence = (
            json.dumps(
                row.get("evidence", row.get("qualification_gaps", [])),
                ensure_ascii=False,
            )
            .replace("|", "\\|")
            .replace("\n", " ")
        )
        lines.append(
            f"| {row['sample']['platform']} | {row['sample']['id']} "
            f"| {row['result']} | {ctx.get('resolved_layer', ctx.get('layer', '—'))} "
            f"/ {ctx.get('client', '—')} | {ctx.get('egress_class', '—')} "
            f"/ {ctx.get('egress_observed_ip') or '未观测'} "
            f"| {ctx.get('identity_used', '未知')} | {row['elapsed_seconds']} "
            f"| {row.get('failure_class', '—')} / {evidence} |"
        )
    lines += [
        "",
        "| 样本 | Artifact 字节 | SHA-256 "
        "| ffprobe 时长 / 尺寸 / 编解码器 | 全片解码 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["results"]:
        artifact = row.get("artifact")
        if not artifact:
            continue
        probe = row.get("ffprobe") or {}
        lines.append(
            f"| {row['sample']['id']} | {artifact['size_bytes']} "
            f"| {artifact['sha256']} | {probe.get('duration_seconds', '未通过')} "
            f"/ {probe.get('width', '—')}×{probe.get('height', '—')} "
            f"/ {probe.get('video_codec', '—')}+"
            f"{','.join(probe.get('audio_codecs', []))} "
            f"| {row.get('full_decode_exit_code', '未完成')} |"
        )
    if report.get("setup_failure"):
        lines += [
            "",
            f"启动失败：{json.dumps(report['setup_failure'], ensure_ascii=False)}",
        ]
    (output / "matrix.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--platforms", help="Comma-separated Registry keys")
    mode.add_argument("--all", action="store_true")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8111")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).parent / "fixtures/coldstart_cases.json",
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--runtime-owner", default="coldstart", help="Runtime lock owner label"
    )
    identity_mode = parser.add_mutually_exclusive_group()
    identity_mode.add_argument(
        "--cookie-source-label",
        help="LaunchAgent label to restart",
    )
    identity_mode.add_argument(
        "--reuse-cookie-source",
        action="store_true",
        help="Reuse the connected shared host identity service without restarting it",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "artifacts/coldstart"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
    )
    parser.add_argument("--resolve-timeout", type=float, default=150)
    parser.add_argument("--download-timeout", type=float, default=900)
    parser.add_argument("--decode-timeout", type=float, default=900)
    parser.add_argument("--max-file-bytes", type=int, default=2 * 1024**3)
    parser.add_argument(
        "--duration-tolerance",
        type=float,
        default=3,
        help="Runner tolerance seconds (default 3); also allows 2%% relative error",
    )
    args = parser.parse_args()
    args.env_file = args.env_file.resolve()
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT / "artifacts/coldstart"):
        parser.error("output must be inside artifacts/coldstart/")
    if (
        any(
            getattr(args, name) <= 0
            for name in (
                "resolve_timeout",
                "download_timeout",
                "decode_timeout",
                "max_file_bytes",
            )
        )
        or not 0 <= args.duration_tolerance <= 30
    ):
        parser.error("timeouts/size must be positive; tolerance must be 0..30")
    try:
        cases = load_cases(args.cases)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=False)
    report: Json = {
        "mode": "all" if args.all else "platforms",
        "created_at": datetime.now(UTC).isoformat(),
        "baseline_only": True,
        "runtime": {},
        "results": [],
    }
    api = Api(args.api_base_url)

    def interrupted(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    previous_handler = signal.signal(signal.SIGTERM, interrupted)
    try:
        with runtime(args, args.output, report["runtime"]):
            api.request("GET", "/health/ready")
            api.login()
            items = api.request("GET", "/api/providers")["items"]
            registry = {item["key"] for item in items if item["registered"]}
            report["registry"] = sorted(registry)
            selected = select_cases(cases, registry, args.platforms)
            for case in selected:
                print(f"Running {case.id}", flush=True)
                result = run_case(api, case, args, args.output)
                report["results"].append(result)
                report["platforms"] = platform_results(report["results"])
                write_report(report, args.output)
                print(
                    f"{case.id}: {result['result']} {result.get('failure_class', '')}",
                    flush=True,
                )
    except KeyboardInterrupt:
        report["setup_failure"] = {"category": "interrupted"}
    except (
        MatrixFailure,
        ValueError,
        httpx.HTTPError,
        subprocess.TimeoutExpired,
        OSError,
    ) as exc:
        report["setup_failure"] = {
            "category": str(exc)
            if isinstance(exc, (MatrixFailure, ValueError))
            else type(exc).__name__
        }
        if isinstance(exc, MatrixFailure):
            report["setup_failure"]["evidence"] = exc.evidence
    finally:
        api.client.close()
        write_report(report, args.output)
        signal.signal(signal.SIGTERM, previous_handler)
    print(
        json.dumps(
            {
                "report": str(args.output / "matrix.json"),
                "counts": dict(Counter(r["result"] for r in report["results"])),
            },
            ensure_ascii=False,
        )
    )
    if report.get("setup_failure") or report["runtime"].get("restoration_error"):
        return 2
    return (
        0
        if report.get("platforms")
        and all(v == "passed" for v in report["platforms"].values())
        and all(
            r["result"] in {"passed", "protected_negative"} for r in report["results"]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
