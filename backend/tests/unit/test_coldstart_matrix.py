from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from pydantic import ValidationError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/coldstart_matrix.py"
spec = importlib.util.spec_from_file_location("coldstart_matrix", SCRIPT)
assert spec and spec.loader
matrix = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = matrix
spec.loader.exec_module(matrix)


def case(**overrides):
    evidence = {
        "url": "https://example.com/metadata/1",
        "kind": "platform_api",
        "field": "duration",
        "status": "verified",
        "checked_at": "2026-10-01",
        "note": "independent platform metadata and public clear MP4",
    }
    return matrix.Case.model_validate(
        {
            "id": "test-1",
            "platform": "bilibili",
            "url": "https://example.com/video/1",
            "expected_media_id": "1",
            "kind": "positive",
            "content_scope": "public",
            "duration_seconds": 60,
            "duration_source": evidence,
            "availability_source": evidence,
            "minimum_spec": {"width": 640, "height": 360},
            **overrides,
        }
    )


def plan():
    return {
        "width": 640,
        "height": 360,
        "video_codec_family": "h264",
        "audio_codec_family": "aac",
        "container_preference": "mp4",
    }


def probe(duration=60):
    return {
        "format": {"duration": str(duration), "format_name": "mov,mp4,m4a"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 360},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }


def args():
    return Namespace(
        resolve_timeout=150,
        download_timeout=900,
        decode_timeout=900,
        max_file_bytes=1024,
        duration_tolerance=3,
        cookie_source_label=None,
    )


def test_all_requires_exact_registry_and_two_distinct_works():
    one = case()
    two = case(id="test-2", url="https://example.com/video/2", expected_media_id="2")
    assert matrix.select_cases([one, two], {"bilibili"}, None) == [one, two]
    with pytest.raises(ValueError, match="missing=.*youtube"):
        matrix.select_cases([one, two], {"bilibili", "youtube"}, None)
    with pytest.raises(ValueError, match="extra=.*bilibili"):
        matrix.select_cases([one, two], {"youtube"}, None)
    with pytest.raises(ValueError, match="independent"):
        matrix.select_cases([one, case(id="test-2")], {"bilibili"}, None)
    with pytest.raises(ValueError, match="independent"):
        matrix.select_cases([one], {"bilibili"}, "bilibili")
    with pytest.raises(ValueError, match="unknown"):
        matrix.select_cases([one], {"bilibili"}, "unknown")


def test_stage_ignores_other_platforms_but_never_unknown_platform():
    cases = [
        case(),
        case(id="test-2", url="https://example.com/video/2", expected_media_id="2"),
        case(id="other", platform="youtube"),
    ]
    assert len(matrix.select_cases(cases, {"bilibili", "youtube"}, "bilibili")) == 2


def test_verified_duration_requires_independent_value_and_timestamp():
    with pytest.raises(ValidationError):
        case(duration_seconds=None)
    with pytest.raises(ValidationError):
        case(duration_seconds=float("nan"))
    with pytest.raises(ValidationError):
        case(content_scope="personal_full")
    with pytest.raises(ValidationError):
        case(platform="youku", content_scope="personal_full", needs_identity=False)


@pytest.mark.parametrize("duration", [57, 63, 60])
def test_full_duration_uses_runner_absolute_tolerance(duration):
    assert (
        matrix.verify_probe(probe(duration), case(), plan(), 3)["duration_seconds"]
        == duration
    )


def test_full_duration_uses_runner_relative_tolerance():
    assert matrix.verify_probe(probe(1019), case(duration_seconds=1000), plan(), 3)
    with pytest.raises(matrix.MatrixFailure, match="full_duration_mismatch"):
        matrix.verify_probe(probe(1021), case(duration_seconds=1000), plan(), 3)


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda p: p["streams"][0].update(width=320), "spec_mismatch"),
        (lambda p: p["streams"][0].update(codec_name="vp9"), "codec_mismatch"),
        (lambda p: p["streams"].pop(), "audio_missing"),
        (lambda p: p["format"].update(format_name="matroska"), "container_mismatch"),
        (lambda p: p["format"].update(duration="nan"), "invalid_artifact"),
    ],
)
def test_file_validation_rejects_incomplete_or_wrong_specs(change, reason):
    payload = probe()
    change(payload)
    with pytest.raises(matrix.MatrixFailure, match=reason):
        matrix.verify_probe(payload, case(), plan(), 3)


