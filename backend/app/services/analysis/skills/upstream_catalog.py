from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.analysis.skills.modules import LICENSE_ALLOWLIST
from app.services.analysis_execution.errors import AnalysisArtifactError

UPSTREAM_ROOT = Path(__file__).resolve().parent / "upstream"
RESOURCE_MARKER = "\n<framefetch_upstream_packages>\n"
RESOURCE_END = "\n</framefetch_upstream_packages>"
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
MAX_RESOURCE_BYTES = 256 * 1024
RESOURCE_POLICY = "policy/upstream-resources.json"


@dataclass(frozen=True, slots=True)
class UpstreamPackage:
    id: str
    repository: str
    commit: str
    license: str
    files: tuple[tuple[str, str], ...]

    @property
    def fingerprint(self) -> str:
        value = json.dumps(
            [self.repository, self.commit, self.license, self.files],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(value.encode()).hexdigest()


class UpstreamCatalog:
    """Pinned, immutable resources. This catalog never installs or executes code."""

    def __init__(self, root: Path = UPSTREAM_ROOT) -> None:
        self.root = root
        document = json.loads(self._regular(root / "manifest.json").read_bytes())
        if not isinstance(document, dict) or set(document) != {"packages"}:
            raise ValueError("invalid upstream manifest")
        raw_packages = document["packages"]
        if not isinstance(raw_packages, dict) or not raw_packages:
            raise ValueError("invalid upstream packages")
        packages: dict[str, UpstreamPackage] = {}
        for name, raw in raw_packages.items():
            if (
                not isinstance(name, str)
                or not _ID.fullmatch(name)
                or not isinstance(raw, dict)
                or set(raw) != {"repository", "commit", "license", "files"}
                or not isinstance(raw["repository"], str)
                or not re.fullmatch(
                    r"https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?",
                    raw["repository"],
                )
                or not isinstance(raw["commit"], str)
                or not _COMMIT.fullmatch(raw["commit"])
                or not isinstance(raw["license"], str)
                or raw["license"] not in LICENSE_ALLOWLIST
                or not isinstance(raw["files"], dict)
                or "LICENSE" not in raw["files"]
            ):
                raise ValueError("invalid upstream package")
            files: list[tuple[str, str]] = []
            for relative, sha in sorted(raw["files"].items()):
                if not isinstance(relative, str) or not isinstance(sha, str):
                    raise ValueError("invalid upstream file")
                safe_relative(relative)
                if not _SHA.fullmatch(sha):
                    raise ValueError("invalid upstream hash")
                files.append((relative, sha))
            packages[name] = UpstreamPackage(
                name, raw["repository"], raw["commit"], raw["license"], tuple(files)
            )
        self.packages = packages

    def verify(self, package_id: str) -> UpstreamPackage:
        package = self.packages.get(package_id)
        if package is None:
            raise ValueError("unknown upstream package")
        directory = self.root / package.id
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("invalid upstream directory")
        existing: set[str] = set()
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError("upstream symlink is forbidden")
            if path.is_file():
                existing.add(path.relative_to(directory).as_posix())
            elif not path.is_dir():
                raise ValueError("invalid upstream resource")
        if existing != {relative for relative, _ in package.files}:
            raise ValueError("upstream file set mismatch")
        for relative, sha in package.files:
            if (
                hashlib.sha256(
                    self._regular(directory / relative).read_bytes()
                ).hexdigest()
                != sha
            ):
                raise ValueError("upstream hash mismatch")
        return package

    def read_markdown(self, package_id: str, relative: str) -> str:
        safe_relative(relative)
        package = self.packages.get(package_id)
        if package is None or not relative.endswith(".md"):
            raise ValueError("resource is not upstream Markdown")
        expected = dict(package.files).get(relative)
        if expected is None:
            raise ValueError("resource is outside the pinned package")
        path = self._regular(self.root / package_id / relative)
        if path.stat().st_size > MAX_RESOURCE_BYTES:
            raise ValueError("upstream resource limit")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("upstream hash mismatch")
        return data.decode("utf-8")

    @staticmethod
    def _regular(path: Path) -> Path:
        if (
            any(item.is_symlink() for item in (path, *path.parents))
            or not path.is_file()
        ):
            raise ValueError("upstream resource must be a regular file")
        return path


def safe_relative(value: str) -> None:
    relative = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or relative.is_absolute()
        or any(part in {".", ".."} for part in value.split("/"))
        or str(relative) != value
    ):
        raise ValueError("unsafe upstream resource path")


