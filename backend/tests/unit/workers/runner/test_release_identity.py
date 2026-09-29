from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from app.services.provider_types import ProviderAccessMode
from app.workers.runner.errors import RunnerFailure
from app.workers.runner.release_identity import (
    require_youtube_sidecar_identity,
    runtime_code_sha256,
)


def test_runtime_revision_changes_with_plugin_and_policy(tmp_path: Path) -> None:
    runner = tmp_path / "workers" / "runner"
    plugin = runner / "plugins" / "yt_dlp_plugins" / "extractor" / "douyin_share.py"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("version = 1\n")
    main = runner / "main.py"
    main.write_text("protocol = 1\n")
    contracts = runner / "contracts.py"
    contracts.write_text("accept_media = True\n")
    pot_supervisor = runner / "youtube-pot-supervisor.mjs"
    pot_supervisor.write_text("const version = 1;\n")
    personal_video = plugin.parent / "personal_video.py"
    personal_video.write_text("version = 1\n")
    wechat_policy = runner / "wechat_channels_policy.py"
    wechat_policy.write_text("policy = 1\n")
    # Host-only session import code is never packaged into a media Runner.
    chrome_source = tmp_path / "workers" / "session" / "chrome_source.py"
    chrome_source.parent.mkdir(parents=True)
    chrome_source.write_text("extract = 1\n")
    yuanbao_session = runner / "provider_session_headers.py"
    yuanbao_session.write_text("session = 1\n")
    services = tmp_path / "services"
    services.mkdir()
    policy = services / "provider_access.py"
    policy.write_text("route = 'public'\n")
    (services / "providers.py").write_text("status = 'probe'\n")
    downloads = services / "downloads"
    downloads.mkdir()
    (downloads / "inspection_models.py").write_text("identity = 1\n")
    (downloads / "plans.py").write_text("plan = 1\n")

    original = runtime_code_sha256("douyin", tmp_path)
    other_provider = runtime_code_sha256("tiktok", tmp_path)
    plugin.write_text("version = 2\n")
    runtime_code_sha256.cache_clear()
    changed_plugin = runtime_code_sha256("douyin", tmp_path)
    assert runtime_code_sha256("tiktok", tmp_path) == other_provider
    youku_before = runtime_code_sha256("youku", tmp_path)
    qqvideo_before = runtime_code_sha256("qqvideo", tmp_path)
    personal_video.write_text("version = 2\n")
    runtime_code_sha256.cache_clear()
    assert runtime_code_sha256("douyin", tmp_path) == changed_plugin
    assert runtime_code_sha256("youku", tmp_path) != youku_before
    assert runtime_code_sha256("qqvideo", tmp_path) != qqvideo_before
    pot_before = runtime_code_sha256("youtube", tmp_path)
    douyin_before_pot = runtime_code_sha256("douyin", tmp_path)
    pot_supervisor.write_text("const version = 2;\n")
    runtime_code_sha256.cache_clear()
    assert runtime_code_sha256("youtube", tmp_path) != pot_before
    assert runtime_code_sha256("douyin", tmp_path) == douyin_before_pot
    youtube_anonymous = runtime_code_sha256(
        "youtube", tmp_path, access_mode=ProviderAccessMode.ANONYMOUS
    )
    youtube_operator = runtime_code_sha256(
        "youtube", tmp_path, access_mode=ProviderAccessMode.OPERATOR_MANAGED
    )
    chrome_source.write_text("extract = 2\n")
    runtime_code_sha256.cache_clear()
    assert (
        runtime_code_sha256(
            "youtube", tmp_path, access_mode=ProviderAccessMode.ANONYMOUS
        )
        == youtube_anonymous
    )
    assert (
        runtime_code_sha256(
            "youtube", tmp_path, access_mode=ProviderAccessMode.OPERATOR_MANAGED
        )
        == youtube_operator
    )
    wechat_operator = runtime_code_sha256(
        "wechat_channels", tmp_path, access_mode=ProviderAccessMode.OPERATOR_MANAGED
    )
    youtube_operator = runtime_code_sha256(
        "youtube", tmp_path, access_mode=ProviderAccessMode.OPERATOR_MANAGED
    )
    yuanbao_session.write_text("session = 2\n")
    runtime_code_sha256.cache_clear()
    assert (
        runtime_code_sha256(
            "wechat_channels", tmp_path, access_mode=ProviderAccessMode.OPERATOR_MANAGED
        )
        != wechat_operator
    )
    assert (
        runtime_code_sha256(
            "youtube", tmp_path, access_mode=ProviderAccessMode.OPERATOR_MANAGED
        )
        == youtube_operator
    )
    wechat_before = runtime_code_sha256("wechat_channels", tmp_path)
    youtube_before_wechat = runtime_code_sha256("youtube", tmp_path)
    douyin_before_wechat = runtime_code_sha256("douyin", tmp_path)
    wechat_policy.write_text("policy = 2\n")
    runtime_code_sha256.cache_clear()
    assert runtime_code_sha256("wechat_channels", tmp_path) != wechat_before
    assert runtime_code_sha256("youtube", tmp_path) == youtube_before_wechat
    assert runtime_code_sha256("douyin", tmp_path) == douyin_before_wechat
    contracts.write_text("accept_media = False\n")
    runtime_code_sha256.cache_clear()
    assert runtime_code_sha256("douyin", tmp_path) != douyin_before_pot
    policy.write_text("route = 'guest'\n")
    runtime_code_sha256.cache_clear()
    changed_policy = runtime_code_sha256("douyin", tmp_path)
    assert runtime_code_sha256("tiktok", tmp_path) != other_provider
    rules = services / "downloads" / "rules"
    rules.mkdir(parents=True)
    selection = rules / "selection.py"
    selection.write_text("choice = 'first'\n")
    runtime_code_sha256.cache_clear()
    changed_selection = runtime_code_sha256("douyin", tmp_path)
    selection.write_text("choice = 'best'\n")
    runtime_code_sha256.cache_clear()

    assert changed_plugin != original
    assert changed_policy != changed_plugin
    assert changed_selection != changed_policy
    changed_selection_again = runtime_code_sha256("douyin", tmp_path)
    assert changed_selection_again != changed_selection
    main.write_text("protocol = 2\n")
    runtime_code_sha256.cache_clear()
    assert runtime_code_sha256("douyin", tmp_path) == changed_selection_again


@pytest.mark.asyncio
async def test_youtube_companion_identity_checks_running_script(tmp_path: Path) -> None:
    script = tmp_path / "supervisor.mjs"
    script.write_text("running-script\n")
    observed_url = None
    observed_digest = sha256(script.read_bytes()).hexdigest()

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal observed_url
        observed_url = str(request.url)
        return httpx.Response(200, json={"sha256": observed_digest})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await require_youtube_sidecar_identity(
            "http://youtube-pot-provider:4416",
            supervisor_path=script,
            client=client,
        )
        assert observed_url == "http://youtube-pot-provider:4417/identity"
        observed_digest = "0" * 64
        with pytest.raises(RunnerFailure) as captured:
            await require_youtube_sidecar_identity(
                "http://youtube-pot-provider:4416",
                supervisor_path=script,
                client=client,
            )
        assert captured.value.code == "pot_provider_release_mismatch"
