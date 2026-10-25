"""Image uploads go straight from the browser to Cloudinary using a backend-signed request."""
import os
import time

import cloudinary
import cloudinary.utils
from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user

router = APIRouter(prefix="/storage", tags=["Storage"])

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)


@router.get("/cloudinary/signature")
async def cloudinary_signature(user: dict = Depends(get_current_user)):
    """Signed params for a direct browser → Cloudinary image upload into the user's own folder."""
    secret = os.environ.get("CLOUDINARY_API_SECRET")
    if not secret:
        raise HTTPException(503, "Upload de imagens indisponível")
    timestamp = int(time.time())
    folder = f"users/{user['id']}/images"
    signature = cloudinary.utils.api_sign_request({"timestamp": timestamp, "folder": folder}, secret)
    return {
        "signature": signature,
        "timestamp": timestamp,
        "folder": folder,
        "cloud_name": os.environ.get("CLOUDINARY_CLOUD_NAME"),
        "api_key": os.environ.get("CLOUDINARY_API_KEY"),
    }
