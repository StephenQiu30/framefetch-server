"""Import a third-party Agent Skill as pinned, reviewed Markdown modules.

Run from backend/ on a maintainer machine (network access is needed only here;
the analysis worker never fetches Skills):

    uv run python -m app.workers.skill_import \\
        --repository https://github.com/owner/repo \\
        --commit <40-char sha> --path skills/some-skill --source some-source

The command prints the plan (license, kept and dropped files, injection
findings) and refuses to write while findings are unreviewed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.services.analysis.skills.importing import (
    ImportPlan,
    SkillImportRejected,
    apply_import,
    plan_import,
)

_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "services" / "analysis" / "skills"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="引入经审查的第三方 Skill Markdown")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--path", required=True, help="Skill 目录在仓库中的路径")
    parser.add_argument("--source", required=True, help="本地来源名（kebab-case）")
    parser.add_argument(
        "--accept-findings",
        action="store_true",
        help="逐条阅读注入扫描结果后才可使用",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="skill-import-") as workdir:
            checkout = Path(workdir) / "repo"
            _checkout(args.repository, args.commit, checkout)
            plan = plan_import(
                checkout,
                args.path,
                source=args.source,
                repository=args.repository,
                commit=args.commit,
            )
            _print_plan(plan)
            if args.dry_run:
                return 0
            registered = apply_import(
                plan,
                _SKILLS_ROOT / "modules",
                _SKILLS_ROOT / "NOTICE.md",
                accept_findings=args.accept_findings,
                today=datetime.now(UTC).date(),
            )
    except (SkillImportRejected, subprocess.CalledProcessError) as exc:
        print(f"导入被拒绝：{exc}", file=sys.stderr)
        return 2
    print("已登记模块：" + (", ".join(registered) or "无（文件没有二级标题）"))
    print(
        "下一步：在产品 Skill 中用 video-server-modules 选用，并补 NOTICE 的 Local use"
    )
    return 0


def _checkout(repository: str, commit: str, target: Path) -> None:
    """Fetch exactly one commit; no hooks, submodules or LFS run."""
    git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never"]
    subprocess.run([*git, "init", "--quiet", str(target)], check=True)
    subprocess.run(
        [
            *git,
            "-C",
            str(target),
            "fetch",
            "--quiet",
            "--depth",
            "1",
            "--no-recurse-submodules",
            repository,
            commit,
        ],
        check=True,
        timeout=120,
    )
    subprocess.run(
        [
            *git,
            "-C",
            str(target),
            "-c",
            "advice.detachedHead=false",
            "checkout",
            "--quiet",
            "FETCH_HEAD",
        ],
        check=True,
        env={"GIT_LFS_SKIP_SMUDGE": "1", "PATH": "/usr/bin:/bin:/opt/homebrew/bin"},
    )
    head = subprocess.run(
        [*git, "-C", str(target), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != commit:
        raise SkillImportRejected("fetched commit does not match the requested SHA")


def _print_plan(plan: ImportPlan) -> None:
    print(f"来源：{plan.repository} @ {plan.commit}（{plan.subdirectory}）")
    print(f"许可证：{plan.license}")
    print("保留 Markdown：")
    for item in plan.files:
        print(f"  {item.source_path} -> modules/{item.destination}")
    print("丢弃（不引入、不执行）：")
    for dropped in plan.dropped or ("无",):
        print(f"  {dropped}")
    print(f"注入扫描：{len(plan.findings)} 处")
    for finding in plan.findings:
        print(f"  {finding.path}:{finding.line} [{finding.pattern}] {finding.excerpt}")


if __name__ == "__main__":
    raise SystemExit(main())
