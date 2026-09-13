"""Backend upload/download for user avatars, covers, product images, etc.
Files are stored in Emergent Object Storage and served through this backend
so the same JWT protects both write and read."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from app.core.database import db
from app.core.deps import get_current_user
from app.modules.storage.service import APP_NAME, get_object, put_object

router = APIRouter(prefix="/storage", tags=["Storage"])

MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "gif": "image/gif", "webp": "image/webp"}


@router.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Upload any image. Returns { id, url } — save `url` in your record."""
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    ext = ext if ext in MIME else "bin"
    content_type = file.content_type or MIME.get(ext, "application/octet-stream")
    file_id = uuid.uuid4().hex
    path = f"{APP_NAME}/uploads/{user['id']}/{file_id}.{ext}"
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Arquivo maior que 8MB")
    try:
        result = put_object(path, data, content_type)
    except Exception as e:
        raise HTTPException(502, f"Falha no upload: {e}")
    await db.files.insert_one({
        "id": file_id,
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result["size"],
        "user_id": user["id"],
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"id": file_id, "url": f"/api/storage/files/{file_id}"}


@router.get("/files/{file_id}")
async def download(file_id: str):
    """Public download endpoint — files uploaded here are meant to be embedded
    in bio pages, product images, etc. Access control lives in the referring app."""
    record = await db.files.find_one({"id": file_id, "is_deleted": False})
    if not record:
        raise HTTPException(404, "Arquivo não encontrado")
    try:
        data, content_type = get_object(record["storage_path"])
    except Exception:
        raise HTTPException(502, "Falha ao carregar arquivo")
    return Response(content=data,
                    media_type=record.get("content_type") or content_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
