from bson import ObjectId
from fastapi import HTTPException, Request

from app.core.security.tokens import decode_jwt
from app.database.mongo import db


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token", "")
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    payload = decode_jwt(token, "access")
    sid, sub = payload.get("sid", ""), payload.get("sub", "")
    if not ObjectId.is_valid(sid) or not ObjectId.is_valid(sub):
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
    session = await db.sessions.find_one({"_id": ObjectId(sid), "user_id": ObjectId(sub), "revoked_at": None})
    if not session:
        raise HTTPException(status_code=401, detail="Sessão revogada ou expirada")
    user = await db.users.find_one({"_id": ObjectId(sub)})
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=403, detail="Conta indisponível")
    request.state.user = user
    request.state.session = session
    return user
