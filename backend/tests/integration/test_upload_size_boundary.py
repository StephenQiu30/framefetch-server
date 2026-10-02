"""Real S3 boundary: run against an isolated MinIO via TEST_MINIO_ENDPOINT."""

import asyncio
import os
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings
from app.integrations.object_storage import MinioObjectStorage
from app.services.imports.models import CompletedUploadPart
from minio import Minio


@pytest.mark.skipif(
    not os.getenv("TEST_MINIO_ENDPOINT"), reason="isolated MinIO endpoint not supplied"
)
async def test_upload_signature_rejects_larger_and_smaller_parts():
    endpoint = os.environ["TEST_MINIO_ENDPOINT"]
    bucket = f"review-{uuid4().hex}"
    settings = Settings(
        _env_file=None,
        app_env="test",
        minio_endpoint=endpoint,
        minio_public_endpoint=endpoint,
        minio_access_key=os.environ["TEST_MINIO_ACCESS_KEY"],
        minio_secret_key=os.environ["TEST_MINIO_SECRET_KEY"],
        minio_bucket=bucket,
    )
    private = Minio(
        endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=False,
    )
    await asyncio.to_thread(private.make_bucket, bucket)
    storage = MinioObjectStorage(settings, private=private, enable_public_signing=True)
    key = f"quarantine/video/{uuid4()}/1/source"
    upload_id = None
    try:
        upload_id = await storage.create_multipart_upload(key, content_type="video/mp4")
        url = await storage.presign_upload_part(
            key, upload_id, 1, ttl_seconds=60, size_bytes=32
        )
        assert parse_qs(urlsplit(url).query)["X-Amz-SignedHeaders"] == [
            "content-length;host"
        ]
        targets = [(url, {})]
        proxy = os.getenv("TEST_NEXT_UPLOAD_ORIGIN")
        if proxy:
            targets.append(
                (f"{proxy}/storage-upload", {"X-FrameFetch-Upload-Target": url})
            )
        async with httpx.AsyncClient(trust_env=False) as client:
            for target, headers in targets:
                for size in (31, 33, 1024):
                    rejected = await client.put(
                        target, content=b"x" * size, headers=headers
                    )
                    assert rejected.status_code == 403
                accepted = await client.put(target, content=b"x" * 32, headers=headers)
                assert accepted.status_code == 200
        await storage.complete_multipart_upload(
            key, upload_id, (CompletedUploadPart(1, accepted.headers["etag"]),)
        )
        upload_id = None
        assert (await storage.stat(key)).size_bytes == 32
    finally:
        if upload_id is not None:
            await storage.abort_multipart_upload(key, upload_id)
        await storage.delete(key)
        await asyncio.to_thread(private.remove_bucket, bucket)
