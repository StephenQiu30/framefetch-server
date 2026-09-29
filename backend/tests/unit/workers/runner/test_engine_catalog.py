import asyncio

import pytest
from api_helpers import FakeService, settings, signed_headers
from app.workers.runner.engine_catalog import RunnerEngineCatalog
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.main import create_app
from app.workers.runner.process import ProcessResult, ProcessSupervisor
from app.workers.runner.version import YTDLP_ENGINE_COMMIT
from fastapi.testclient import TestClient


async def test_catalog_enumerates_real_plugins_once_for_concurrent_readers(tmp_path):
    loader = RunnerEngineCatalog(settings(tmp_path))
    results = await asyncio.gather(*(loader.get() for _ in range(10)))
    snapshot = results[0]
    assert all(result is snapshot for result in results)
    candidates = {item.key: item for item in snapshot.candidates}
    assert len(candidates) == len(snapshot.candidates)
    assert len(candidates) > 1000  # Do not freeze a marketing platform count.
    assert "WechatChannelsPublic" in candidates
    assert "HongguoOfficialShare" in candidates
    assert candidates["Douyin"].name == "Douyin+share_page"
    assert snapshot.engine_commit == YTDLP_ENGINE_COMMIT
    assert snapshot.pin_matches
    assert (
        not {"download_available", "cookie", "egress"}
        & type(snapshot).model_fields.keys()
    )
    assert (await RunnerEngineCatalog(settings(tmp_path)).get()) == snapshot


async def test_mismatched_pin_never_claims_the_configured_commit_as_installed(tmp_path):
    original = await RunnerEngineCatalog(settings(tmp_path)).get()
    changed = settings(tmp_path).model_copy(update={"runner_ytdlp_commit": "a" * 40})
    observed = await RunnerEngineCatalog(changed).get()
    assert observed.engine_commit == original.engine_commit
    assert observed.expected_engine_commit == "a" * 40
    assert not observed.pin_matches
    assert observed.manifest_id != original.manifest_id


async def test_changed_pot_setting_does_not_match_release_pin(tmp_path):
    changed = settings(tmp_path).model_copy(
        update={"runner_youtube_pot_provider_version": "bgutil-http-9.9.9"}
    )
    snapshot = await RunnerEngineCatalog(changed).get()
    assert not snapshot.pin_matches


async def test_catalog_refuses_a_different_configured_binary(tmp_path):
    configured = settings(tmp_path).model_copy(update={"runner_ytdlp_bin": "python"})
    with pytest.raises(RunnerFailure, match="engine catalog unavailable"):
        await RunnerEngineCatalog(configured).get()


@pytest.mark.parametrize("failure", ["truncated", "invalid", "exit", "timeout"])
async def test_catalog_failure_is_bounded_redacted_and_not_cached(
    tmp_path, monkeypatch, failure
):
    calls = []

    async def run(_self, argv, **options):
        calls.append(options)
        assert options["timeout_seconds"] == 8
        assert "TOP_SECRET" not in options["env"]
        if failure == "timeout":
            raise TimeoutError("private internal output")
        return ProcessResult(
            1 if failure == "exit" else 0,
            b"private internal output",
            b"secret",
            failure == "truncated",
            False,
        )

    monkeypatch.setenv("TOP_SECRET", "must-not-be-inherited")
    monkeypatch.setattr(ProcessSupervisor, "run", run)
    loader = RunnerEngineCatalog(settings(tmp_path))
    for _ in range(2):
        with pytest.raises(RunnerFailure) as error:
            await loader.get()
        assert error.value.code == "engine_catalog_unavailable"
        assert "private" not in str(error.value)
    assert len(calls) == 2


def test_catalog_requires_signature_and_rejects_replay(tmp_path, monkeypatch):
    calls = []

    async def unavailable(_self):
        calls.append(True)
        raise RunnerFailure("engine_catalog_unavailable", status=503)

    monkeypatch.setattr(RunnerEngineCatalog, "get", unavailable)
    client = TestClient(create_app(settings(tmp_path), service=FakeService()))
    path = "/internal/engine-catalog"
    assert client.get(path).status_code == 401
    assert not calls
    headers = signed_headers(path, b"", "engine_catalog_nonce", method="GET")
    assert client.get(path, headers=headers).status_code == 503
    assert client.get(path, headers=headers).status_code == 401
    assert len(calls) == 1
