from __future__ import annotations

from app.api.upload_signing import (
    use_browser_download_proxy,
    use_local_browser_upload_endpoint,
)
from app.core.config import Settings
from starlette.requests import Request


def test_local_web_development_request_uses_loopback_signer() -> None:
    request = _request(
        {
            "x-framefetch-upload-client": "local-web",
            "referer": "http://localhost:8101/",
        }
    )
    settings = Settings(
        app_env="development",
        minio_local_browser_endpoint="127.0.0.1:9000",
        _env_file=None,
    )

    assert use_local_browser_upload_endpoint(request, settings) is True


def test_remote_or_native_request_keeps_public_signer() -> None:
    settings = Settings(
        app_env="development",
        minio_local_browser_endpoint="127.0.0.1:9000",
        _env_file=None,
    )

    assert use_local_browser_upload_endpoint(_request({}), settings) is False
    assert (
        use_local_browser_upload_endpoint(
            _request(
                {
                    "x-framefetch-upload-client": "local-web",
                    "origin": "https://app.example.com",
                }
            ),
            settings,
        )
        is False
    )


def test_non_development_runtime_never_uses_the_local_signer() -> None:
    request = _request(
        {
            "x-framefetch-upload-client": "local-web",
            "origin": "http://127.0.0.1:8101",
        }
    )
    settings = Settings(
        app_env="test",
        minio_local_browser_endpoint="127.0.0.1:9000",
        _env_file=None,
    )

    assert use_local_browser_upload_endpoint(request, settings) is False


def test_web_download_proxy_is_available_for_any_authenticated_web_origin() -> None:
    settings = Settings.model_construct(app_env="production")

    assert (
        use_browser_download_proxy(
            _request(
                {
                    "x-framefetch-download-client": "local-web",
                    "origin": "https://stephenqius-macbook-pro.tailda4efa.ts.net",
                }
            ),
            settings,
        )
        is True
    )
    assert use_browser_download_proxy(_request({}), settings) is False


def _request(headers: dict[str, str]) -> Request:
    raw_headers = [(key.encode(), value.encode()) for key, value in headers.items()]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/documents/id/upload-sessions",
            "headers": raw_headers,
        }
    )