def test_format_selection_checks_minimum_and_chooses_smallest():
    small = {"id": "small", "plan": {**plan(), "width": 320}}
    large = {"id": "large", "plan": {**plan(), "width": 1280}}
    good = {"id": "good", "plan": plan()}
    assert (
        matrix.choose_format({"formats": [small, large, good]}, case())["id"] == "good"
    )
    with pytest.raises(matrix.MatrixFailure, match="minimum_spec"):
        matrix.choose_format({"formats": [small]}, case())


def test_protected_negative_and_health_never_certify_platform():
    positive = {"sample": case().model_dump(), "result": "passed"}
    negative = {
        "sample": case(id="negative", kind="protected").model_dump(),
        "result": "protected_negative",
    }
    assert matrix.platform_results([positive, negative]) == {"bilibili": "failed"}
    assert matrix.platform_results([]) == {}
    assert (
        matrix.failure_result(case(kind="protected"), "content_protected")
        == "protected_negative"
    )
    assert matrix.failure_result(case(), "content_protected") == "failed"
    assert matrix.failure_result(case(), "login_required") == "blocked"


class FakeApi:
    def __init__(self, *, failure=None, wrong_id=False, context=None):
        self.calls = []
        self.failure = failure
        self.wrong_id = wrong_id
        self.context = context or {
            "provider_key": "bilibili",
            "resolved_layer": "L1",
            "client": "actual",
            "egress_route": "cn_residential",
            "egress_class": "unknown",
            "egress_observed_ip": None,
            "identity_used": False,
        }

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/api/download-intents":
            return {"id": "intent"}
        if path == "/api/inspections/inspection":
            return {
                "id": "inspection",
                "provider_media_id": "wrong" if self.wrong_id else "1",
                "execution_context": self.context,
                "protection_state": "clear",
                "formats": [{"id": "format", "plan": plan()}],
            }
        if path == "/api/downloads":
            return {"id": "job"}
        raise AssertionError(path)

    def poll(self, path, active, timeout):
        self.calls.append(("POLL", path, {}))
        if path.startswith("/api/download-intents"):
            if self.failure:
                return {
                    "status": "failed",
                    "failure": {
                        "failure_class": self.failure,
                        "layer": "L3",
                        "stage": "resolve",
                        "gate": "③",
                        "evidence": {"cause_code": "login"},
                    },
                }
            return {"status": "ready", "inspection_id": "inspection"}
        return {
            "id": "job",
            "status": "succeeded",
            "file_available": True,
            "execution_context": self.context,
        }

    def file(self, job_id, path, max_bytes, timeout=900):
        self.calls.append(("FILE", job_id, {}))
        path.write_bytes(b"video")
        return {"size_bytes": 5, "sha256": "hash", "file": path.name}


