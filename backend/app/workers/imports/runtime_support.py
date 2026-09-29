from __future__ import annotations

import hashlib
import os
import socket
from datetime import UTC, datetime


def worker_id() -> str:
    hostname = socket.gethostname()
    digest = hashlib.sha256(hostname.encode()).hexdigest()[:12]
    return f"import-{hostname[:64]}-{digest}-{os.getpid()}"


def utc_now() -> datetime:
    return datetime.now(UTC)
