from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

LICENSE_ALLOWLIST = frozenset(
    {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC-BY-4.0"}
)
_MANIFEST = Path(__file__).resolve().parent / "modules" / "manifest.json"
_MODULE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SourceModule:
    path: str
    sha256: str
    license: str
    source_url: str
    sections: tuple[str, ...]


def load_manifest(path: Path = _MANIFEST) -> dict[str, SourceModule]:
    """Read the pinned upstream module manifest written by skill import."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"modules"}:
        raise ValueError(f"invalid analysis source manifest: {path}")
    raw_modules = document["modules"]
    if not isinstance(raw_modules, dict):
        raise ValueError(f"invalid analysis source manifest: {path}")
    modules: dict[str, SourceModule] = {}
    for module_id, raw in raw_modules.items():
        if (
            _MODULE_ID.fullmatch(module_id) is None
            or not isinstance(raw, dict)
            or set(raw) != {"path", "sha256", "license", "source_url", "sections"}
        ):
            raise ValueError(f"invalid analysis source module: {module_id}")
        relative = PurePosixPath(str(raw["path"]))
        sections = raw["sections"]
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or ".." in relative.parts
            or not relative.name.endswith(".md")
            or _SHA256.fullmatch(str(raw["sha256"])) is None
            or raw["license"] not in LICENSE_ALLOWLIST
            or not str(raw["source_url"]).startswith("https://github.com/")
            or not isinstance(sections, list)
            or not sections
            or not all(isinstance(item, str) and item for item in sections)
        ):
            raise ValueError(f"invalid analysis source module: {module_id}")
        modules[module_id] = SourceModule(
            path=str(relative),
            sha256=str(raw["sha256"]),
            license=str(raw["license"]),
            source_url=str(raw["source_url"]),
            sections=tuple(sections),
        )
    return modules


SOURCE_MODULES: dict[str, SourceModule] = load_manifest()


def compile_source_module(module_id: str, root: Path) -> str:
    module = SOURCE_MODULES.get(module_id)
    if module is None:
        raise ValueError(f"unknown analysis source module: {module_id}")
    path = root / module.path
    if (
        any(path_part.is_symlink() for path_part in (root, *path.parents))
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 64_000
    ):
        raise ValueError(f"invalid analysis source module file: {path}")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != module.sha256:
        raise ValueError(f"analysis source module hash mismatch: {path}")
    text = content.decode("utf-8").replace("\r\n", "\n")
    selected = _select_sections(text, module.sections, path)
    return (
        f"# Source module: {module_id}\n"
        f"Pinned source: {module.source_url}\n\n"
        f"{selected}"
    )


def _select_sections(text: str, headings: tuple[str, ...], path: Path) -> str:
    lines = text.splitlines()
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            if current in blocks:
                raise ValueError(f"duplicate analysis source section: {path}")
            blocks[current] = [line]
        elif current is not None:
            blocks[current].append(line)
    if len(set(headings)) != len(headings) or any(
        item not in blocks for item in headings
    ):
        raise ValueError(f"missing analysis source section: {path}")
    return "\n\n".join("\n".join(blocks[item]).strip() for item in headings)
