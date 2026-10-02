from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.integrations.object_storage import MinioObjectStorage
from app.services.downloads.file_delivery import download_filename
from app.services.imports.errors import (
    ImportObjectStorageError,
    MultipartUploadNotFound,
    MultipartUploadRejected,
)
from app.services.imports.models import CompletedUploadPart
from minio.commonconfig import CopySource
from pydantic import SecretStr


class FakeMinio:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.content = b"normalized screenplay"

    def get_object(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls.append(("read", *args, kwargs))
        length = int(kwargs.get("length", len(self.content)))
        return FakeResponse(self.content[:length])

    def fput_object(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("put", *args, kwargs))

    def fget_object(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("get", *args, kwargs))

    def remove_object(self, *args: object) -> None:
        self.calls.append(("remove", *args))

    def presigned_get_object(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("presign", *args, kwargs))
        return "https://objects.example/artifact"

    def _create_multipart_upload(
        self, bucket: str, object_key: str, headers: dict[str, str]
    ) -> str:
        self.calls.append(("create_multipart", bucket, object_key, headers))
        return "upload-id"

    def get_presigned_url(self, *args: object, **kwargs: object) -> str:
        self.calls.append(("presign_part", *args, kwargs))
        return "https://objects.example/upload-part"

    def _complete_multipart_upload(
        self,
        bucket: str,
        object_key: str,
        upload_id: str,
        parts: list[CompletedUploadPart],
    ) -> SimpleNamespace:
        normalized = tuple((part.part_number, part.etag) for part in parts)
        self.calls.append(
            ("complete_multipart", bucket, object_key, upload_id, normalized)
        )
        return SimpleNamespace(etag="completed-etag")

    def _abort_multipart_upload(
        self, bucket: str, object_key: str, upload_id: str
    ) -> None:
        self.calls.append(("abort_multipart", bucket, object_key, upload_id))


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        pass

    def release_conn(self) -> None:
        pass


def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        minio_access_key=SecretStr("access"),
        minio_secret_key=SecretStr("secret"),
        minio_local_browser_endpoint="127.0.0.1:9000",
    )


async def test_storage_uses_private_and_public_clients(tmp_path: Path) -> None:
    private = FakeMinio()
    public = FakeMinio()
    storage = MinioObjectStorage(settings(), private=private, public=public)
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    target = tmp_path / "download.mp4"

    await storage.upload("jobs/one/video.mp4", source, "video/mp4")
    await storage.download("jobs/one/video.mp4", target)
    url = await storage.presigned_download(
        "jobs/one/video.mp4", title="example", ttl_seconds=60
    )
    await storage.delete("jobs/one/video.mp4")

    assert any(call[0] == "put" for call in private.calls)
    assert any(call[0] == "get" for call in private.calls)
    assert any(call[0] == "remove" for call in private.calls)
    presign = next(call for call in public.calls if call[0] == "presign")
    options = presign[-1]
    assert isinstance(options, dict)
    assert options["response_headers"] == {
        "response-content-disposition": 'attachment; filename="example.mp4"'
    }
    assert url == "https://objects.example/artifact"


async def test_storage_range_read_is_bounded() -> None:
    private = FakeMinio()
    storage = MinioObjectStorage(settings(), private=private)

    payload = await storage.read_range("documents/one/1/screenplay.md", length=10)

    assert payload == b"normalized"
    read = next(call for call in private.calls if call[0] == "read")
    assert read[-1] == {"offset": 0, "length": 10}
    with pytest.raises(ValueError, match="range length"):
        await storage.read_range("documents/one/1/screenplay.md", length=0)


async def test_storage_uses_video_title_in_content_disposition() -> None:
    public = FakeMinio()
    storage = MinioObjectStorage(settings(), private=FakeMinio(), public=public)

    await storage.presigned_download(
        "downloads/job-1/1/video.mp4", title="Q4 Showreel", ttl_seconds=60
    )

    assert _signed_disposition(public) == 'attachment; filename="Q4 Showreel.mp4"'


