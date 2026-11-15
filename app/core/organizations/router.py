from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import EmailStr, Field

from app.core.audit.service import audit
from app.core.authentication.deps import get_current_user
from app.core.authorization.deps import ROLES, resolve_product_context
from app.core.config.settings import settings
from app.core.security.rate_limit import rate_limit
from app.core.security.tokens import hash_token, new_token
from app.database.mongo import db
from app.integrations.email.sender import send_email
from app.shared.models import StrictInput, to_oid, utcnow

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])
ASSIGNABLE = [r for r in ROLES if r != "owner"]


class InviteIn(StrictInput):
    email: EmailStr
    role: str = Field(pattern=r"^(admin|member|viewer)$")


class RoleIn(StrictInput):
    role: str = Field(pattern=r"^(admin|member|viewer)$")


class AcceptIn(StrictInput):
    token: str = Field(min_length=10, max_length=200)


@router.get("/{product_key}/members")
async def list_members(product_key: str, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "read")
    grants = await db.product_permissions.find({"organization_id": ctx.org_id, "product_key": product_key}).to_list(500)
    users = {u["_id"]: u for u in await db.users.find({"_id": {"$in": [g["user_id"] for g in grants]}}).to_list(500)}
    invites = await db.organization_invites.find({"organization_id": ctx.org_id, "product_key": product_key,
                                                  "accepted_at": None}).to_list(100)
    return {"members": [{"user_id": str(g["user_id"]), "name": users[g["user_id"]]["name"],
                         "email": users[g["user_id"]]["email"], "role": g["role"]}
                        for g in grants if g["user_id"] in users],
            "invites": [{"id": str(i["_id"]), "email": i["email"], "role": i["role"],
                         "expires_at": i["expires_at"].isoformat()} for i in invites],
            "assignable_roles": ASSIGNABLE, "my_role": ctx.role}


@router.post("/{product_key}/invites", dependencies=[rate_limit("invite", 30, 3600)])
async def invite(product_key: str, body: InviteIn, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "manage")
    email = body.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing and await db.product_permissions.find_one({"organization_id": ctx.org_id, "user_id": existing["_id"],
                                                           "product_key": product_key}):
        raise HTTPException(status_code=409, detail="Usuário já possui acesso")
    token = new_token()
    await db.organization_invites.insert_one({
        "organization_id": ctx.org_id, "product_key": product_key, "email": email, "role": body.role,
        "token_hash": hash_token(token), "invited_by": user["_id"], "accepted_at": None,
        "expires_at": utcnow() + timedelta(days=7), "created_at": utcnow()})
    link = f"{settings.public_app_url}/convite?token={token}"
    await send_email(email, f"Convite para {ctx.organization['name']} — LEAMSE",
                     f"{user['name']} convidou você para acessar a organização {ctx.organization['name']}.\n"
                     f"Aceite em: {link}\n\nO convite expira em 7 dias.", "invite")
    await audit("organization.invite_sent", user_id=user["_id"], organization_id=ctx.org_id, product_key=product_key,
                metadata={"email": email, "role": body.role}, request=request)
    return {"ok": True}


@router.delete("/{product_key}/invites/{invite_id}")
async def cancel_invite(product_key: str, invite_id: str, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "manage")
    result = await db.organization_invites.delete_one({"_id": to_oid(invite_id), "organization_id": ctx.org_id,
                                                       "product_key": product_key, "accepted_at": None})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    return {"ok": True}


@router.patch("/{product_key}/members/{member_id}")
async def change_role(product_key: str, member_id: str, body: RoleIn, request: Request,
                      user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "manage")
    uid = to_oid(member_id)
    grant = await db.product_permissions.find_one({"organization_id": ctx.org_id, "user_id": uid,
                                                   "product_key": product_key})
    if not grant:
        raise HTTPException(status_code=404, detail="Membro não encontrado")
    if grant["role"] == "owner" or uid == user["_id"]:
        raise HTTPException(status_code=403, detail="Não é possível alterar este papel")
    if ctx.role == "admin" and grant["role"] == "admin":
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    await db.product_permissions.update_one({"_id": grant["_id"]}, {"$set": {"role": body.role}})
    await audit("organization.role_changed", user_id=user["_id"], organization_id=ctx.org_id, product_key=product_key,
                target_id=member_id, metadata={"role": body.role}, request=request)
    return {"ok": True}


@router.delete("/{product_key}/members/{member_id}")
async def remove_member(product_key: str, member_id: str, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "manage")
    uid = to_oid(member_id)
    grant = await db.product_permissions.find_one({"organization_id": ctx.org_id, "user_id": uid,
                                                   "product_key": product_key})
    if not grant:
        raise HTTPException(status_code=404, detail="Membro não encontrado")
    if grant["role"] == "owner" or uid == user["_id"]:
        raise HTTPException(status_code=403, detail="Não é possível remover este membro")
    await db.product_permissions.delete_one({"_id": grant["_id"]})
    await audit("organization.member_removed", user_id=user["_id"], organization_id=ctx.org_id,
                product_key=product_key, target_id=member_id, request=request)
    return {"ok": True}


@router.post("/invites/accept", dependencies=[rate_limit("invite-accept", 20, 3600)])
async def accept_invite(body: AcceptIn, request: Request, user: dict = Depends(get_current_user)):
    inv = await db.organization_invites.find_one({"token_hash": hash_token(body.token), "accepted_at": None})
    if not inv or inv["expires_at"] <= utcnow():
        raise HTTPException(status_code=400, detail="Convite inválido ou expirado")
    if inv["email"] != user["email"]:
        raise HTTPException(status_code=403, detail="Este convite foi enviado para outro e-mail")
    now = utcnow()
    await db.organization_members.update_one({"organization_id": inv["organization_id"], "user_id": user["_id"]},
                                             {"$setOnInsert": {"role": "member", "status": "active", "created_at": now}},
                                             upsert=True)
    await db.product_permissions.update_one(
        {"organization_id": inv["organization_id"], "user_id": user["_id"], "product_key": inv["product_key"]},
        {"$set": {"role": inv["role"], "updated_at": now}, "$setOnInsert": {"created_at": now}}, upsert=True)
    await db.organization_invites.update_one({"_id": inv["_id"]}, {"$set": {"accepted_at": now}})
    product = await db.products.find_one({"key": inv["product_key"]})
    await audit("organization.invite_accepted", user_id=user["_id"], organization_id=inv["organization_id"],
                product_key=inv["product_key"], request=request)
    return {"ok": True, "slug": product["slug"]}
