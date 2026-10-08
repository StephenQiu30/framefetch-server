from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.services.analysis.rules.enums import AnalysisValidationCode
from app.services.analysis.rules.errors import AnalysisValidationError
from app.services.analysis.rules.result_items import _strings
from app.services.analysis.rules.text import identifier, required_text

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ScreenplayGlossaryTerm:
    source: str
    target: str
    category: str

    def __post_init__(self) -> None:
        for field_name in ("source", "target", "category"):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), f"glossary {field_name}"),
            )


@dataclass(frozen=True, slots=True)
class ScreenplayRewriteGlossary:
    source_language: str
    target_language: str
    terms: tuple[ScreenplayGlossaryTerm, ...]
    style_rules: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "style_rules",
            _strings(self.style_rules, "screenplay glossary style rule"),
        )
        if (
            self.source_language not in {"zh-CN", "en-US", "mixed", "unknown"}
            or self.target_language not in {"zh-CN", "en-US"}
            or not self.style_rules
            or len(self.terms) > 512
            or len(self.style_rules) > 64
        ):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "screenplay rewrite glossary is invalid",
            )
        sources = [term.source.casefold() for term in self.terms]
        if len(set(sources)) != len(sources):
            raise AnalysisValidationError(
                AnalysisValidationCode.DUPLICATE_IDENTIFIER,
                "screenplay glossary source terms must be unique",
            )


@dataclass(frozen=True, slots=True)
class ScreenplayRewriteChunk:
    source_scene_id: str
    part_no: int
    source_sha256: str
    rewritten_text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_scene_id",
            identifier(self.source_scene_id, "rewrite source scene id"),
        )
        if (
            isinstance(self.part_no, bool)
            or not isinstance(self.part_no, int)
            or self.part_no <= 0
        ):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "rewrite part_no must be a positive integer",
            )
        if not _SHA256.fullmatch(self.source_sha256):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_SCHEMA,
                "rewrite source SHA-256 is invalid",
            )
        if (
            not isinstance(self.rewritten_text, str)
            or not self.rewritten_text.strip()
            or len(self.rewritten_text) > 200_000
            or "\r" in self.rewritten_text
            or "\x00" in self.rewritten_text
            or unicodedata.normalize("NFC", self.rewritten_text) != self.rewritten_text
        ):
            raise AnalysisValidationError(
                AnalysisValidationCode.INVALID_TEXT,
                "rewritten text is invalid",
            )
