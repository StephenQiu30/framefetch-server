"""Reviewed import of third-party Agent Skills as pinned Markdown modules.

Only Markdown is vendored, byte-for-byte, next to its license. Scripts, MCP or
plugin manifests, installers and binaries are dropped and never executed.
Imported text is scanned for prompt-injection patterns; any finding blocks the
import until a maintainer has reviewed it. Product Skills opt in to the
imported sections explicitly, so importing never changes a running Skill.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from app.services.analysis.skills.frontmatter import load_frontmatter
from app.services.analysis.skills.modules import LICENSE_ALLOWLIST, markdown_sections

MAX_MARKDOWN_BYTES = 64_000
_LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SOURCE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        (
            "override-instructions",
            r"\b(ignore|disregard|forget|override)\b[^\n]{0,40}\b(previous|prior|"
            r"above|earlier|all|system)\b[^\n]{0,20}\b(instructions?|prompts?|rules)",
        ),
        ("system-prompt", r"\bsystem prompt\b|\bdeveloper message\b"),
        (
            "execute-command",
            r"\b(run|execute|invoke)\b[^\n]{0,30}\b(command|script|shell|bash|"
            r"python|terminal)\b",
        ),
        ("network-fetch", r"\b(curl|wget)\b|https?://"),
        (
            "read-secrets",
            r"(\.env\b|id_rsa|\.ssh/|credentials|api[_ -]?key|access[_ -]?token|"
            r"password|secret)",
        ),
        (
            "exfiltrate",
            r"\b(send|upload|post|exfiltrat\w*|forward)\b[^\n]{0,40}\b(to|http)\b",
        ),
        ("hidden-comment", r"<!--"),
        ("encoded-payload", r"[A-Za-z0-9+/]{120,}={0,2}"),
        ("zero-width", "[​-‏⁠﻿]"),
        ("tool-grant", r"^\s*allowed-tools\s*:|\bmcp\b"),
        (
            "override-instructions-zh",
            r"(忽略|无视|覆盖)[^\n]{0,10}(之前|以上|前面|系统)[^\n]{0,10}"
            r"(指令|提示|要求|规则)",
        ),
        ("system-prompt-zh", r"系统提示词|开发者消息"),
        ("execute-command-zh", r"(执行|运行)[^\n]{0,10}(命令|脚本|终端)"),
        ("read-secrets-zh", r"(读取|获取|发送)[^\n]{0,15}(密钥|密码|令牌|环境变量)"),
    )
)


@dataclass(frozen=True, slots=True)
class InjectionFinding:
    path: str
    line: int
    pattern: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class ImportedFile:
    source_path: str
    destination: str
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class ImportPlan:
    source: str
    repository: str
    commit: str
    subdirectory: str
    license: str
    license_text: bytes | None
    files: tuple[ImportedFile, ...]
    dropped: tuple[str, ...]
    findings: tuple[InjectionFinding, ...]


class SkillImportRejected(ValueError):
    pass


def detect_license(text: str) -> str | None:
    """Recognize an allowlisted license from its canonical text."""
    normalized = " ".join(text.split())
    if "Permission is hereby granted, free of charge" in normalized:
        return "MIT"
    if "Apache License" in normalized and "Version 2.0" in normalized:
        return "Apache-2.0"
    if "Redistribution and use in source and binary forms" in normalized:
        return (
            "BSD-3-Clause"
            if "Neither the name" in normalized or "neither the name" in normalized
            else "BSD-2-Clause"
        )
    if "Creative Commons Attribution 4.0" in normalized:
        return "CC-BY-4.0"
    return None


def scan_prompt_injection(path: str, text: str) -> tuple[InjectionFinding, ...]:
    findings: list[InjectionFinding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for name, pattern in _INJECTION_PATTERNS:
            if pattern.search(line):
                findings.append(
                    InjectionFinding(path, line_no, name, line.strip()[:160])
                )
    return tuple(findings)


def plan_import(
    checkout: Path,
    subdirectory: str,
    *,
    source: str,
    repository: str,
    commit: str,
) -> ImportPlan:
    if _SOURCE.fullmatch(source) is None:
        raise SkillImportRejected("source must be a lowercase kebab-case name")
    if _COMMIT.fullmatch(commit) is None:
        raise SkillImportRejected("commit must be a full 40-character SHA")
    if not repository.startswith("https://github.com/"):
        raise SkillImportRejected("repository must be an https GitHub URL")
    relative = PurePosixPath(subdirectory)
    if relative.is_absolute() or ".." in relative.parts:
        raise SkillImportRejected("subdirectory must stay inside the repository")
    root = checkout.resolve(strict=True)
    requested = root / relative
    if any(part.is_symlink() for part in (requested, *requested.parents)):
        raise SkillImportRejected("import path must not contain symlinks")
    base = requested.resolve(strict=True)
    if not base.is_relative_to(root):
        raise SkillImportRejected("path must be a file or directory in the checkout")
    single_file = base.is_file()
    if single_file and base.suffix.lower() != ".md":
        raise SkillImportRejected("a single imported file must be Markdown")
    if not single_file and not base.is_dir():
        raise SkillImportRejected("path must be a file or directory in the checkout")

    skill_dir = _skill_directory(root, base)
    license_name, license_text = _repository_license(root, skill_dir)
    files: list[ImportedFile] = []
    dropped: list[str] = []
    findings: list[InjectionFinding] = []
    candidates = [base] if single_file else sorted(base.rglob("*"))
    for path in candidates:
        if path.is_dir() and not path.is_symlink():
            continue
        shown = path.relative_to(root).as_posix()
        if (
            path.is_symlink()
            or path.suffix.lower() != ".md"
            or path.stat().st_size > MAX_MARKDOWN_BYTES
        ):
            dropped.append(shown)
            continue
        content = path.read_bytes()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            dropped.append(shown)
            continue
        name = (
            f"{skill_dir.name}-{path.name}"
            if single_file
            else _flatten(path.relative_to(base).as_posix(), base.name)
        )
        files.append(
            ImportedFile(
                source_path=shown,
                destination=f"{source}/{name}",
                content=content,
            )
        )
        findings.extend(scan_prompt_injection(shown, text))
    if not files:
        raise SkillImportRejected("no Markdown files to import")
    destinations = [item.destination for item in files]
    if len(set(destinations)) != len(destinations):
        raise SkillImportRejected("imported file names collide after flattening")
    return ImportPlan(
        source=source,
        repository=repository.rstrip("/"),
        commit=commit,
        subdirectory=relative.as_posix(),
        license=license_name,
        license_text=license_text,
        files=tuple(files),
        dropped=tuple(dropped),
        findings=tuple(findings),
    )


def apply_import(
    plan: ImportPlan,
    modules_root: Path,
    notice: Path,
    *,
    accept_findings: bool,
    today: date,
) -> tuple[str, ...]:
    """Vendor the plan's Markdown and register one module per sectioned file."""
    if plan.findings and not accept_findings:
        raise SkillImportRejected(
            f"{len(plan.findings)} prompt-injection findings need review; "
            "re-run with --accept-findings only after reading every finding"
        )
    manifest_path = modules_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    modules: dict[str, dict[str, object]] = manifest["modules"]
    for item in plan.files:
        target = modules_root / item.destination
        if target.exists() and target.read_bytes() != item.content:
            raise SkillImportRejected(
                f"{item.destination} already exists with different content; "
                "remove the old version deliberately before upgrading"
            )
    source_dir = modules_root / plan.source
    source_dir.mkdir(exist_ok=True)
    if plan.license_text is not None:
        (source_dir / "LICENSE").write_bytes(plan.license_text)
    registered: list[str] = []
    for item in plan.files:
        (modules_root / item.destination).write_bytes(item.content)
        headings = _headings(item.content.decode("utf-8"))
        if not headings:
            continue
        module_id = _module_id(plan.source, item.destination)
        modules[module_id] = {
            "path": item.destination,
            "sha256": item.sha256,
            "license": plan.license,
            "source_url": (f"{plan.repository}/blob/{plan.commit}/{item.source_path}"),
            "sections": list(headings),
        }
        registered.append(module_id)
    manifest["modules"] = dict(sorted(modules.items()))
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with notice.open("a", encoding="utf-8") as stream:
        stream.write(_notice_entry(plan, today, registered))
    return tuple(registered)


