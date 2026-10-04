"""Safe creation errors independent of HTTP and persistence adapters."""

from app.core.errors import AppError


def creation_error(status: int, code: str, detail: str) -> AppError:
    return AppError(status, code, "Content creation request failed", detail)
