"""Shared platform flag for opening Runner files without following symlinks."""

from __future__ import annotations

import os


def no_follow_flag() -> int:
    """Return the platform flag that prevents opening a symlink."""
    return getattr(os, "O_NOFOLLOW", 0)
