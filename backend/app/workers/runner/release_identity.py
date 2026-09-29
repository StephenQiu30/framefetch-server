"""Identity of the packaged extraction and Provider policy code."""

from __future__ import annotations

from functools import cache
from hashlib import sha256
from pathlib import Path

import httpx
from app.services.provider_types import ProviderAccessMode
from app.workers.runner.errors import RunnerFailure

_APP_ROOT = Path(__file__).resolve().parents[2]
_NON_MEDIA_MODULES = {
    "active_tasks.py",
    "engine_catalog.py",
    "main.py",
    "readiness.py",
    "release_identity.py",
    "signing.py",
}
_PROVIDER_MODULES = {
    "wechat_channels_policy.py": "wechat_channels",
    "provider_session_headers.py": "wechat_channels",
}
# Only the site session Runner loads these; anonymous contexts ignore them.
_OPERATOR_MODULES = frozenset({"site_sessions.py", "provider_session_headers.py"})
_PROVIDER_PLUGINS = {
    "bilibili_access.py": "bilibili",
    "douyin_note.py": "douyin",
    "douyin_share.py": "douyin",
    "facebook_post.py": "facebook",
    "hongguo_official_share.py": "hongguo_web",
    "instagram_media.py": "instagram",
    "kuaishou_public.py": "kuaishou",
    "tiktok_public_player.py": "tiktok",
    "tumblr_public.py": "tumblr",
    "wechat_channels_public.py": "wechat_channels",
    "weibo_short.py": "weibo",
    "xiaohongshu_availability.py": "xiaohongshu",
}
_SHARED_PROVIDER_PLUGINS = {
    "personal_video.py": frozenset({"youku", "qqvideo"}),
    "_content_access.py": frozenset({"bilibili", "douyin", "youku", "qqvideo"}),
}
_HASH_SCHEMA_VERSION = b"v1"
_SHARED_PROVIDER_SERVICES = frozenset(
    {
        "provider_access.py",
        "provider_route_admission.py",
        "provider_types.py",
    }
)


@cache
def runtime_code_sha256(
    provider_key: str,
    app_root: Path = _APP_ROOT,
    *,
    access_mode: ProviderAccessMode | None = None,
) -> str:
    """Scope extraction changes to the affected Provider where possible."""
    runner_root = app_root / "workers" / "runner"
    plugins_root = runner_root / "plugins"
    paths = {
        *(
            path
            for path in runner_root.glob("*.py")
            if path.name not in _NON_MEDIA_MODULES
            and _PROVIDER_MODULES.get(path.name, provider_key) == provider_key
            and (
                path.name not in _OPERATOR_MODULES
                or access_mode is None
                or access_mode is ProviderAccessMode.OPERATOR_MANAGED
            )
        ),
        *(
            path
            for path in runner_root.rglob("*.mjs")
            if path.name != "youtube-pot-supervisor.mjs" or provider_key == "youtube"
        ),
        *(
            path
            for path in plugins_root.rglob("*.py")
            if (
                provider_key in _SHARED_PROVIDER_PLUGINS[path.name]
                if path.name in _SHARED_PROVIDER_PLUGINS
                else _PROVIDER_PLUGINS.get(path.name, provider_key) == provider_key
            )
        ),
        *(
            app_root / "services" / name
            for name in _SHARED_PROVIDER_SERVICES
            if (app_root / "services" / name).exists()
        ),
        app_root / "services" / "downloads" / "inspection_models.py",
        app_root / "services" / "downloads" / "plans.py",
        *(app_root / "services" / "downloads" / "rules").rglob("*.py"),
    }
    digest = sha256()
    digest.update(_HASH_SCHEMA_VERSION)
    for path in sorted(paths):
        digest.update(path.relative_to(app_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


async def require_youtube_sidecar_identity(
    base_url: str,
    *,
    supervisor_path: Path = (
        _APP_ROOT / "workers" / "runner" / "youtube-pot-supervisor.mjs"
    ),
    client: httpx.AsyncClient | None = None,
) -> None:
    """Fail closed when the running POT supervisor differs from Runner code."""
    expected = sha256(supervisor_path.read_bytes()).hexdigest()
    identity_url = httpx.URL(base_url).copy_with(port=4417, path="/identity")
    try:
        if client is None:
            async with httpx.AsyncClient(
                timeout=2.0, trust_env=False, follow_redirects=False
            ) as own_client:
                response = await own_client.get(identity_url)
        else:
            response = await client.get(identity_url)
        payload = response.json()
        if (
            response.status_code != 200
            or not isinstance(payload, dict)
            or payload.get("sha256") != expected
        ):
            raise RunnerFailure("pot_provider_release_mismatch", status=503)
    except (httpx.HTTPError, ValueError) as exc:
        raise RunnerFailure("pot_provider_release_mismatch", status=503) from exc