def fake_commands(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return json.dumps(probe()) if argv[0] == "ffprobe" else ""

    monkeypatch.setattr(matrix, "run_command", run)
    return calls


def test_complete_formal_chain_and_actual_context(monkeypatch, tmp_path):
    commands = fake_commands(monkeypatch)
    api = FakeApi()
    row = matrix.run_case(api, case(), args(), tmp_path)
    assert row["result"] == "passed"
    assert row["execution_context"] == api.context
    assert row["full_decode_exit_code"] == 0
    assert [p for _, p, _ in api.calls] == [
        "/api/download-intents",
        "/api/download-intents/intent",
        "/api/inspections/inspection",
        "/api/downloads",
        "/api/downloads/job",
        "job",
    ]
    assert [c[0] for c in commands] == ["ffprobe", "ffmpeg"]
    assert "-xerror" in commands[1] and commands[1][-1] == "-"
    assert "-t" not in commands[1]


def test_missing_independent_evidence_blocks_even_complete_delivery(
    monkeypatch, tmp_path
):
    fake_commands(monkeypatch)
    unverified = {
        "url": "https://example.com/metadata",
        "kind": "page",
        "field": "missing",
        "status": "unverified",
        "note": "not obtained",
    }
    row = matrix.run_case(
        FakeApi(),
        case(duration_seconds=None, duration_source=unverified),
        args(),
        tmp_path,
    )
    assert (
        row["result"] == "blocked" and row["failure_class"] == "sample_evidence_missing"
    )
    assert row["full_decode_exit_code"] == 0


def test_id_mismatch_stops_before_download(tmp_path):
    api = FakeApi(wrong_id=True)
    row = matrix.run_case(api, case(), args(), tmp_path)
    assert row["failure_class"] == "work_identity_mismatch"
    assert not any(path == "/api/downloads" for _, path, _ in api.calls)


def test_protected_and_identity_failures_record_structured_evidence(tmp_path):
    row = matrix.run_case(
        FakeApi(failure="content_protected"), case(kind="protected"), args(), tmp_path
    )
    assert row["result"] == "protected_negative" and row["evidence"]["layer"] == "L3"
    row = matrix.run_case(
        FakeApi(failure="identity_unavailable"), case(), args(), tmp_path
    )
    assert row["result"] == "blocked" and row["evidence"]["gate"] == "③"


def test_required_identity_cannot_pass_anonymous_result(tmp_path):
    row = matrix.run_case(FakeApi(), case(needs_identity=True), args(), tmp_path)
    assert row["result"] == "blocked" and row["failure_class"] == "identity_unavailable"


def test_decode_failure_is_not_passed(monkeypatch, tmp_path):
    def run(argv, **kwargs):
        if argv[0] == "ffmpeg":
            raise matrix.MatrixFailure("command_failed", {"exit_code": 1})
        return json.dumps(probe())

    monkeypatch.setattr(matrix, "run_command", run)
    row = matrix.run_case(FakeApi(), case(), args(), tmp_path)
    assert row["result"] == "failed" and "full_decode_exit_code" not in row


def test_api_unwraps_response_and_never_logs_secrets(tmp_path):
    api = matrix.Api("http://example.com")
    api.client.close()
    api.client = httpx.Client(
        base_url="http://example.com",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                401, json={"code": "unauthorized", "message": "secret", "data": None}
            )
        ),
    )
    with pytest.raises(matrix.MatrixFailure) as failure:
        api.request("GET", "/api/auth/me")
    assert "secret" not in str(failure.value) and "secret" not in str(
        failure.value.evidence
    )
    api.client.close()


def test_api_file_checks_published_length_and_sha(tmp_path):
    import hashlib

    api = matrix.Api("http://example.com")
    api.client.close()
    api.client = httpx.Client(
        base_url="http://example.com",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                content=b"video",
                headers={"ETag": hashlib.sha256(b"video").hexdigest()},
            )
        ),
    )
    assert api.file("id", tmp_path / "file", 10)["size_bytes"] == 5
    with pytest.raises(matrix.MatrixFailure, match="file_size_limit"):
        api.file("id", tmp_path / "file", 4)
    api.client.close()


def test_runtime_failure_restores_volumes_and_releases_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(matrix, "LOCK", tmp_path / "lock")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "build" in argv:
            return ""
        if "up" in argv and "compose.coldstart.json" in " ".join(argv):
            raise matrix.MatrixFailure("command_failed")
        return ""

    monkeypatch.setattr(matrix, "run_command", run)
    monkeypatch.setattr(matrix, "compose_project", lambda output: "video-server")
    facts = {}
    with pytest.raises(matrix.MatrixFailure):
        with matrix.runtime(
            Namespace(env_file=Path(".env"), cookie_source_label=None), tmp_path, facts
        ):
            pytest.fail("startup failed")
    assert not matrix.LOCK.exists() and facts["daily_volumes_restored"]
    assert sum("up" in cmd for cmd in calls) == 2
    override = json.loads((tmp_path / "compose.coldstart.json").read_text())
    assert "browser_profiles" not in json.dumps(override)
    assert set(override["services"]) == {"session-runner", "worker"}


