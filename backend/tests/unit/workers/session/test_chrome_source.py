import asyncio
import io
import json
import struct

import pytest
from app.workers.session.chrome_source import (
    BrowserReply,
    ChromeSource,
    SourceUnavailable,
)
from app.workers.session.native_host import read_message, write_message
from app.workers.session.source_cli import SourceConfig, agent_spec, install_extension


def cookie(name="SID", value="synthetic", domain=".youtube.com"):
    return dict(
        name=name,
        value=value,
        domain=domain,
        path="/",
        expirationDate=4102444800,
        secure=True,
        httpOnly=True,
    )


async def read(source, connection, values):
    task = asyncio.create_task(source.read("youtube.com"))
    request = await source.poll(connection)
    assert request["site"] == "youtube.com" and "google.com" not in request["domains"]
    source.reply(
        BrowserReply(
            connection=connection, request_id=request["request_id"], cookies=values
        )
    )
    return await task


async def test_current_material_scoping_generation_and_reconnect():
    source = ChromeSource(secret=b"s" * 32)
    connection = source.connect().connection
    first = await read(
        source, connection, [cookie(), cookie("foreign", "never-export", ".google.com")]
    )
    assert b"never-export" not in first.cookies and b"SID" in first.cookies
    assert "synthetic" not in repr(first)
    assert (
        await read(source, connection, [cookie(), cookie("analytics", "changed")])
    ).generation == first.generation
    assert (
        await read(source, connection, [cookie(value="rotated")])
    ).generation != first.generation
    source.disconnect(connection)
    connection = source.connect().connection
    assert (await read(source, connection, [cookie()])).generation != first.generation
    await source.close()


async def test_missing_browser_and_missing_login_are_distinct():
    source = ChromeSource(secret=b"s" * 32)
    with pytest.raises(SourceUnavailable, match="provider_session_not_ready"):
        await source.read("youtube.com")
    connection = source.connect().connection
    with pytest.raises(SourceUnavailable, match="credential_required"):
        await read(
            source,
            connection,
            [cookie(domain=".evil-youtube.com"), cookie(value="bad\nvalue")],
        )
    with pytest.raises(SourceUnavailable, match="provider_session_not_allowed"):
        await source.open_login("../youtube.com")


async def test_no_takeover_stale_reply_and_cancel_cleanup():
    source = ChromeSource(secret=b"s" * 32)
    connection = source.connect().connection
    with pytest.raises(SourceUnavailable):
        source.connect()
    task = asyncio.create_task(source.read("youtube.com"))
    request = await source.poll(connection)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not source._pending
    with pytest.raises(SourceUnavailable, match="credential_revoked"):
        source.reply(
            BrowserReply(
                connection=connection,
                request_id=request["request_id"],
                cookies=[cookie()],
            )
        )
    task = asyncio.create_task(source.read("youtube.com"))
    await source.poll(connection)
    source.disconnect(connection)
    with pytest.raises(SourceUnavailable):
        await task
    assert not source._pending


async def test_login_opens_only_registry_url_and_exports_no_cookies():
    source = ChromeSource(secret=b"s" * 32)
    connection = source.connect().connection
    task = asyncio.create_task(source.open_login("youtube.com"))
    request = await source.poll(connection)
    assert request["command"] == "login"
    assert request["login_url"] == "https://www.youtube.com/feed/you"
    source.reply(BrowserReply(connection=connection, request_id=request["request_id"]))
    await task


@pytest.mark.parametrize(
    "payload",
    [
        b"\x01",
        struct.pack("=I", 1024**2 + 1),
        struct.pack("=I", 3) + b"{}",
        struct.pack("=I", 2) + b"[]",
    ],
)
def test_native_messaging_rejects_truncated_oversized_and_non_object(payload):
    with pytest.raises(ValueError):
        read_message(io.BytesIO(payload))


def test_native_messaging_round_trip_and_eof():
    stream = io.BytesIO()
    write_message(stream, {"command": "read", "site": "youtube.com"})
    stream.seek(0)
    assert read_message(stream) == {"command": "read", "site": "youtube.com"}
    assert read_message(stream) is None


def test_install_uses_registry_permissions_and_private_native_config(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.workers.session.source_cli.Path.home", lambda: tmp_path)
    config = SourceConfig(b"s" * 32, tmp_path / "source")
    install_extension(config)
    manifest = json.loads((config.root / "ChromeExtension/manifest.json").read_text())
    assert "https://*.youtube.com/*" in manifest["host_permissions"]
    assert "<all_urls>" not in manifest["host_permissions"]
    assert (
        "content_scripts" not in manifest and "externally_connectable" not in manifest
    )
    assert (config.root / "native-config.json").stat().st_mode & 0o777 == 0o600
    assert (config.root / "native-host").stat().st_mode & 0o777 == 0o700
    assert set(agent_spec(config)["EnvironmentVariables"]) == {
        "PATH",
        "SITE_SESSION_AGENT_SECRET",
        "SITE_SESSION_PROFILE_ROOT",
    }
    for browser in ("Chrome", "ChromeForTesting"):
        host = json.loads(
            (
                tmp_path
                / f"Library/Application Support/Google/{browser}/NativeMessagingHosts"
                / "com.framefetch.chrome_source.json"
            ).read_text()
        )
        assert (
            len(host["allowed_origins"]) == 1 and "*" not in host["allowed_origins"][0]
        )
        assert "secret" not in host


def test_reinstall_retries_launchd_teardown(tmp_path, monkeypatch):
    import subprocess

    from app.workers.session import source_cli

    monkeypatch.setattr(source_cli.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(source_cli.time, "sleep", lambda _: None)
    bootstraps = []

    def launchctl(*args, **kwargs):
        if args[0] == "bootstrap":
            bootstraps.append(args)
            if len(bootstraps) == 1:
                raise subprocess.CalledProcessError(5, args)

    monkeypatch.setattr(source_cli, "launchctl", launchctl)
    source_cli.install(SourceConfig(b"s" * 32, tmp_path / "source"))
    assert len(bootstraps) == 2
    assert (
        tmp_path / "Library/LaunchAgents/com.framefetch.browser-source.plist"
    ).stat().st_mode & 0o777 == 0o600


async def test_completed_reply_is_rejected_if_chrome_reconnects_before_read_resumes():
    source = ChromeSource(secret=b"s" * 32)
    connection = source.connect().connection
    task = asyncio.create_task(source.read("youtube.com"))
    request = await source.poll(connection)
    source.reply(
        BrowserReply(
            connection=connection, request_id=request["request_id"], cookies=[cookie()]
        )
    )
    source.disconnect(connection)
    source.connect()
    with pytest.raises(SourceUnavailable, match="credential_revoked"):
        await task
    assert not source._pending


def test_yuanbao_page_identity_cannot_replace_the_cookie_generation():
    from app.workers.session.chrome_source import _cookie
    from app.workers.session.page_headers import PageHeadersUnavailable, yuanbao_payload

    values = [
        _cookie(cookie("hy_user", "account-a")),
        _cookie(cookie("hy_token", "token-a")),
    ]
    auth = {
        "userId": "account-a",
        "token": "token-a",
        "headers": {"x-device-id": "device"},
    }
    assert json.loads(yuanbao_payload(auth, values))["userId"] == "account-a"
    with pytest.raises(PageHeadersUnavailable):
        yuanbao_payload({**auth, "userId": "account-b"}, values)
