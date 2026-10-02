"""Private MinIO storage with optional public download signing."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Protocol

from minio import Minio
from minio.commonconfig import REPLACE, CopySource
from minio.datatypes import Part

from app.core.config import Settings
from app.integrations.upload_signing import UploadSigner
from app.services.downloads.file_delivery import download_disposition
from app.services.imports.errors import (
    ImportObjectStorageError,
    MultipartUploadNotFound,
    MultipartUploadRejected,
)


@dataclass(frozen=True, slots=True)
class StoredObjectStat:
    size_bytes: int
    sha256: str | None
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    last_modified: datetime


class MultipartUploadPartLike(Protocol):
    @property
    def part_number(self) -> int: ...

    @property
    def etag(self) -> str: ...


class MinioObjectStorage:
    def __init__(
        self,
        settings: Settings,
        *,
        private: Minio | None = None,
        public: Minio | None = None,
        local_browser: Minio | None = None,
        enable_public_signing: bool = False,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        if (access_key is None) != (secret_key is None):
            raise ValueError("MinIO access and secret keys must be configured together")
        access_key = access_key or settings.minio_access_key.get_secret_value()
        secret_key = secret_key or settings.minio_secret_key.get_secret_value()
        self._bucket = settings.minio_bucket
        self._upload_signer = UploadSigner(
            settings.minio_public_origin(),
            settings.minio_region,
            access_key,
            secret_key,
        )
        local_origin = settings.minio_local_browser_origin()
        self._local_upload_signer = (
            None
            if local_origin is None
            else UploadSigner(
                local_origin, settings.minio_region, access_key, secret_key
            )
        )
        self._private = private or Minio(
            settings.minio_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=settings.minio_internal_secure,
            region=settings.minio_region,
        )
        self._public = public
        self._local_browser = local_browser
        if self._public is None and enable_public_signing:
            self._public = Minio(
                settings.minio_public_endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=settings.minio_public_secure,
                region=settings.minio_region,
            )
        if (
            self._local_browser is None
            and enable_public_signing
            and settings.minio_local_browser_endpoint is not None
        ):
            self._local_browser = Minio(
                settings.minio_local_browser_endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=settings.minio_local_browser_secure,
                region=settings.minio_region,
            )

    @property
    def bucket(self) -> str:
        return self._bucket

    async def upload(self, object_key: str, source: Path, content_type: str) -> int:
        _validate_key(object_key)
        size = source.stat().st_size
        await asyncio.to_thread(
            self._private.fput_object,
            self._bucket,
            object_key,
            str(source),
            content_type=content_type,
        )
        return size

    async def upload_bytes(
        self, object_key: str, content: bytes, content_type: str, sha256: str
    ) -> int:
        _validate_key(object_key)
        if not content:
            raise ValueError("object content cannot be empty")
        await asyncio.to_thread(
            self._private.put_object,
            self._bucket,
            object_key,
            BytesIO(content),
            len(content),
            content_type=content_type,
            metadata={"sha256": sha256},
        )
        return len(content)

    async def stat(self, object_key: str) -> StoredObjectStat | None:
        _validate_key(object_key)
        try:
            result = await asyncio.to_thread(
                self._private.stat_object, self._bucket, object_key
            )
        except Exception as error:
            if getattr(error, "code", None) in {"NoSuchKey", "NoSuchObject"}:
                return None
            raise ImportObjectStorageError("object HEAD failed") from error
        metadata = getattr(result, "metadata", {}) or {}
        sha256 = metadata.get("x-amz-meta-sha256") or metadata.get("sha256")
        if result.size is None:
            raise RuntimeError("object storage returned no size")
        return StoredObjectStat(
            size_bytes=result.size,
            sha256=sha256,
            content_type=getattr(result, "content_type", None),
        )

    async def create_multipart_upload(
        self,
        object_key: str,
        *,
        content_type: str,
        declared_sha256: str | None = None,
    ) -> str:
        """Create a multipart upload for one server-selected object key.

        The MinIO Python SDK currently exposes multipart control primitives as
        private methods. They are isolated here so the application port remains
        stable if the pinned SDK changes its implementation.
        """
        _validate_key(object_key)
        _validate_content_type(content_type)
        headers: dict[str, str | list[str] | tuple[str]] = {
            "Content-Type": content_type
        }
        if declared_sha256 is not None:
            headers["X-Amz-Meta-Declared-Sha256"] = _validate_sha256(declared_sha256)
        try:
            upload_id = await asyncio.to_thread(
                self._private._create_multipart_upload,
                self._bucket,
                object_key,
                headers,
            )
        except Exception as error:
            raise ImportObjectStorageError("multipart creation failed") from error
        return _validate_upload_id(upload_id)

    async def presign_upload_part(
        self,
        object_key: str,
        upload_id: str,
        part_number: int,
        *,
        ttl_seconds: int,
        size_bytes: int,
        use_local_browser_endpoint: bool = False,
    ) -> str:
        _validate_key(object_key)
        upload_id = _validate_upload_id(upload_id)
        signer = self._local_browser if use_local_browser_endpoint else self._public
        if signer is None:
            raise RuntimeError("public upload signing is not enabled")
        if isinstance(part_number, bool) or not 1 <= part_number <= 10_000:
            raise ValueError("part number must be between 1 and 10000")
        if isinstance(ttl_seconds, bool) or not 1 <= ttl_seconds <= 604_800:
            raise ValueError("upload signing TTL must be between 1 and 604800")
        upload_signer = (
            self._local_upload_signer
            if use_local_browser_endpoint
            else self._upload_signer
        )
        if upload_signer is None:
            raise RuntimeError("local browser upload signing is not configured")
        return upload_signer.part_url(
            self._bucket,
            object_key,
            upload_id,
            part_number,
            size_bytes=size_bytes,
            ttl_seconds=ttl_seconds,
        )

    async def complete_multipart_upload(
        self,
        object_key: str,
        upload_id: str,
        parts: tuple[MultipartUploadPartLike, ...],
    ) -> str | None:
        _validate_key(object_key)
        upload_id = _validate_upload_id(upload_id)
        normalized = _normalize_multipart_parts(parts)
        try:
            result = await asyncio.to_thread(
                self._private._complete_multipart_upload,
                self._bucket,
                object_key,
                upload_id,
                normalized,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            if code == "NoSuchUpload":
                raise MultipartUploadNotFound("multipart upload not found") from error
            if code in {"EntityTooSmall", "InvalidPart", "InvalidPartOrder"}:
                raise MultipartUploadRejected("multipart manifest rejected") from error
            raise ImportObjectStorageError("multipart completion failed") from error
        return getattr(result, "etag", None)

    async def abort_multipart_upload(self, object_key: str, upload_id: str) -> None:
        _validate_key(object_key)
        upload_id = _validate_upload_id(upload_id)
        try:
            await asyncio.to_thread(
                self._private._abort_multipart_upload,
                self._bucket,
                object_key,
                upload_id,
            )
        except Exception as error:
            if getattr(error, "code", None) == "NoSuchUpload":
                return
            raise ImportObjectStorageError("multipart abort failed") from error

    async def promote(
        self,
        source_key: str,
        destination_key: str,
        *,
        expected_size_bytes: int,
        sha256: str,
        content_type: str,
    ) -> StoredObjectStat:
        """Idempotently copy a verified object to its deterministic final key.

        The quarantine source is intentionally retained. Its deletion belongs to
        post-commit cleanup/reconciliation so a database failure cannot lose the
        only recoverable copy.
        """
        _validate_key(source_key)
        _validate_key(destination_key)
        if source_key == destination_key:
            raise ValueError("source and destination object keys must differ")
        if isinstance(expected_size_bytes, bool) or expected_size_bytes <= 0:
            raise ValueError("expected object size must be positive")
        sha256 = _validate_sha256(sha256)
        _validate_content_type(content_type)

        current = await self.stat(destination_key)
        if current is not None:
            if (current.size_bytes, current.sha256, current.content_type) != (
                expected_size_bytes,
                sha256,
                content_type,
            ):
                raise RuntimeError("destination object conflicts with promotion")
            return current

        source = await self.stat(source_key)
        if source is None or source.size_bytes != expected_size_bytes:
            raise RuntimeError("source object conflicts with promotion")
        try:
            await asyncio.to_thread(
                self._private.copy_object,
                self._bucket,
                destination_key,
                CopySource(self._bucket, source_key),
                metadata={"Content-Type": content_type, "sha256": sha256},
                metadata_directive=REPLACE,
            )
        except Exception as error:
            raise ImportObjectStorageError("object promotion failed") from error
        promoted = await self.stat(destination_key)
        if promoted is None or (promoted.size_bytes, promoted.sha256) != (
            expected_size_bytes,
            sha256,
        ):
            raise RuntimeError("promoted object failed verification")
        return promoted

    async def upload_verified(
        self,
        source: Path,
        destination_key: str,
        *,
        expected_size_bytes: int,
        sha256: str,
        content_type: str,
    ) -> StoredObjectStat:
        """Idempotently persist a locally generated, already verified artifact."""
        _validate_key(destination_key)
        sha256 = _validate_sha256(sha256)
        _validate_content_type(content_type)
        if source.stat().st_size != expected_size_bytes or expected_size_bytes <= 0:
            raise ValueError("verified object size does not match")
        current = await self.stat(destination_key)
        if current is not None:
            if (current.size_bytes, current.sha256, current.content_type) != (
                expected_size_bytes,
                sha256,
                content_type,
            ):
                raise RuntimeError("destination object conflicts with upload")
            return current
        try:
            await asyncio.to_thread(
                self._private.fput_object,
                self._bucket,
                destination_key,
                str(source),
                content_type=content_type,
                metadata={"sha256": sha256},
            )
        except Exception as error:
            raise ImportObjectStorageError("verified object upload failed") from error
        stored = await self.stat(destination_key)
        if stored is None or (stored.size_bytes, stored.sha256) != (
            expected_size_bytes,
            sha256,
        ):
            raise RuntimeError("uploaded object failed verification")
        return stored

    async def read(self, object_key: str) -> bytes:
        _validate_key(object_key)
        response = await asyncio.to_thread(
            self._private.get_object, self._bucket, object_key
        )
        try:
            return await asyncio.to_thread(response.read)
        finally:
            response.close()
            response.release_conn()

    async def read_range(self, object_key: str, *, length: int) -> bytes:
        _validate_key(object_key)
        if isinstance(length, bool) or not 1 <= length <= 256 * 1024:
            raise ValueError("object range length is invalid")
        try:
            response = await asyncio.to_thread(
                self._private.get_object,
                self._bucket,
                object_key,
                offset=0,
                length=length,
            )
            try:
                return await asyncio.to_thread(response.read)
            finally:
                response.close()
                response.release_conn()
        except Exception as error:
            raise ImportObjectStorageError("object range read failed") from error

    async def download(self, object_key: str, target: Path) -> None:
        _validate_key(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            self._private.fget_object,
            self._bucket,
            object_key,
            str(target),
        )

    def iter_download(
        self,
        object_key: str,
        *,
        offset: int = 0,
        length: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        """Stream a private artifact without exposing the storage endpoint."""
        _validate_key(object_key)
        if offset < 0 or (length is not None and length < 1):
            raise ValueError("download range is invalid")
        if chunk_size < 1:
            raise ValueError("download chunk size is invalid")
        if length is None:
            response = (
                self._private.get_object(self._bucket, object_key, offset=offset)
                if offset
                else self._private.get_object(self._bucket, object_key)
            )
        else:
            response = self._private.get_object(
                self._bucket,
                object_key,
                offset=offset,
                length=length,
            )
        remaining = length
        try:
            while True:
                read_size = (
                    chunk_size if remaining is None else min(chunk_size, remaining)
                )
                chunk = response.read(read_size)
                if not chunk:
                    break
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
        finally:
            response.close()
            response.release_conn()

    async def presigned_download(
        self,
        object_key: str,
        *,
        title: str | None = None,
        ttl_seconds: int,
        inline: bool = False,
        use_local_browser_endpoint: bool = False,
    ) -> str:
        _validate_key(object_key)
        signer = self._local_browser if use_local_browser_endpoint else self._public
        if signer is None:
            raise RuntimeError("public download signing is not enabled")
        return await asyncio.to_thread(
            signer.presigned_get_object,
            self._bucket,
            object_key,
            expires=timedelta(seconds=ttl_seconds),
            response_headers={
                "response-content-disposition": (
                    "inline" if inline else download_disposition(object_key, title)
                )
            },
        )

    async def delete(self, object_key: str) -> None:
        _validate_key(object_key)
        try:
            await asyncio.to_thread(
                self._private.remove_object, self._bucket, object_key
            )
        except Exception as error:
            raise ImportObjectStorageError("object deletion failed") from error

    async def list(self, prefix: str) -> tuple[StoredObject, ...]:
        _validate_key(prefix)

        def collect() -> tuple[StoredObject, ...]:
            return tuple(
                StoredObject(item.object_name, item.last_modified)
                for item in self._private.list_objects(
                    self._bucket, prefix=prefix, recursive=True
                )
                if item.object_name is not None and item.last_modified is not None
            )

        return await asyncio.to_thread(collect)


def _validate_key(object_key: str) -> None:
    path = PurePosixPath(object_key)
    unsafe = (
        not object_key
        or object_key.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
    )
    if unsafe:
        raise ValueError("unsafe object key")


def _validate_upload_id(upload_id: str) -> str:
    if (
        not isinstance(upload_id, str)
        or not upload_id
        or len(upload_id) > 1024
        or any(ord(character) < 0x20 for character in upload_id)
    ):
        raise ValueError("invalid multipart upload id")
    return upload_id


def _validate_sha256(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("SHA-256 must be lowercase hexadecimal")
    return value


def _validate_content_type(value: str) -> None:
    if (
        not value
        or len(value) > 255
        or value != value.strip()
        or "\r" in value
        or "\n" in value
        or "/" not in value
    ):
        raise ValueError("invalid content type")


def _normalize_multipart_parts(
    parts: tuple[MultipartUploadPartLike, ...],
) -> list[Part]:
    if not parts or len(parts) > 10_000:
        raise ValueError("multipart completion requires between 1 and 10000 parts")
    normalized: list[Part] = []
    seen: set[int] = set()
    for item in parts:
        if (
            isinstance(item.part_number, bool)
            or not 1 <= item.part_number <= 10_000
            or item.part_number in seen
        ):
            raise ValueError("multipart part numbers must be unique and in range")
        etag = item.etag.removeprefix('"').removesuffix('"')
        if re.fullmatch(r"[0-9a-fA-F]{32}", etag) is None:
            raise ValueError("invalid multipart part ETag")
        seen.add(item.part_number)
        normalized.append(Part(item.part_number, etag.lower()))
    return sorted(normalized, key=lambda item: item.part_number)