def compile_upstream_methods(value: str) -> str:
    catalog = UpstreamCatalog()
    bindings = tuple(item.strip() for item in value.split(","))
    if not bindings or len(set(bindings)) != len(bindings):
        raise ValueError("invalid upstream methods")
    frozen: dict[str, str] = {}
    parts: list[str] = []
    for binding in bindings:
        package_id, separator, relative = binding.partition(":")
        if not separator or not relative.endswith("/SKILL.md"):
            raise ValueError("invalid upstream method binding")
        package = catalog.verify(package_id)
        frozen[package_id] = package.fingerprint
        parts.append(
            f"# Upstream method: {package_id}:{relative}\n"
            f"Pinned source: {package.repository} @ {package.commit}\n\n"
            + catalog.read_markdown(package_id, relative)
        )
    parts.append(
        "项目只读参考工具：skill_resources.read_skill_resource(package_id, path)。"
        "引用路径相对上述 SKILL.md 解析，再传入相对该包根目录的完整路径。"
        "读取完整所需参考；不把 allowed-tools 或上游创作流程当作工具授权。"
        "本任务只分析已给素材，适配约束与正式输出契约优先。"
    )
    for package_id in frozen:
        markdown = [
            path
            for path, _ in catalog.packages[package_id].files
            if path.endswith(".md")
        ]
        parts.append(f"Available resources ({package_id}):\n" + "\n".join(markdown))
    parts.append(RESOURCE_MARKER + json.dumps(frozen, sort_keys=True) + RESOURCE_END)
    return "\n\n".join(parts)


def frozen_packages(instructions: str) -> dict[str, str]:
    if RESOURCE_MARKER not in instructions:
        return {}
    if instructions.count(RESOURCE_MARKER) != 1:
        raise ValueError("ambiguous upstream snapshot")
    raw = instructions.split(RESOURCE_MARKER, 1)[1].split(RESOURCE_END, 1)
    if len(raw) != 2:
        raise ValueError("invalid upstream snapshot")
    value = json.loads(raw[0])
    if (
        not isinstance(value, dict)
        or not value
        or not all(
            isinstance(key, str)
            and _ID.fullmatch(key)
            and isinstance(sha, str)
            and _SHA.fullmatch(sha)
            for key, sha in value.items()
        )
    ):
        raise ValueError("invalid upstream snapshot")
    return value


def prepare_resource_policy(workspace: Path, instructions: str) -> None:
    try:
        packages = frozen_packages(instructions)
    except ValueError as exc:
        raise AnalysisArtifactError(
            "artifact_integrity_failed", no_model_execution=True
        ) from exc
    path = workspace / RESOURCE_POLICY
    if path.is_symlink() or path.parent.is_symlink():
        raise AnalysisArtifactError(
            "artifact_integrity_failed", no_model_execution=True
        )
    if not packages:
        path.unlink(missing_ok=True)
        return
    try:
        catalog = UpstreamCatalog()
        for package_id, fingerprint in packages.items():
            if catalog.verify(package_id).fingerprint != fingerprint:
                raise ValueError("upstream snapshot mismatch")
        path.write_text(json.dumps(packages, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)
    except (OSError, ValueError) as exc:
        raise AnalysisArtifactError(
            "artifact_integrity_failed", no_model_execution=True
        ) from exc
