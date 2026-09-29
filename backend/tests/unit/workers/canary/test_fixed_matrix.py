import json
from types import SimpleNamespace

from app.services.provider_types import ProviderCanaryOutcome
from app.workers.canary import fixed_matrix


async def test_unknown_provider_cannot_be_silently_omitted(monkeypatch, capsys):
    def unexpected(*args):
        raise AssertionError("invalid selection must not open runtime")

    monkeypatch.setattr(fixed_matrix, "build_runtime", unexpected)
    assert (
        await fixed_matrix._run(frozenset({"youtube", "misspelled"}), "metadata") == 2
    )
    report = json.loads(capsys.readouterr().out)
    assert report["matrix_complete"] is False
    assert report["target_count"] == 0
    assert report["error"] == "unknown_provider"


async def test_selected_targets_execute_once_close_and_report_without_url(
    monkeypatch, capsys
):
    calls, closed = [], []

    class Service:
        async def execute(self, target):
            calls.append((target.provider_key, target.stage.value))
            return SimpleNamespace(
                provider_key=target.provider_key,
                profile_version="test",
                stage=target.stage,
                access_mode=target.access_mode,
                outcome=ProviderCanaryOutcome.SUCCEEDED,
                stable_error_code=None,
                duration_ms=1,
            )

    class Runtime:
        service = Service()

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(fixed_matrix, "build_runtime", lambda _: Runtime())
    monkeypatch.setattr(fixed_matrix, "get_settings_for_role", lambda _: None)
    assert await fixed_matrix._run(frozenset({"youtube"}), "metadata") == 0
    output = capsys.readouterr().out
    assert "https://" not in output and "url" not in output
    assert json.loads(output)["target_count"] == 1
    assert calls == [("youtube", "metadata")]
    assert closed == [True]


def test_native_public_cli_never_selects_account_platforms(monkeypatch):
    import sys

    import pytest
    from app.services.provider_access import NATIVE_PUBLIC_PROVIDERS

    calls = []

    async def run(providers, stage):
        calls.append((providers, stage))
        return 0

    monkeypatch.setattr(fixed_matrix, "_run", run)
    monkeypatch.setattr(
        sys, "argv", ["fixed_matrix", "--native-public", "--stage", "metadata"]
    )
    with pytest.raises(SystemExit) as caught:
        fixed_matrix.main()
    assert caught.value.code == 0
    assert calls == [(NATIVE_PUBLIC_PROVIDERS, "metadata")]


def test_native_public_cli_rejects_account_override(monkeypatch):
    import sys

    import pytest

    monkeypatch.setattr(
        sys, "argv", ["fixed_matrix", "--native-public", "--provider", "youtube"]
    )
    with pytest.raises(SystemExit) as caught:
        fixed_matrix.main()
    assert caught.value.code == 2
