from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request

from app.core.database import db
from app.core.mongo import now_utc, oid
from app.core.security import decode_token, sha256

RATE_LIMIT_PER_MINUTE = 600


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = await db.users.find_one({"_id": oid(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    user["id"] = str(user.pop("_id"))
    user.pop("password_hash", None)
    return user


async def get_current_org(user: dict = Depends(get_current_user)) -> dict:
    org = await db.organizations.find_one({"_id": oid(user.get("organization_id", ""))})
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    org["id"] = str(org.pop("_id"))
    return org


async def get_project(project_id: str, org: dict = Depends(get_current_org)) -> dict:
    project = await db.projects.find_one({"_id": oid(project_id), "organization_id": org["id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["id"] = str(project.pop("_id"))
    return project


# Every /api/dashboard/* route must depend on this so the project_id query param
# is validated against the caller's organization (tenant isolation).
project_scope = get_project


async def assert_project_owned(project_id: str, org_id: str) -> dict:
    project = await db.projects.find_one({"_id": oid(project_id), "organization_id": org_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["id"] = str(project.pop("_id"))
    return project


def require_role(*roles: str):
    async def checker(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return checker


async def _rate_limit(key_id: str) -> None:
    minute = now_utc().strftime("%Y%m%d%H%M")
    doc = await db.rate_limits.find_one_and_update(
        {"key_id": key_id, "minute": minute},
        {"$inc": {"count": 1}},
        upsert=True,
        return_document=True,
    )
    if doc and doc.get("count", 0) > RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


class ApiContext:
    def __init__(self, api_key: dict, project: dict) -> None:
        self.api_key = api_key
        self.project = project
        self.project_id = project["id"]
        self.mode = project.get("mode", "test")
        self.scopes: list[str] = api_key.get("scopes", [])
        self.modules: list[str] = project.get("modules", [])

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")

    def require_module(self, module: str) -> None:
        if module not in self.modules:
            raise HTTPException(status_code=403, detail=f"Module not enabled for this project: {module}")


async def api_key_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> ApiContext:
    raw = x_api_key
    if not raw and authorization and authorization.startswith("Bearer "):
        raw = authorization[7:]
    if not raw:
        raise HTTPException(status_code=401, detail="Missing API key")
    key = await db.api_keys.find_one({"secret_hash": sha256(raw), "revoked": False})
    if not key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    key["id"] = str(key.pop("_id"))
    await _rate_limit(key["id"])
    project = await db.projects.find_one({"_id": oid(key["project_id"])})
    if not project:
        raise HTTPException(status_code=401, detail="Project not found for API key")
    project["id"] = str(project.pop("_id"))
    await db.api_keys.update_one({"_id": oid(key["id"])}, {"$set": {"last_used_at": now_utc()}})
    await db.audit_logs.insert_one(
        {
            "organization_id": project["organization_id"],
            "project_id": project["id"],
            "api_key_id": key["id"],
            "action": f"{request.method} {request.url.path}",
            "created_at": now_utc(),
        }
    )
    return ApiContext(key, project)


def scope_guard(scope: str, module: str):
    async def dep(ctx: ApiContext = Depends(api_key_auth)) -> ApiContext:
        ctx.require_module(module)
        ctx.require_scope(scope)
        return ctx

    return dep
