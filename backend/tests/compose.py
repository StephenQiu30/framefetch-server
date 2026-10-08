"""Read the repository's shared Compose services without a Docker daemon."""

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def load_compose(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for name, service in document["services"].items():
        inheritance = service.pop("extends", None)
        if inheritance is None:
            continue
        shared = yaml.safe_load(
            (path.parent / inheritance["file"]).read_text(encoding="utf-8")
        )["services"][inheritance["service"]]
        assert "extends" not in shared, "Only one shared service layer is supported"
        document["services"][name] = _merge(shared, service)
    return document


def _merge(shared: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(shared)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            # Current mode files override scalars, mappings and the health command.
            # Reject list merges so these tests cannot silently diverge from Compose.
            assert key == "test" or not (
                isinstance(value, list) and isinstance(result.get(key), list)
            ), f"Unsupported Compose sequence merge: {key}"
            result[key] = value
    return result
