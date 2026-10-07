from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from app.services.analysis.rules.contracts import contract_for
from app.services.analysis.rules.enums import AnalysisInputKind, AnalysisResultContract
from app.services.analysis.skills.frontmatter import (
    bounded,
    load_frontmatter,
    required_string,
    string_mapping,
)
from app.services.analysis.skills.models import AnalysisSkill
from app.services.analysis.skills.modules import compile_source_module

_SKILL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REFERENCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")
_TOP_LEVEL_FIELDS = {"name", "description", "license", "metadata"}
_REQUIRED_PRODUCT_FIELDS = {
    "framefetch-server-display-name",
    "framefetch-server-default-prompt",
    "framefetch-server-order",
    "framefetch-server-input-kinds",
    "framefetch-server-output-contract",
}
_OPTIONAL_PRODUCT_FIELDS = {"framefetch-server-references", "framefetch-server-modules"}


def load_skill(path: Path) -> AnalysisSkill:
    _validate_skill_tree(path)
    document = _read_markdown(path, maximum=128_000).replace("\r\n", "\n")
    if not document.startswith("---\n") or "\n---\n" not in document[4:]:
        raise ValueError(f"invalid analysis skill frontmatter: {path}")
    raw_metadata, body = document[4:].split("\n---\n", 1)
    metadata = load_frontmatter(raw_metadata, path)
    if set(metadata) != _TOP_LEVEL_FIELDS:
        raise ValueError(f"unknown analysis skill frontmatter field: {path}")
    required_string(metadata["license"], "license", path, maximum=128)
    product = string_mapping(metadata["metadata"], path)
    if not _REQUIRED_PRODUCT_FIELDS <= set(product) or not set(product) <= (
        _REQUIRED_PRODUCT_FIELDS | _OPTIONAL_PRODUCT_FIELDS
    ):
        raise ValueError(f"invalid analysis skill product metadata: {path}")
    skill_id = required_string(metadata["name"], "name", path, maximum=64)
    if skill_id != path.parent.name or _SKILL_ID.fullmatch(skill_id) is None:
        raise ValueError(f"invalid analysis skill id: {path}")
    input_kinds = _input_kinds(product["framefetch-server-input-kinds"], path)
    result_contract = _result_contract(
        product["framefetch-server-output-contract"], path
    )
    _validate_contract(input_kinds, result_contract, path)
    raw_modules = product.get("framefetch-server-modules")
    instructions = _compile_instructions(
        body, product.get("framefetch-server-references"), raw_modules, path
    )
    return AnalysisSkill(
        id=skill_id,
        display_name=bounded(product["framefetch-server-display-name"], path, 128),
        description=required_string(
            metadata["description"], "description", path, maximum=1024
        ),
        default_prompt=bounded(
            product["framefetch-server-default-prompt"], path, 4_000
        ),
        instructions=instructions,
        instructions_sha256=hashlib.sha256(instructions.encode()).hexdigest(),
        order=_order(product["framefetch-server-order"], path),
        input_kinds=input_kinds,
        result_contract=result_contract,
    )


def _validate_skill_tree(path: Path) -> None:
    skill_dir = path.parent
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"analysis skill file must be a regular file: {path}")
    unexpected = {item.name for item in skill_dir.iterdir()} - {
        "SKILL.md",
        "references",
    }
    if unexpected:
        raise ValueError(f"unsupported analysis skill resources: {skill_dir}")
    references = skill_dir / "references"
    if references.exists() and (references.is_symlink() or not references.is_dir()):
        raise ValueError(f"invalid analysis skill references directory: {references}")


def _input_kinds(value: str, path: Path) -> tuple[AnalysisInputKind, ...]:
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    try:
        result = tuple(AnalysisInputKind(item) for item in values)
    except ValueError as exc:
        raise ValueError(f"unknown analysis skill input kind: {path}") from exc
    if not result or len(set(result)) != len(result):
        raise ValueError(f"invalid analysis skill input kinds: {path}")
    return result


def _result_contract(value: str, path: Path) -> AnalysisResultContract:
    try:
        return AnalysisResultContract(value)
    except ValueError as exc:
        raise ValueError(f"unknown analysis skill result contract: {path}") from exc


def _validate_contract(
    input_kinds: tuple[AnalysisInputKind, ...],
    contract: AnalysisResultContract,
    path: Path,
) -> None:
    if not all(contract_for(contract).accepts(kind) for kind in input_kinds):
        raise ValueError(f"incompatible analysis skill contract: {path}")


def _order(value: str, path: Path) -> int:
    if not value.isdecimal() or not 0 <= (result := int(value)) <= 999:
        raise ValueError(f"invalid analysis skill order: {path}")
    return result


def _compile_instructions(
    body: str, raw_refs: str | None, raw_modules: str | None, path: Path
) -> str:
    parts: list[str] = []
    modules = (
        ()
        if raw_modules is None
        else tuple(item.strip() for item in raw_modules.split(","))
    )
    if any(not item for item in modules) or len(set(modules)) != len(modules):
        raise ValueError(f"invalid analysis source modules: {path}")
    for module_id in modules:
        parts.append(compile_source_module(module_id, path.parent.parent / "modules"))
    parts.append(bounded(body, path, 64_000))
    references_dir = path.parent / "references"
    requested = (
        () if raw_refs is None else tuple(item.strip() for item in raw_refs.split(","))
    )
    if any(not item for item in requested) or len(set(requested)) != len(requested):
        raise ValueError(f"invalid analysis skill references: {path}")
    allowed_paths: set[Path] = set()
    for raw in requested:
        relative = PurePosixPath(raw)
        if (
            relative.is_absolute()
            or relative.parts[:1] not in {("references",), ("shared",)}
            or len(relative.parts) != 2
        ):
            raise ValueError(f"unsafe analysis skill reference: {path}")
        if _REFERENCE_NAME.fullmatch(relative.name) is None:
            raise ValueError(f"invalid analysis skill reference name: {path}")
        # shared/ holds project-owned references reused by several Skills.
        base = path.parent if relative.parts[0] == "references" else path.parent.parent
        reference = base.joinpath(*relative.parts)
        if (
            reference.parent.is_symlink()
            or reference.is_symlink()
            or not reference.is_file()
        ):
            raise ValueError(f"missing analysis skill reference: {reference}")
        if relative.parts[0] == "references":
            allowed_paths.add(reference)
        reference_text = _read_markdown(reference, maximum=64_000).strip()
        parts.append(f"# Reference: {raw}\n\n{reference_text}")
    existing = set(references_dir.iterdir()) if references_dir.exists() else set()
    if existing != allowed_paths:
        raise ValueError(f"unlisted analysis skill reference: {path}")
    return bounded("\n\n".join(parts), path, 192_000)


def _read_markdown(path: Path, *, maximum: int) -> str:
    if path.stat().st_size > maximum:
        raise ValueError(f"analysis skill file is too large: {path}")
    return path.read_text(encoding="utf-8")
