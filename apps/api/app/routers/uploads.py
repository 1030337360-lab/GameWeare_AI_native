from fastapi import APIRouter, File, UploadFile

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("")
async def upload(file: UploadFile = File(...)) -> dict[str, str | int | None]:
    content = await file.read()
    return {
        "status": "stubbed",
        "filename": file.filename,
        "contentType": file.content_type,
        "size": len(content),
        "objectKey": None,
    }