def test_reports_json_and_markdown_preserve_evidence(tmp_path):
    row = {
        "sample": case().model_dump(),
        "result": "failed",
        "elapsed_seconds": 1,
        "execution_context": None,
        "failure_class": "challenge",
        "evidence": {"cause_code": "test|gate"},
        "artifact": {"size_bytes": 123, "sha256": "a" * 64},
    }
    matrix.write_report(
        {"results": [row], "platforms": {"bilibili": "failed"}}, tmp_path
    )
    assert (
        json.loads((tmp_path / "matrix.json").read_text())["results"][0]["evidence"]
        == row["evidence"]
    )
    assert "test\\|gate" in (tmp_path / "matrix.md").read_text()
    assert "| 123 | " + "a" * 64 in (tmp_path / "matrix.md").read_text()
    assert "未完成" in (tmp_path / "matrix.md").read_text()


def test_fixture_positive_candidates_have_distinct_identity_and_honest_gaps():
    cases = matrix.load_cases(SCRIPT.parent / "fixtures/coldstart_cases.json")
    registry = {c.platform for c in cases}
    matrix.select_cases(cases, registry, None)
    assert len(registry) == 24
    assert all(
        c.needs_identity
        for c in cases
        if c.platform in {"instagram", "qqvideo", "youku", "wechat_channels"}
    )
    assert all(not c.qualification_gaps() for c in cases if c.platform == "bilibili")
    assert any(c.qualification_gaps() for c in cases if c.platform == "wechat_channels")


@pytest.mark.parametrize(
    "sample_id,duration,source_url,source_kind,source_field",
    [
        (
            "douyin-positive-1",
            11,
            "https://www.douyin.com/video/7674644830270473609",
            "public_page",
            "anonymous page player total MM:SS",
        ),
        (
            "douyin-positive-2",
            20,
            "https://www.douyin.com/video/6961737553342991651",
            "public_page",
            "anonymous page player total MM:SS",
        ),
        (
            "kuaishou-positive-1",
            72.533,
            "https://v.m.chenzhongtech.com/fw/photo/3x888mrikrur4g2",
            "platform_page_or_api",
            "photo.duration / 1000",
        ),
        (
            "kuaishou-positive-2",
            218.783,
            "https://v.m.chenzhongtech.com/fw/photo/3x5jvmsmmiahx3m",
            "platform_page_or_api",
            "photo.duration / 1000",
        ),
        (
            "weibo-positive-1",
            918,
            "https://weibo.com/ajax/statuses/show?id=N4xlMvjhI",
            "platform_page_or_api",
            "page_info.media_info.duration",
        ),
        (
            "weibo-positive-2",
            53,
            "https://weibo.com/ajax/statuses/show?id=FBqgOmDxO",
            "platform_page_or_api",
            "page_info.media_info.duration",
        ),
        (
            "xiaohongshu-positive-1",
            69,
            "https://www.xiaohongshu.com/explore/6a6ff0eb000000002701d892",
            "platform_page_or_api",
            "note.video.capa.duration",
        ),
    ],
)
def test_g2_fixture_retains_dated_independent_platform_evidence(
    sample_id, duration, source_url, source_kind, source_field
):
    samples = matrix.load_cases(SCRIPT.parent / "fixtures/coldstart_cases.json")
    sample = next(c for c in samples if c.id == sample_id)
    assert sample.duration_seconds == duration
    assert sample.duration_source.kind == source_kind
    assert sample.duration_source.field == source_field
    expected = urlsplit(source_url)
    for source in (sample.duration_source, sample.availability_source):
        actual = urlsplit(source.url)
        assert (actual.scheme, actual.netloc, actual.path) == (
            expected.scheme,
            expected.netloc,
            expected.path,
        )
        if expected.query:
            assert actual.query == expected.query
        assert source.status == "verified"
        assert (
            datetime.fromisoformat(source.checked_at).date().isoformat() == "2026-10-01"
        )
    assert sample.qualification_gaps() == []


