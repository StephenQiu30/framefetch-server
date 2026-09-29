"""Apply the current-state schema, once, before any service starts.

Run with ``python -m app.workers.migrate`` (the Compose ``migrate`` service).
``sql/schema.sql`` is idempotent; an advisory lock keeps concurrent starts from
racing on the same database.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
from app.core.config import Settings
from sqlalchemy.engine import make_url

SCHEMA = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"
_LOCK_KEY = 0x6672616D65  # "frame"


async def apply_schema(database_url: str, schema: Path = SCHEMA) -> None:
    url = make_url(database_url)
    connection = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port or 5432,
        database=url.database,
        timeout=10,
        command_timeout=300,
    )
    try:
        await connection.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY)
        try:
            await connection.execute(schema.read_text(encoding="utf-8"))
        finally:
            await connection.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
    finally:
        await connection.close()


def main() -> int:
    # A queue-less role: migration needs only the database connection.
    settings = Settings(service_role="provider-sources")
    try:
        asyncio.run(apply_schema(settings.database_url))
    except Exception as exc:
        # Never print the connection string or the failing statement's data.
        print(f"schema migration failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("schema is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
