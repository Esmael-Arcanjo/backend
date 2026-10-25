from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import decode_token
from app.modules.auth.schema import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])
service = AuthService()


def _set_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none",
                        max_age=settings.ACCESS_TOKEN_MINUTES * 60, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none",
                        max_age=settings.REFRESH_TOKEN_DAYS * 86400, path="/")


@router.post("/register")
async def register(payload: RegisterRequest, response: Response):
    user = await service.register(payload)
    access, refresh = service.tokens(user)
    _set_cookies(response, access, refresh)
    # Real welcome email via LEAMSE Email API (best-effort, non-blocking on failure).
    try:
        from app.modules.email.internal import send_internal
        await send_internal(user["email"], "welcome",
                            {"name": user.get("name", ""), "service": payload.service},
                            organization_id=user.get("organization_id"))
    except Exception:
        pass
    return {**user, "access_token": access}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    payload = service._public(user)
    if user.get("organization_id"):
        from app.core.database import db
        from app.core.mongo import oid
        org = await db.organizations.find_one({"_id": oid(user["organization_id"])})
        payload["payment_required"] = bool(org and org.get("payment_pending"))
    else:
        payload["payment_required"] = False
    return payload


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    user = await service.login(payload, ip)
    # Block login if the org still needs to pay for its subscription service.
    if user.get("organization_id"):
        from app.core.database import db
        from app.core.mongo import oid
        org = await db.organizations.find_one({"_id": oid(user["organization_id"])})
        if org and org.get("payment_pending"):
            raise HTTPException(status_code=402,
                                detail="Pagamento pendente. Conclua o pagamento para acessar sua conta.")
    access, refresh = service.tokens(user)
    _set_cookies(response, access, refresh)
    return {**user, "access_token": access, "payment_required": False}


@router.post("/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"status": "ok"}


@router.post("/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = await service.users.get(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access, new_refresh = service.tokens(service._public(user))
    _set_cookies(response, access, new_refresh)
    return {"status": "ok", "access_token": access}


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest):
    token = await service.forgot_password(payload.email)
    print(f"[LEAMSE] password reset link: /reset-password?token={token}")
    return {"status": "ok"}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest):
    await service.reset_password(payload.token, payload.password)
    return {"status": "ok"}
