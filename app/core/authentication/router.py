from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError

from app.core.audit.service import audit
from app.core.authentication import service as svc
from app.core.authentication.deps import get_current_user
from app.core.authentication.schemas import EmailIn, LoginIn, MfaLoginIn, RegisterIn, ResetPasswordIn, TokenIn
from app.core.security.crypto import decrypt, verify_totp
from app.core.security.passwords import hash_password, needs_rehash, verify_password
from app.core.security.rate_limit import enforce, rate_limit
from app.core.security.tokens import create_jwt, decode_jwt
from app.core.users.schemas import user_out
from app.database.mongo import db
from app.shared.models import to_oid, utcnow

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
GENERIC_LOGIN_ERROR = "E-mail ou senha inválidos"


@router.post("/register", dependencies=[rate_limit("register", 10, 3600)])
async def register(body: RegisterIn, request: Request, response: Response):
    now = utcnow()
    user = {"name": body.name, "email": body.email.lower(), "document": body.document,
            "password_hash": hash_password(body.password),
            "email_verified": False, "mfa_enabled": False, "mfa_secret": None, "status": "active",
            "failed_logins": 0, "locked_until": None, "locale": "pt-BR", "timezone": "America/Sao_Paulo",
            "phone": None, "notification_prefs": {"email_billing": True, "email_security": True,
                                                  "email_product": True},
            "created_at": now, "updated_at": now}
    try:
        result = await db.users.insert_one(user)
    except DuplicateKeyError as e:
        if "document" in str(e):
            raise HTTPException(status_code=409, detail="Já existe uma conta com este CPF/CNPJ")
        raise HTTPException(status_code=409, detail="Já existe uma conta com este e-mail")
    user["_id"] = result.inserted_id
    await svc.send_verification(user)
    await svc.start_session(user, request, response)
    await audit("auth.register", user_id=user["_id"], request=request)
    return {"user": user_out(user)}


@router.post("/login", dependencies=[rate_limit("login", 20, 300)])
async def login(body: LoginIn, request: Request, response: Response):
    email = body.email.lower()
    await enforce(f"login-email:{email}", 10, 300)
    user = await db.users.find_one({"email": email})
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)
    if user.get("locked_until") and user["locked_until"] > utcnow():
        raise HTTPException(status_code=423, detail="Conta temporariamente bloqueada por tentativas inválidas. "
                                                    "Tente novamente em 15 minutos.")
    if not verify_password(body.password, user["password_hash"]):
        await svc.register_failed_login(user)
        await audit("auth.login_failed", user_id=user["_id"], request=request)
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)
    if needs_rehash(user["password_hash"]):
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.password)}})
    if user.get("mfa_enabled"):
        return {"mfa_required": True, "mfa_token": create_jwt(str(user["_id"]), "mfa", 5)}
    await svc.start_session(user, request, response)
    await audit("auth.login", user_id=user["_id"], request=request)
    return {"mfa_required": False, "user": user_out(user)}


@router.post("/login/mfa", dependencies=[rate_limit("login-mfa", 10, 300)])
async def login_mfa(body: MfaLoginIn, request: Request, response: Response):
    payload = decode_jwt(body.mfa_token, "mfa")
    user = await db.users.find_one({"_id": to_oid(payload["sub"])})
    if not user or not user.get("mfa_enabled") or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="Código inválido")
    await enforce(f"mfa-user:{user['_id']}", 5, 300)
    if not verify_totp(decrypt(user["mfa_secret"]), body.code):
        await audit("auth.mfa_failed", user_id=user["_id"], request=request)
        raise HTTPException(status_code=401, detail="Código inválido")
    await svc.start_session(user, request, response)
    await audit("auth.login", user_id=user["_id"], metadata={"mfa": True}, request=request)
    return {"user": user_out(user)}


@router.post("/refresh", dependencies=[rate_limit("refresh", 60, 60)])
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    try:
        if not token:
            raise HTTPException(status_code=401, detail="Sessão expirada")
        await svc.rotate_session(token, response)
    except HTTPException as e:
        expired = JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        svc.clear_auth_cookies(expired)
        return expired
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response, user: dict = Depends(get_current_user)):
    await db.sessions.update_one({"_id": request.state.session["_id"]},
                                 {"$set": {"revoked_at": utcnow(), "revoked_reason": "logout"}})
    svc.clear_auth_cookies(response)
    await audit("auth.logout", user_id=user["_id"], request=request)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"user": user_out(user)}


@router.get("/csrf")
async def csrf(request: Request):
    """Lets a frontend on another subdomain read the CSRF token it cannot see in document.cookie."""
    return {"csrf_token": request.cookies.get("csrf_token")}


@router.post("/verify-email", dependencies=[rate_limit("verify", 20, 3600)])
async def verify_email(body: TokenIn, request: Request):
    user = await svc.consume_email_token(body.token, "verify_email")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"email_verified": True, "updated_at": utcnow()}})
    await audit("auth.email_verified", user_id=user["_id"], request=request)
    return {"ok": True}


@router.post("/resend-verification", dependencies=[rate_limit("resend", 5, 3600)])
async def resend_verification(user: dict = Depends(get_current_user)):
    if user.get("email_verified"):
        return {"ok": True}
    await svc.send_verification(user)
    return {"ok": True}


@router.post("/forgot-password", dependencies=[rate_limit("forgot", 5, 3600)])
async def forgot_password(body: EmailIn, request: Request):
    user = await db.users.find_one({"email": body.email.lower(), "status": "active"})
    if user:
        await svc.send_password_reset(user)
        await audit("auth.password_reset_requested", user_id=user["_id"], request=request)
    return {"ok": True, "message": "Se o e-mail estiver cadastrado, enviaremos instruções."}


@router.post("/reset-password", dependencies=[rate_limit("reset", 10, 3600)])
async def reset_password(body: ResetPasswordIn, request: Request):
    user = await svc.consume_email_token(body.token, "reset_password")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(body.password),
                                                              "failed_logins": 0, "locked_until": None,
                                                              "updated_at": utcnow()}})
    await svc.revoke_sessions(user["_id"], reason="password_reset")
    await audit("auth.password_reset", user_id=user["_id"], request=request)
    return {"ok": True}