def test_g2_missing_xiaohongshu_evidence_blocks_complete_delivery(
    monkeypatch, tmp_path
):
    samples = matrix.load_cases(SCRIPT.parent / "fixtures/coldstart_cases.json")
    sample = next(c for c in samples if c.id == "xiaohongshu-positive-2")
    assert sample.duration_seconds is None
    for source in (sample.duration_source, sample.availability_source):
        assert source.status == "unverified"
        assert source.checked_at is None
        assert "待补充" in source.note
    assert sample.qualification_gaps() == [
        "public/free/non-DRM availability not independently verified",
        "independent full duration missing",
    ]
    fake_commands(monkeypatch)
    api = FakeApi(context={"provider_key": sample.platform, "identity_used": True})
    original = api.request

    def request(method, path, **kwargs):
        payload = original(method, path, **kwargs)
        if path == "/api/inspections/inspection":
            payload["provider_media_id"] = sample.expected_media_id
        return payload

    api.request = request
    options = args()
    options.cookie_source_label = "test-cookie-source"
    row = matrix.run_case(api, sample, options, tmp_path)
    assert row["full_decode_exit_code"] == 0
    assert row["result"] == "blocked"
    assert row["failure_class"] == "sample_evidence_missing"
    assert row["qualification_gaps"] == sample.qualification_gaps()
    matrix.write_report({"results": [row]}, tmp_path)
    report = json.loads((tmp_path / "matrix.json").read_text())
    assert report["results"][0]["sample"]["duration_source"]["status"] == "unverified"
    markdown = (tmp_path / "matrix.md").read_text()
    assert "| blocked |" in markdown
    assert "independent full duration missing" in markdown


def test_youtube_fixture_pair_has_complete_independent_qualification():
    cases = matrix.load_cases(SCRIPT.parent / "fixtures/coldstart_cases.json")
    positives = [c for c in cases if c.platform == "youtube" and c.kind == "positive"]
    assert len(positives) == 2
    assert len({c.expected_media_id for c in positives}) == 2
    assert {c.duration_seconds for c in positives} == {19, 635}
    assert all(c.needs_identity and c.content_scope == "public" for c in positives)
    assert all(not c.qualification_gaps() for c in positives)
    assert all(
        c.availability_source.kind == "official_player_metadata"
        and c.availability_source.checked_at
        for c in positives
    )


def test_frame_rate_and_dynamic_range_are_checked_against_confirmed_plan():
    payload = probe()
    payload["streams"][0].update(avg_frame_rate="30000/1001", color_transfer="bt709")
    assert matrix.verify_probe(
        payload, case(), {**plan(), "fps_bucket": "fps_30", "dynamic_range": "sdr"}, 3
    )
    with pytest.raises(matrix.MatrixFailure, match="frame_rate_mismatch"):
        matrix.verify_probe(payload, case(), {**plan(), "fps_bucket": "fps_60"}, 3)
    with pytest.raises(matrix.MatrixFailure, match="dynamic_range_mismatch"):
        matrix.verify_probe(payload, case(), {**plan(), "dynamic_range": "hdr"}, 3)