def test_download_filename_uses_a_sanitized_video_title() -> None:
    assert (
        download_filename("downloads/job-1/1/video.mp4", '  A/B: "cut"  ')
        == "AB cut.mp4"
    )


def test_download_filename_falls_back_to_a_media_extension() -> None:
    assert download_filename("downloads/job-1/1/video.mp4", "   ") == "video.mp4"


async def test_storage_uses_inline_disposition_for_video_preview() -> None:
    public = FakeMinio()
    storage = MinioObjectStorage(settings(), private=FakeMinio(), public=public)

    await storage.presigned_download(
        "downloads/job-1/1/video.mp4",
        title="Q4 Showreel",
        ttl_seconds=60,
        inline=True,
    )

    assert _signed_disposition(public) == "inline"


async def test_storage_encodes_cjk_title_with_rfc5987() -> None:
    public = FakeMinio()
    storage = MinioObjectStorage(settings(), private=FakeMinio(), public=public)

    await storage.presigned_download(
        "downloads/job-1/1/video.mp4",
        title="【官方 MV】Never Gonna Give You Up - Rick Astley",
        ttl_seconds=60,
    )

    disposition = _signed_disposition(public)
    assert disposition.startswith('attachment; filename="video.mp4"; filename*=')
    assert "UTF-8''" in disposition
    assert "%E3%80%90%E5%AE%98%E6%96%B9" in disposition


async def test_storage_uses_plain_title_when_ascii() -> None:
    public = FakeMinio()
    storage = MinioObjectStorage(settings(), private=FakeMinio(), public=public)

    await storage.presigned_download(
        "downloads/job-1/1/video.mp4", title="Build Notes", ttl_seconds=60
    )

    assert _signed_disposition(public) == 'attachment; filename="Build Notes.mp4"'


async def test_storage_falls_back_when_title_empty() -> None:
    public = FakeMinio()
    storage = MinioObjectStorage(settings(), private=FakeMinio(), public=public)

    await storage.presigned_download(
        "downloads/job-1/1/video.mp4", title="", ttl_seconds=60
    )

    assert _signed_disposition(public) == 'attachment; filename="video.mp4"'


def _signed_disposition(public: FakeMinio) -> str:
    presign = next(call for call in public.calls if call[0] == "presign")
    options = presign[-1]
    assert isinstance(options, dict)
    return str(options["response_headers"]["response-content-disposition"])


async def test_storage_rejects_unsafe_object_keys(tmp_path: Path) -> None:
    storage = MinioObjectStorage(settings(), private=FakeMinio(), public=FakeMinio())

    with pytest.raises(ValueError, match="unsafe object key"):
        await storage.upload("../secret", tmp_path / "missing", "video/mp4")


async def test_private_storage_cannot_sign_public_downloads() -> None:
    storage = MinioObjectStorage(settings(), private=FakeMinio())

    with pytest.raises(RuntimeError, match="public download signing is not enabled"):
        await storage.presigned_download("jobs/one/video.mp4", ttl_seconds=60)


async def test_storage_controls_one_deterministic_multipart_upload() -> None:
    private = FakeMinio()
    public = FakeMinio()
    storage = MinioObjectStorage(settings(), private=private, public=public)
    object_key = "quarantine/video/4f7f4a1d/1/source"
    digest = "a" * 64

    upload_id = await storage.create_multipart_upload(
        object_key,
        content_type="video/mp4",
        declared_sha256=digest,
    )
    url = await storage.presign_upload_part(
        object_key,
        upload_id,
        2,
        ttl_seconds=900,
        size_bytes=32,
    )
    etag = await storage.complete_multipart_upload(
        object_key,
        upload_id,
        (
            _multipart_part(2, '"22222222222222222222222222222222"'),
            _multipart_part(1, "11111111111111111111111111111111"),
        ),
    )
    await storage.abort_multipart_upload(object_key, upload_id)

    assert upload_id == "upload-id"
    assert "X-Amz-SignedHeaders=content-length%3Bhost" in url
    assert etag == "completed-etag"
    assert (
        "create_multipart",
        "video-artifacts",
        object_key,
        {
            "Content-Type": "video/mp4",
            "X-Amz-Meta-Declared-Sha256": digest,
        },
    ) in private.calls
    assert (
        "complete_multipart",
        "video-artifacts",
        object_key,
        "upload-id",
        (
            (1, "11111111111111111111111111111111"),
            (2, "22222222222222222222222222222222"),
        ),
    ) in private.calls
    assert "partNumber=2" in url
    assert "uploadId=upload-id" in url
    assert (
        "abort_multipart",
        "video-artifacts",
        object_key,
        "upload-id",
    ) in private.calls


