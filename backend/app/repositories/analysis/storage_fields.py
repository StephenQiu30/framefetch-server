from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, cast

from pydantic import BaseModel


def dataclass_document(value: object) -> dict[str, Any]:
    result = _document_value(value)
    if not isinstance(result, dict):
        raise TypeError("analysis result must serialize to an object")
    return result


def _document_value(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _document_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_document_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def mapping(value: object, expected: set[str] | None, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"stored {label} must be an object")
    result = cast(dict[str, Any], value)
    if expected is not None and set(result) != expected:
        raise ValueError(f"stored {label} has an invalid shape")
    return result


def array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"stored {label} must be an array")
    return cast(list[object], value)


def strings(value: object, label: str) -> tuple[str, ...]:
    return tuple(string(item, label) for item in array(value, label))


def string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"stored {label} must be a string")
    return value


def integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"stored {label} must be an integer")
    return value
