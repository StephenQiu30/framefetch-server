"""Fully prepared and hashable content requests across provider adapters."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContentModelRequest:
    workspace: Path
    prompt: str = field(repr=False)
    schema_json: str = field(repr=False)
    provider_binding_sha256: str
    stage: str
    image_paths: tuple[Path, ...] = ()