def test_decode_interruption_terminates_entire_process_group(monkeypatch, tmp_path):
    import signal
    import subprocess

    class Process:
        pid = 123

        def __init__(self):
            self.calls = 0

        def wait(self, timeout=None):
            self.calls += 1
            if self.calls <= 2:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            return -9

    process = Process()
    monkeypatch.setattr(matrix.subprocess, "Popen", lambda *a, **kw: process)
    killed = []
    monkeypatch.setattr(matrix.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        matrix.run_command(["ffmpeg"], timeout=1, log=tmp_path / "decode.log")
    assert killed == [(123, signal.SIGTERM), (123, signal.SIGKILL)]


def test_poll_timeout_requests_cancellation(monkeypatch):
    api = matrix.Api("http://example.com")
    calls = []

    def request(method, path, **kw):
        calls.append((method, path))
        return {"status": "queued"}

    monkeypatch.setattr(api, "request", request)
    with pytest.raises(matrix.MatrixFailure, match="matrix_timeout"):
        api.poll("/api/download-intents/id", {"queued"}, 0)
    assert calls[-1] == ("POST", "/api/download-intents/id/cancel")
    api.client.close()


def test_download_context_change_is_rejected_before_fetch(monkeypatch, tmp_path):
    api = FakeApi()
    original = api.poll

    def poll(path, *params):
        result = original(path, *params)
        if path.startswith("/api/downloads/"):
            result["execution_context"] = {**api.context, "client": "changed"}
        return result

    monkeypatch.setattr(api, "poll", poll)
    row = matrix.run_case(api, case(), args(), tmp_path)
    assert row["failure_class"] == "context_changed"
    assert not any(method == "FILE" for method, _, _ in api.calls)


def test_warm_cookie_source_cannot_certify_identity_coldstart(monkeypatch, tmp_path):
    fake_commands(monkeypatch)
    api = FakeApi(context={"provider_key": "bilibili", "identity_used": True})
    row = matrix.run_case(api, case(needs_identity=True), args(), tmp_path)
    assert (
        row["result"] == "blocked"
        and "cookie-source was not cold-started" in row["qualification_gaps"]
    )


def test_worktree_reuses_single_existing_compose_project(monkeypatch, tmp_path):
    monkeypatch.setattr(
        matrix,
        "run_command",
        lambda *a, **kw: "video-server\nvideo-server\nvideo-server\n",
    )
    assert matrix.compose_project(tmp_path) == "video-server"
    monkeypatch.setattr(
        matrix, "run_command", lambda *a, **kw: "video-server\nother\nvideo-server\n"
    )
    with pytest.raises(matrix.MatrixFailure, match="shared_compose_project_not_found"):
        matrix.compose_project(tmp_path)


def test_file_retrieval_has_a_total_time_bound(tmp_path):
    import hashlib

    api = matrix.Api("http://example.com")
    api.client.close()
    api.client = httpx.Client(
        base_url="http://example.com",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                content=b"video",
                headers={"ETag": hashlib.sha256(b"video").hexdigest()},
            )
        ),
    )
    with pytest.raises(matrix.MatrixFailure, match="file_timeout"):
        api.file("id", tmp_path / "file", 10, timeout=0)
    api.client.close()


def test_datacenter_does_not_disqualify_complete_youtube_delivery(
    monkeypatch, tmp_path
):
    fake_commands(monkeypatch)
    api = FakeApi(
        context={
            "provider_key": "youtube",
            "identity_used": True,
            "egress_class": "datacenter",
        }
    )
    row = matrix.run_case(api, case(platform="youtube"), args(), tmp_path)
    assert row["result"] == "passed"
    assert row["execution_context"]["egress_class"] == "datacenter"


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "ffprobe"},
        {"kind": "yt_dlp"},
        {"kind": "platform_player_ui"},
        {"kind": "official_anonymous_api"},
        {"kind": "official_anonymous_embed_metadata"},
        {"kind": "official_anonymous_watch_metadata"},
        {"kind": "official_page_metadata"},
        {"kind": "official_public_blog_metadata"},
        {"url": "file:///tmp/probe"},
        {"checked_at": "yesterday"},
        {"checked_at": None},
        {"checked_at": "2026-10-01T09:21:54"},
        {"field": ""},
        {"note": ""},
    ],
)
@pytest.mark.parametrize("source_field", ["duration_source", "availability_source"])
def test_verified_evidence_requires_real_independent_source(change, source_field):
    original = getattr(case(), source_field).model_dump()
    with pytest.raises(ValidationError):
        case(**{source_field: {**original, **change}})


