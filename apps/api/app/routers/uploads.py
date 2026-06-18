from fastapi import APIRouter, Depends, File, UploadFile
from minio import Minio

from app.config import get_settings
from app.database import db_connection
from app.services.auth_service import get_optional_user

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("")
async def upload(
    file: UploadFile = File(...),
    user=Depends(get_optional_user),
) -> dict[str, str | int | None]:
    content = await file.read()
    settings = get_settings()
    owner_id = user.id if user else None
    object_name = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"

    with db_connection() as connection:
        asset = connection.execute(
            """
INSERT INTO assets (owner_id, kind, bucket, object_key, content_type, size_bytes)
VALUES (%s, 'upload', %s, 'pending/' || gen_random_uuid()::text, %s, %s)
RETURNING id
""",
            (owner_id, settings.minio_bucket, content_type, len(content)),
        ).fetchone()
        object_key = f"uploads/{owner_id or 'anonymous'}/manual/{asset['id']}/{object_name}"
        public_url = f"{settings.minio_public_base_url}/{object_key}"
        connection.execute(
            """
UPDATE assets
SET object_key = %s, public_url = %s
WHERE id = %s
""",
            (object_key, public_url, asset["id"]),
        )

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
    from io import BytesIO

    client.put_object(
        settings.minio_bucket,
        object_key,
        BytesIO(content),
        length=len(content),
        content_type=content_type,
    )

    return {
        "status": "uploaded",
        "filename": file.filename,
        "contentType": content_type,
        "size": len(content),
        "objectKey": object_key,
    }
