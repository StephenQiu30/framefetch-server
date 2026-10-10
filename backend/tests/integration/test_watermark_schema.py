from pathlib import Path

from sqlalchemy import text
from tests.integration.test_execution_context_schema import apply_schema
from tests.postgres import isolated_postgres_engine


async def test_watermark_schema_is_idempotent_and_preserves_existing_rows():
    sql = Path("sql/schema.sql").read_text()
    async with isolated_postgres_engine() as engine:
        await apply_schema(engine, sql)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO watermark_workers (id, heartbeat_at, engine) "
                    "VALUES ('test-worker', now(), 'test')"
                )
            )
        await apply_schema(engine, sql)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT count(*) FROM watermark_workers"))
                == 1
            )
