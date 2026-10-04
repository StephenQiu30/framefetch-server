"""Preserve ordinary document text without inventing screenplay scenes."""

from dataclasses import dataclass

from app.services.documents.rules.screenplay import ScreenplayScene


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    text: str
    detected_language: str
    scenes: tuple[ScreenplayScene, ...] = ()
    quality_warnings: tuple[str, ...] = ()

    @property
    def character_count(self) -> int:
        return len(self.text)


def normalize_document(text: str) -> NormalizedDocument:
    # These are text decoding/newline operations only. Code indentation, Markdown
    # hard breaks, quotes and authored Unicode remain exactly as extracted.
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ValueError("document text is empty")
    chinese = sum("\u3400" <= character <= "\u9fff" for character in normalized)
    english = sum(
        character.isascii() and character.isalpha() for character in normalized
    )
    letters = chinese + english
    language = (
        "unknown"
        if letters < 20
        else "mixed"
        if min(chinese, english) / letters >= 0.2
        else "zh-CN"
        if chinese > english
        else "en-US"
    )
    return NormalizedDocument(normalized, language)