async def test_storage_can_sign_upload_parts_for_local_web_clients() -> None:
    public = FakeMinio()
    local_browser = FakeMinio()
    storage = MinioObjectStorage(
        settings(),
        private=FakeMinio(),
        public=public,
        local_browser=local_browser,
    )

    url = await storage.presign_upload_part(
        "quarantine/video/resource/1/source",
        "upload-id",
        1,
        ttl_seconds=900,
        size_bytes=32,
        use_local_browser_endpoint=True,
    )

    assert not public.calls
    assert "X-Amz-SignedHeaders=content-length%3Bhost" in url
    assert url.startswith(settings().minio_local_browser_origin())


async def test_storage_can_sign_downloads_for_local_web_clients() -> None:
    public = FakeMinio()
    local_browser = FakeMinio()
    storage = MinioObjectStorage(
        settings(),
        private=FakeMinio(),
        public=public,
        local_browser=local_browser,
    )

    url = await storage.presigned_download(
        "downloads/job-1/1/video.mp4",
        ttl_seconds=60,
        inline=True,
        use_local_browser_endpoint=True,
    )

    assert url == "https://objects.example/artifact"
    assert not public.calls
    assert next(call for call in local_browser.calls if call[0] == "presign")


@pytest.mark.parametrize(
    ("part_number", "etag"),
    ((0, "1" * 32), (1, "not-an-etag")),
)
async def test_storage_rejects_invalid_multipart_parts(
    part_number: int, etag: str
) -> None:
    storage = MinioObjectStorage(settings(), private=FakeMinio())

    with pytest.raises(ValueError):
        await storage.complete_multipart_upload(
            "quarantine/video/resource/1/source",
            "upload-id",
            (_multipart_part(part_number, etag),),
        )


class PromotionMinio(FakeMinio):
    def __init__(self) -> None:
        super().__init__()
        self.objects: dict[str, SimpleNamespace] = {
            "quarantine/video/resource/1/source": SimpleNamespace(
                size=5,
                metadata={"x-amz-meta-declared-sha256": "0" * 64},
                content_type="video/mp4",
            )
        }

    def stat_object(self, bucket: str, object_key: str) -> SimpleNamespace:
        self.calls.append(("stat", bucket, object_key))
        try:
            return self.objects[object_key]
        except KeyError as exc:
            raise SimpleStorageError("NoSuchKey") from exc

    def copy_object(
        self,
        bucket: str,
        destination_key: str,
        source: CopySource,
        **kwargs: object,
    ) -> None:
        source_key = source.object_name
        source_object = self.objects[source_key]
        metadata = kwargs["metadata"]
        assert isinstance(metadata, dict)
        self.objects[destination_key] = SimpleNamespace(
            size=source_object.size,
            metadata={"x-amz-meta-sha256": metadata["sha256"]},
            content_type=metadata["Content-Type"],
        )
        self.calls.append(("copy", bucket, source_key, destination_key, kwargs))


class VerifiedUploadMinio(PromotionMinio):
    def fput_object(self, bucket: str, object_key: str, source: str, **kwargs) -> None:
        metadata = kwargs["metadata"]
        self.objects[object_key] = SimpleNamespace(
            size=Path(source).stat().st_size,
            metadata={"x-amz-meta-sha256": metadata["sha256"]},
            content_type=kwargs["content_type"],
        )
        self.calls.append(("verified-put", bucket, object_key, kwargs))


