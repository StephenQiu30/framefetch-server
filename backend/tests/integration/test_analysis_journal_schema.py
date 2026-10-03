"""Current-state SQL preserves paid and unknown calls when reapplied."""

from datetime import UTC, datetime
from pathlib import Path

from app.repositories.analysis.repository import SqlAlchemyAnalysisRepository
from app.services.analysis_execution.models import AnalysisStepStatus
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.integration.test_execution_context_schema import apply_schema
from tests.postgres import isolated_postgres_engine
from tests.unit.repositories.analysis.factories import (
    analysis_command,
    seed_artifact,
)

NOW = datetime(2026, 10, 4, tzinfo=UTC)


async def test_schema_reapplication_preserves_finished_failed_and_unknown_calls():
    sql = (Path(__file__).resolve().parents[2] / "sql/schema.sql").read_text()
    async with isolated_postgres_engine() as postgres_engine:
        await apply_schema(postgres_engine, sql)
        sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
        repository = SqlAlchemyAnalysisRepository(sessions)
        source = await seed_artifact(sessions, NOW)
        command = analysis_command(source)
        await repository.create_job_and_enqueue(command, now=NOW)
        for key in ("draft", "review", "verify"):
            await repository.begin_step(command.run_id, key, "a" * 64, now=NOW)
        await repository.complete_step(
            command.run_id, "draft", {"text": "保留原返回"}, now=NOW
        )
        await repository.fail_step(
            command.run_id, "review", "invalid_model_output", now=NOW
        )
        for _ in range(2):
            await apply_schema(postgres_engine, sql)
        draft = await repository.begin_step(command.run_id, "draft", "a" * 64, now=NOW)
        assert draft.status is AnalysisStepStatus.REPLAY
        assert draft.payload == {"text": "保留原返回"}
        failed = await repository.begin_step(
            command.run_id, "review", "a" * 64, now=NOW
        )
        assert failed.status is AnalysisStepStatus.FAILED
        assert failed.payload == "invalid_model_output"
        unknown = await repository.begin_step(
            command.run_id, "verify", "a" * 64, now=NOW
        )
        assert unknown.status is AnalysisStepStatus.UNKNOWN
