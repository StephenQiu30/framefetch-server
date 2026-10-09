"""Read standalone Compose definitions without a Docker daemon."""

from pathlib import Path
from typing import Any

import yaml


def load_compose(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