def test_failed_intent_reports_actual_attempt_without_success_context(tmp_path):
    api = FakeApi(failure="content_protected")
    original = api.poll
    facts = {
        "layer": "L3",
        "client": "test:browser",
        "egress_route": "global_residential",
        "egress_class": "datacenter",
        "egress_observed_ip": "192.0.2.1",
        "identity_used": True,
    }

    def poll(*args):
        payload = original(*args)
        payload["failure"]["evidence"].update(facts)
        return payload

    api.poll = poll
    row = matrix.run_case(api, case(), args(), tmp_path)
    assert row["execution_context"] is None
    assert all(row["failure_attempt"][key] == value for key, value in facts.items())
    matrix.write_report({"results": [row]}, tmp_path)
    report = (tmp_path / "matrix.md").read_text()
    assert "L3 / test:browser" in report and "datacenter / 192.0.2.1" in report


@pytest.mark.parametrize("rate", [None, "0/0", "0/1", "garbage", "NaN"])
def test_malformed_or_missing_rate_is_a_contract_failure(rate):
    payload = probe()
    payload["streams"][0]["avg_frame_rate"] = rate
    with pytest.raises(matrix.MatrixFailure, match="frame_rate_missing"):
        matrix.verify_probe(payload, case(), {**plan(), "fps_bucket": "fps_30"}, 3)


@pytest.mark.parametrize(
    "identity_used,expected", [(True, "passed"), (False, "blocked")]
)
def test_youtube_datacenter_requires_identity_and_complete_file(
    monkeypatch, tmp_path, identity_used, expected
):
    fake_commands(monkeypatch)
    context = {
        **FakeApi().context,
        "provider_key": "youtube",
        "resolved_layer": "L2",
        "client": "youtube:mweb",
        "egress_class": "datacenter",
        "identity_used": identity_used,
    }
    options = args()
    options.reuse_cookie_source = True
    row = matrix.run_case(
        FakeApi(context=context),
        case(platform="youtube", needs_identity=identity_used),
        options,
        tmp_path,
    )
    assert row["result"] == expected
    assert row["full_decode_exit_code"] == 0
    assert row["execution_context"]["egress_class"] == "datacenter"


def test_shared_identity_service_still_requires_actual_injection(monkeypatch, tmp_path):
    fake_commands(monkeypatch)
    options = args()
    options.reuse_cookie_source = True
    row = matrix.run_case(
        FakeApi(context={**FakeApi().context, "provider_key": "youtube"}),
        case(platform="youtube", needs_identity=True),
        options,
        tmp_path,
    )
    assert row["result"] == "blocked"
    assert row["failure_class"] == "identity_unavailable"


