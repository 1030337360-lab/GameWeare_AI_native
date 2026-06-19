from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from minio import Minio

from app.config import get_settings
from app.database import db_connection
from app.services.auth_service import require_user

router = APIRouter(prefix="/uploads", tags=["uploads"])

SUPPORTED_CREATE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@router.post("")
async def upload(
    file: UploadFile = File(...),
    user=Depends(require_user),
) -> dict[str, str | int | None]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "EMPTY_UPLOAD", "message": "Upload file is empty."})
    settings = get_settings()
    owner_id = user.id
    object_name = file.filename or "upload.bin"
    content_type = file.content_type or "application/octet-stream"
    if content_type not in SUPPORTED_CREATE_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "UNSUPPORTED_UPLOAD_TYPE",
                "message": "Create input uploads currently support PNG, JPEG, WebP, and GIF images.",
                "contentType": content_type,
            },
        )

    with db_connection() as connection:
        asset = connection.execute(
            """
INSERT INTO assets (owner_id, kind, bucket, object_key, content_type, size_bytes)
VALUES (%s, 'upload', %s, 'pending/' || gen_random_uuid()::text, %s, %s)
RETURNING id
""",
            (owner_id, settings.minio_bucket, content_type, len(content)),
        ).fetchone()
        object_key = f"uploads/{owner_id}/create-input/{asset['id']}/{object_name}"
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
        "assetId": str(asset["id"]),
        "filename": file.filename,
        "contentType": content_type,
        "size": len(content),
        "objectKey": object_key,
        "publicUrl": public_url,
    }


@router.delete("/{asset_id}")
def delete_upload(asset_id: str, user=Depends(require_user)) -> dict[str, bool | str]:
    settings = get_settings()
    with db_connection() as connection:
        asset = connection.execute(
            """
SELECT id, bucket, object_key
FROM assets
WHERE id = %s AND owner_id = %s AND kind = 'upload'
LIMIT 1
""",
            (asset_id, user.id),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Upload not found")
        connection.execute("DELETE FROM assets WHERE id = %s", (asset_id,))

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )
    try:
        client.remove_object(asset["bucket"], asset["object_key"])
    except Exception:
        pass
    return {"deleted": True, "assetId": asset_id}
