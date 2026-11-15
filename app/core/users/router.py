from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.audit.service import audit
from app.core.authentication.deps import get_current_user
from app.core.authentication.schemas import ChangePasswordIn
from app.core.authentication.service import revoke_sessions
from app.core.security.crypto import decrypt, encrypt, new_totp_secret, totp_uri, verify_totp
from app.core.security.passwords import hash_password, verify_password
from app.core.security.rate_limit import enforce
from app.core.users.schemas import MfaCodeIn, MfaDisableIn, NotificationPrefsIn, ProfileIn, user_out
from app.database.mongo import db
from app.shared.models import to_oid, utcnow

router = APIRouter(prefix="/api/v1/users/me", tags=["users"])


@router.patch("")
async def update_profile(body: ProfileIn, request: Request, user: dict = Depends(get_current_user)):
    await db.users.update_one({"_id": user["_id"]}, {"$set": {**body.model_dump(), "updated_at": utcnow()}})
    await audit("user.profile_updated", user_id=user["_id"], request=request)
    return {"user": user_out(await db.users.find_one({"_id": user["_id"]}))}


@router.put("/notification-preferences")
async def update_prefs(body: NotificationPrefsIn, user: dict = Depends(get_current_user)):
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"notification_prefs": body.model_dump()}})
    return {"notification_prefs": body.model_dump()}


@router.post("/password")
async def change_password(body: ChangePasswordIn, request: Request, user: dict = Depends(get_current_user)):
    await enforce(f"pwd-change:{user['_id']}", 5, 900)
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.new_password),
                                                              "updated_at": utcnow()}})
    revoked = await revoke_sessions(user["_id"], except_id=request.state.session["_id"], reason="password_change")
    await audit("user.password_changed", user_id=user["_id"], request=request)
    return {"ok": True, "revoked_sessions": revoked}


@router.post("/mfa/setup")
async def mfa_setup(user: dict = Depends(get_current_user)):
    if user.get("mfa_enabled"):
        raise HTTPException(status_code=400, detail="MFA já está ativo")
    secret = new_totp_secret()
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"mfa_pending_secret": encrypt(secret)}})
    return {"secret": secret, "otpauth_uri": totp_uri(secret, user["email"])}


@router.post("/mfa/enable")
async def mfa_enable(body: MfaCodeIn, request: Request, user: dict = Depends(get_current_user)):
    await enforce(f"mfa-enable:{user['_id']}", 10, 900)
    pending = user.get("mfa_pending_secret")
    if not pending or not verify_totp(decrypt(pending), body.code):
        raise HTTPException(status_code=400, detail="Código inválido")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"mfa_enabled": True, "mfa_secret": pending},
                                                     "$unset": {"mfa_pending_secret": ""}})
    await audit("user.mfa_enabled", user_id=user["_id"], request=request)
    return {"ok": True}


@router.post("/mfa/disable")
async def mfa_disable(body: MfaDisableIn, request: Request, user: dict = Depends(get_current_user)):
    await enforce(f"mfa-disable:{user['_id']}", 5, 900)
    if not user.get("mfa_enabled"):
        raise HTTPException(status_code=400, detail="MFA não está ativo")
    if not verify_password(body.password, user["password_hash"]) or \
            not verify_totp(decrypt(user["mfa_secret"]), body.code):
        raise HTTPException(status_code=400, detail="Senha ou código inválido")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"mfa_enabled": False, "mfa_secret": None}})
    await audit("user.mfa_disabled", user_id=user["_id"], request=request)
    return {"ok": True}


@router.get("/sessions")
async def list_sessions(request: Request, user: dict = Depends(get_current_user)):
    docs = await db.sessions.find({"user_id": user["_id"], "revoked_at": None}).sort("last_used_at", -1).to_list(50)
    current = request.state.session["_id"]
    return {"sessions": [{"id": str(d["_id"]), "user_agent": d.get("user_agent"), "ip": d.get("ip"),
                          "created_at": d["created_at"].isoformat(), "last_used_at": d["last_used_at"].isoformat(),
                          "current": d["_id"] == current} for d in docs]}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, request: Request, user: dict = Depends(get_current_user)):
    result = await db.sessions.update_one({"_id": to_oid(session_id), "user_id": user["_id"], "revoked_at": None},
                                          {"$set": {"revoked_at": utcnow(), "revoked_reason": "user"}})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    await audit("user.session_revoked", user_id=user["_id"], target_id=session_id, request=request)
    return {"ok": True}


@router.post("/sessions/revoke-others")
async def revoke_others(request: Request, user: dict = Depends(get_current_user)):
    count = await revoke_sessions(user["_id"], except_id=request.state.session["_id"])
    await audit("user.sessions_revoked", user_id=user["_id"], metadata={"count": count}, request=request)
    return {"revoked": count}


@router.get("/notifications")
async def list_notifications(product_key: Optional[str] = None, user: dict = Depends(get_current_user)):
    query: dict = {"user_id": user["_id"]}
    if product_key:
        query["product_key"] = {"$in": [product_key, None]}
    docs = await db.notifications.find(query).sort("created_at", -1).to_list(100)
    return {"notifications": [{"id": str(d["_id"]), "title": d["title"], "body": d.get("body", ""),
                               "product_key": d.get("product_key"), "read": d.get("read_at") is not None,
                               "created_at": d["created_at"].isoformat()} for d in docs]}


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, user: dict = Depends(get_current_user)):
    result = await db.notifications.update_one({"_id": to_oid(notification_id), "user_id": user["_id"]},
                                               {"$set": {"read_at": utcnow()}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notificação não encontrada")
    return {"ok": True}


async def notify(user_id: ObjectId, title: str, body: str, product_key: Optional[str] = None,
                 organization_id: Optional[ObjectId] = None) -> None:
    await db.notifications.insert_one({"user_id": user_id, "organization_id": organization_id,
                                       "product_key": product_key, "title": title, "body": body,
                                       "read_at": None, "created_at": utcnow()})
