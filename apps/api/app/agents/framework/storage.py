from __future__ import annotations

import hashlib
import json
from io import BytesIO
from typing import Any

from minio import Minio

from app.config import get_settings


def json_bytes(payload: dict[str, Any] | list[Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )


def put_json_object(object_key: str, payload: dict[str, Any] | list[Any]) -> tuple[str, int, str]:
    settings = get_settings()
    content = json_bytes(payload)
    client = minio_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
    client.put_object(
        settings.minio_bucket,
        object_key,
        BytesIO(content),
        length=len(content),
        content_type="application/json",
    )
    return object_key, len(content), sha256_hex(content)


def put_jsonl_object(object_key: str, records: list[dict[str, Any]]) -> tuple[str, int, str]:
    settings = get_settings()
    content = ("\n".join(json.dumps(record, ensure_ascii=False, default=str) for record in records) + "\n").encode("utf-8")
    client = minio_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
    client.put_object(
        settings.minio_bucket,
        object_key,
        BytesIO(content),
        length=len(content),
        content_type="application/x-ndjson",
    )
    return object_key, len(content), sha256_hex(content)
