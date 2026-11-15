from datetime import timedelta
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException, Request, Response

from app.core.config.settings import settings
from app.core.security.rate_limit import client_ip
from app.core.security.tokens import create_jwt, hash_token, new_token
from app.database.mongo import db
from app.integrations.email.sender import send_email
from app.shared.models import utcnow

MAX_FAILED = 5
LOCK_MINUTES = 15


def _cookie(response: Response, name: str, value: str, max_age: int, path: str, http_only: bool = True):
    response.set_cookie(name, value, max_age=max_age, path=path, httponly=http_only, domain=settings.cookie_domain,
                        secure=settings.cookie_secure, samesite="lax")


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    _cookie(response, "access_token", access, settings.access_ttl_min * 60, "/api")
    _cookie(response, "refresh_token", refresh, settings.refresh_ttl_days * 86400, "/api/v1/auth")
    _cookie(response, "csrf_token", new_token(), settings.refresh_ttl_days * 86400, "/", http_only=False)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/api", domain=settings.cookie_domain)
    response.delete_cookie("refresh_token", path="/api/v1/auth", domain=settings.cookie_domain)
    response.delete_cookie("csrf_token", path="/", domain=settings.cookie_domain)


async def start_session(user: dict, request: Request, response: Response) -> None:
    refresh = new_token()
    now = utcnow()
    result = await db.sessions.insert_one({
        "user_id": user["_id"], "refresh_hash": hash_token(refresh), "prev_refresh_hash": None,
        "user_agent": request.headers.get("user-agent", "")[:300], "ip": client_ip(request),
        "created_at": now, "last_used_at": now,
        "expires_at": now + timedelta(days=settings.refresh_ttl_days), "revoked_at": None,
    })
    access = create_jwt(str(user["_id"]), "access", settings.access_ttl_min, sid=str(result.inserted_id))
    set_auth_cookies(response, access, refresh)
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now, "failed_logins": 0,
                                                              "locked_until": None}})


async def rotate_session(refresh: str, response: Response) -> dict:
    h = hash_token(refresh)
    session = await db.sessions.find_one({"refresh_hash": h, "revoked_at": None})
    if not session:
        reused = await db.sessions.find_one({"prev_refresh_hash": h, "revoked_at": None})
        if reused:
            await db.sessions.update_one({"_id": reused["_id"]}, {"$set": {"revoked_at": utcnow(),
                                                                         "revoked_reason": "refresh_reuse"}})
        raise HTTPException(status_code=401, detail="Sessão expirada")
    if session["expires_at"] <= utcnow():
        raise HTTPException(status_code=401, detail="Sessão expirada")
    new_refresh = new_token()
    await db.sessions.update_one({"_id": session["_id"], "refresh_hash": h},
                                 {"$set": {"refresh_hash": hash_token(new_refresh), "prev_refresh_hash": h,
                                           "last_used_at": utcnow()}})
    access = create_jwt(str(session["user_id"]), "access", settings.access_ttl_min, sid=str(session["_id"]))
    set_auth_cookies(response, access, new_refresh)
    return session


async def revoke_sessions(user_id: ObjectId, except_id: Optional[ObjectId] = None, reason: str = "user") -> int:
    query = {"user_id": user_id, "revoked_at": None}
    if except_id:
        query["_id"] = {"$ne": except_id}
    result = await db.sessions.update_many(query, {"$set": {"revoked_at": utcnow(), "revoked_reason": reason}})
    return result.modified_count


async def register_failed_login(user: dict) -> None:
    failed = user.get("failed_logins", 0) + 1
    update = {"failed_logins": failed}
    if failed >= MAX_FAILED:
        update["locked_until"] = utcnow() + timedelta(minutes=LOCK_MINUTES)
        update["failed_logins"] = 0
    await db.users.update_one({"_id": user["_id"]}, {"$set": update})


async def issue_email_token(user: dict, purpose: str, hours: int) -> str:
    token = new_token()
    await db.email_tokens.delete_many({"user_id": user["_id"], "purpose": purpose})
    await db.email_tokens.insert_one({"user_id": user["_id"], "purpose": purpose, "token_hash": hash_token(token),
                                      "expires_at": utcnow() + timedelta(hours=hours), "created_at": utcnow()})
    return token


async def consume_email_token(token: str, purpose: str) -> dict:
    doc = await db.email_tokens.find_one_and_delete({"token_hash": hash_token(token), "purpose": purpose})
    if not doc or doc["expires_at"] <= utcnow():
        raise HTTPException(status_code=400, detail="Link inválido ou expirado")
    user = await db.users.find_one({"_id": doc["user_id"]})
    if not user:
        raise HTTPException(status_code=400, detail="Link inválido ou expirado")
    return user


async def send_verification(user: dict) -> None:
    token = await issue_email_token(user, "verify_email", 24)
    link = f"{settings.public_app_url}/verificar-email?token={token}"
    await send_email(user["email"], "Confirme seu e-mail — LEAMSE",
                     f"Olá, {user['name']}!\n\nConfirme seu e-mail acessando: {link}\n\nO link expira em 24 horas.",
                     "verify_email")


async def send_password_reset(user: dict) -> None:
    token = await issue_email_token(user, "reset_password", 1)
    link = f"{settings.public_app_url}/redefinir-senha?token={token}"
    await send_email(user["email"], "Redefinição de senha — LEAMSE",
                     f"Olá, {user['name']}!\n\nPara redefinir sua senha acesse: {link}\n\nO link expira em 1 hora. "
                     "Se você não solicitou, ignore este e-mail.", "reset_password")
