from pathlib import Path

import pytest
from app.core import runtime as runtime_module
from app.core.config import Settings
from app.integrations.realtime import RabbitMqRealtimeConsumer
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def disable_external_realtime(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_op(_consumer: RabbitMqRealtimeConsumer) -> None:
        return None

    monkeypatch.setattr(RabbitMqRealtimeConsumer, "start", no_op)
    monkeypatch.setattr(RabbitMqRealtimeConsumer, "close", no_op)

    async def schema_available(_engine: object) -> None:
        return None

    monkeypatch.setattr(
        runtime_module, "assert_download_execution_schema", schema_available
    )


def test_non_test_app_wires_download_use_cases(tmp_path: Path) -> None:
    settings = Settings(
        app_env="development",
        session_runner_base_url="http://session-runner.test",
        redis_url="redis://127.0.0.1:6379/0",
        _env_file=None,
    )
    application = create_app(settings)

    with TestClient(application) as client:
        assert application.state.services.download_use_cases is not None
        assert application.state.services.analysis_use_cases is not None
        assert application.state.services.auth_service is not None
        assert client.get("/health/live").status_code == 200


def test_non_test_app_wires_runtime_readiness_into_the_route(tmp_path: Path) -> None:
    settings = Settings(
        app_env="development",
        session_runner_base_url="http://session-runner.test",
        redis_url="redis://127.0.0.1:6379/0",
        _env_file=None,
    )
    application = create_app(settings)

    async def unavailable() -> bool:
        return False

    with TestClient(application) as client:
        application.state.services.readiness_probe.check = unavailable
        response = client.get("/health/ready")

    assert response.status_code == 503


def test_test_app_leaves_download_use_cases_injectable(tmp_path: Path) -> None:
    application = create_app(Settings(app_env="test"))

    with TestClient(application) as client:
        response = client.post(
            "/api/inspections",
            headers={"Idempotency-Key": "inspect-1"},
            json={
                "source": {
                    "kind": "public_url",
                    "url": "https://media.example/video",
                }
            },
        )

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