# Recorded G1/G3 file metadata (2026-10-01), kept as deterministic regressions.
# These facts do not rerun a platform or imply current cold-start acceptance.
@pytest.mark.parametrize(
    "sample_id,duration,width,height,codec,rate",
    [
        ("youtube-positive-1", 18.947483, 320, 240, "h264", "15/1"),
        ("youtube-positive-2", 634.578141, 640, 360, "h264", "30/1"),
        ("twitch-positive-1", 32.099, 1920, 1080, "h264", "960000/32099"),
        ("twitch-positive-2", 60.066341, 360, 640, "h264", "13839360/461317"),
        ("x-positive-1", 3.178667, 320, 180, "h264", "24000/1001"),
        ("x-positive-2", 21.333333, 480, 270, "h264", "30000/1001"),
        ("instagram-positive-1", 11.887007, 640, 640, "h264", "2997/100"),
        ("instagram-positive-2", 19.133243, 480, 854, "h264", "30/1"),
        ("facebook-positive-1", 131.030204, 400, 300, "h264", "30/1"),
        ("facebook-positive-2", 44.33, 400, 400, "h264", "119070000/3972973"),
        ("tiktok-positive-1", 18.666667, 540, 960, "hevc", "30/1"),
        ("tiktok-positive-2", 27.466667, 540, 960, "h264", "30/1"),
        ("tumblr-positive-1", 7.620998, 1280, 720, "h264", "24000/1001"),
        ("tumblr-positive-2", 127.175714, 1280, 720, "h264", "30/1"),
    ],
)
def test_merged_g1_g3_samples_pass_strict_recorded_file_checks(
    sample_id, duration, width, height, codec, rate
):
    samples = matrix.load_cases(SCRIPT.parent / "fixtures/coldstart_cases.json")
    sample = next(c for c in samples if c.id == sample_id)
    assert sample.qualification_gaps() == []
    for source in (sample.duration_source, sample.availability_source):
        assert source.status == "verified"
        assert (
            datetime.fromisoformat(source.checked_at).date().isoformat() == "2026-10-01"
        )
        assert source.field and source.note
    actual = probe(duration)
    actual["streams"][0].update(
        width=width, height=height, codec_name=codec, avg_frame_rate=rate
    )
    confirmed = {
        **plan(),
        "width": width,
        "height": height,
        "video_codec_family": codec,
        "fps_bucket": "fps_30",
        "dynamic_range": "sdr",
    }
    assert (
        matrix.verify_probe(actual, sample, confirmed, 3)["duration_seconds"]
        == duration
    )
    with pytest.raises(matrix.MatrixFailure, match="frame_rate_mismatch"):
        matrix.verify_probe(actual, sample, {**confirmed, "fps_bucket": "fps_60"}, 3)


@pytest.mark.parametrize("platform", ["reddit"])
def test_g3_unverified_public_or_duration_evidence_still_blocks(platform):
    samples = matrix.load_cases(SCRIPT.parent / "fixtures/coldstart_cases.json")
    positives = [c for c in samples if c.platform == platform and c.kind == "positive"]
    assert len(positives) == 2
    assert all(c.qualification_gaps() for c in positives)
    assert all(c.availability_source.status == "unverified" for c in positives)


def test_vimeo_replacements_have_independent_dated_public_clear_evidence():
    samples = matrix.load_cases(SCRIPT.parent / "fixtures/coldstart_cases.json")
    positives = [c for c in samples if c.platform == "vimeo" and c.kind == "positive"]
    assert {(c.expected_media_id, c.duration_seconds) for c in positives} == {
        ("1214828906", 88),
        ("22439234", 185),
    }
    for sample in positives:
        assert sample.content_scope == "public" and not sample.needs_identity
        assert sample.qualification_gaps() == []
        assert sample.duration_source.url == (
            f"https://vimeo.com/api/v2/video/{sample.expected_media_id}.json"
        )
        assert sample.availability_source.kind == "official_player_metadata"
        assert sample.availability_source.checked_at
    negative = next(c for c in samples if c.id == "vimeo-protected-1")
    assert negative.expected_media_id == "68375962"
    assert negative.availability_source.status == "verified"


@pytest.mark.parametrize(
    "failure,gate,expected",
    [
        ("content_unavailable", "none", "protected_negative"),
        ("content_unavailable", "③", "failed"),
        ("content_unavailable", None, "failed"),
        ("content_protected", "none", "failed"),
        ("extractor_broken", "none", "failed"),
        ("login_required", "③", "blocked"),
    ],
)
def test_private_negative_requires_exact_failure_class_and_gate(
    tmp_path, failure, gate, expected
):
    api = FakeApi(failure=failure)
    original = api.poll

    def poll(*args):
        result = original(*args)
        result["failure"]["gate"] = gate
        return result

    api.poll = poll
    sample = case(
        kind="protected",
        expected_failure_class="content_unavailable",
        expected_gate="none",
    )
    row = matrix.run_case(api, sample, args(), tmp_path)
    assert row["result"] == expected
    assert not any(method == "FILE" for method, _, _ in api.calls)
    assert (
        matrix.failure_result(case(kind="protected"), "content_unavailable") == "failed"
    )
