from __future__ import annotations

from pathlib import Path

import yaml
from yaml.constructor import ConstructorError


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader, node: yaml.nodes.MappingNode
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=False)
        if key in result:
            raise ConstructorError(
                "mapping", node.start_mark, "duplicate key", key_node.start_mark
            )
        result[key] = loader.construct_object(value_node, deep=False)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def load_frontmatter(raw: str, path: Path) -> dict[str, object]:
    try:
        loaded: object = yaml.load(raw, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid analysis skill YAML: {path}") from exc
    if not isinstance(loaded, dict) or any(not isinstance(key, str) for key in loaded):
        raise ValueError(f"analysis skill frontmatter must be a mapping: {path}")
    return {key: value for key, value in loaded.items() if isinstance(key, str)}


def string_mapping(value: object, path: Path) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"analysis skill metadata must be a mapping: {path}")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"analysis skill metadata values must be strings: {path}")
        result[key] = item
    return result


def required_string(value: object, field: str, path: Path, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"analysis skill {field} must be a string: {path}")
    return bounded(value, path, maximum)


def bounded(value: str, path: Path, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"invalid analysis skill text: {path}")
    return normalized