def _skill_directory(root: Path, base: Path) -> Path:
    """The nearest directory holding SKILL.md, for frontmatter license lookup."""
    current = base if base.is_dir() else base.parent
    while current.is_relative_to(root):
        if (current / "SKILL.md").is_file():
            return current
        if current == root:
            break
        current = current.parent
    return base if base.is_dir() else base.parent


def _repository_license(root: Path, base: Path) -> tuple[str, bytes | None]:
    for name in _LICENSE_FILES:
        candidate = root / name
        if candidate.is_file() and not candidate.is_symlink():
            content = candidate.read_bytes()
            detected = detect_license(content.decode("utf-8", errors="replace"))
            if detected is None:
                raise SkillImportRejected(
                    f"{name} is not an allowlisted license: "
                    f"{', '.join(sorted(LICENSE_ALLOWLIST))}"
                )
            return detected, content
    skill = base / "SKILL.md"
    if skill.is_file():
        document = skill.read_text(encoding="utf-8").replace("\r\n", "\n")
        if document.startswith("---\n") and "\n---\n" in document[4:]:
            raw = document[4:].split("\n---\n", 1)[0]
            declared = load_frontmatter(raw, skill).get("license")
            if isinstance(declared, str) and declared.strip() in LICENSE_ALLOWLIST:
                return declared.strip(), None
    raise SkillImportRejected("no allowlisted license was found; import refused")


def _flatten(within: str, base_name: str) -> str:
    parts = PurePosixPath(within).parts
    if parts == ("SKILL.md",):
        return f"{base_name}-SKILL.md"
    return "-".join(parts)


def _module_id(source: str, destination: str) -> str:
    stem = PurePosixPath(destination).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return f"{source}-{slug}"


def _headings(text: str) -> tuple[str, ...]:
    try:
        return tuple(markdown_sections(text))
    except ValueError as exc:
        raise SkillImportRejected(str(exc)) from None


def _notice_entry(plan: ImportPlan, today: date, registered: list[str]) -> str:
    lines = [
        "",
        f"## {plan.source} ({today.isoformat()})",
        "",
        f"- Source: {plan.repository}/tree/{plan.commit}/{plan.subdirectory}",
        f"- Reviewed commit: `{plan.commit}`",
        f"- License: {plan.license}"
        + ("" if plan.license_text else " (declared in SKILL.md frontmatter)"),
        "- Imported Markdown (unmodified): "
        + ", ".join(f"`{item.destination}`" for item in plan.files),
        "- Registered modules: "
        + (", ".join(f"`{item}`" for item in registered) or "none"),
        "- Dropped, never vendored or executed: "
        + (", ".join(f"`{item}`" for item in plan.dropped) or "none"),
        "- Prompt-injection scan: "
        + (
            f"{len(plan.findings)} findings reviewed and accepted"
            if plan.findings
            else "no findings"
        ),
        "- Local use: none until a product Skill opts in with "
        "`video-server-modules`; update this entry when it does.",
        "",
    ]
    return "\n".join(lines)