class SimpleStorageError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


class ErrorMinio(FakeMinio):
    def __init__(self, code: str) -> None:
        super().__init__()
        self.code = code

    def _complete_multipart_upload(
        self,
        bucket: str,
        object_key: str,
        upload_id: str,
        parts: list[CompletedUploadPart],
    ) -> SimpleNamespace:
        raise SimpleStorageError(self.code)

    def _abort_multipart_upload(
        self, bucket: str, object_key: str, upload_id: str
    ) -> None:
        raise SimpleStorageError(self.code)

    def stat_object(self, bucket: str, object_key: str) -> SimpleNamespace:
        raise SimpleStorageError(self.code)


@pytest.mark.parametrize(
    ("code", "error_type"),
    (
        ("InvalidPart", MultipartUploadRejected),
        ("InvalidPartOrder", MultipartUploadRejected),
        ("EntityTooSmall", MultipartUploadRejected),
        ("NoSuchUpload", MultipartUploadNotFound),
        ("AccessDenied", ImportObjectStorageError),
    ),
)
async def test_storage_translates_multipart_completion_errors(
    code: str, error_type: type[Exception]
) -> None:
    storage = MinioObjectStorage(settings(), private=ErrorMinio(code))

    with pytest.raises(error_type):
        await storage.complete_multipart_upload(
            "quarantine/video/resource/1/source",
            "upload-id",
            (_multipart_part(1, "1" * 32),),
        )


async def test_storage_abort_is_idempotent_when_upload_is_missing() -> None:
    storage = MinioObjectStorage(settings(), private=ErrorMinio("NoSuchUpload"))

    await storage.abort_multipart_upload(
        "quarantine/video/resource/1/source", "upload-id"
    )


async def test_storage_translates_head_access_error() -> None:
    storage = MinioObjectStorage(settings(), private=ErrorMinio("AccessDenied"))

    with pytest.raises(ImportObjectStorageError) as captured:
        await storage.stat("quarantine/video/resource/1/source")

    assert getattr(captured.value.__cause__, "code", None) == "AccessDenied"


async def test_storage_promotes_verified_object_idempotently() -> None:
    private = PromotionMinio()
    storage = MinioObjectStorage(settings(), private=private)
    source_key = "quarantine/video/resource/1/source"
    destination_key = "downloads/job/1/video.mp4"
    digest = "b" * 64

    first = await storage.promote(
        source_key,
        destination_key,
        expected_size_bytes=5,
        sha256=digest,
        content_type="video/mp4",
    )
    second = await storage.promote(
        source_key,
        destination_key,
        expected_size_bytes=5,
        sha256=digest,
        content_type="video/mp4",
    )

    assert first == second
    assert (first.size_bytes, first.sha256, first.content_type) == (
        5,
        digest,
        "video/mp4",
    )
    assert len([call for call in private.calls if call[0] == "copy"]) == 1


async def test_storage_uploads_generated_verified_object_idempotently(
    tmp_path: Path,
) -> None:
    private = VerifiedUploadMinio()
    storage = MinioObjectStorage(settings(), private=private)
    source = tmp_path / "screenplay.md"
    source.write_bytes(b"screenplay")
    destination = "documents/11111111-1111-4111-8111-111111111111/1/screenplay.md"
    digest = "d" * 64

    first = await storage.upload_verified(
        source,
        destination,
        expected_size_bytes=10,
        sha256=digest,
        content_type="text/markdown; charset=utf-8",
    )
    second = await storage.upload_verified(
        source,
        destination,
        expected_size_bytes=10,
        sha256=digest,
        content_type="text/markdown; charset=utf-8",
    )

    assert first == second
    assert len([call for call in private.calls if call[0] == "verified-put"]) == 1


def _multipart_part(part_number: int, etag: str) -> CompletedUploadPart:
    return CompletedUploadPart(part_number=part_number, etag=etag)
