from dataclasses import dataclass

from bson import ObjectId
from fastapi import Depends, HTTPException, Request

from app.core.authentication.deps import get_current_user
from app.core.security.rate_limit import enforce
from app.database.mongo import db

ROLE_PERMISSIONS = {
    "owner": {"read", "write", "delete", "manage", "billing"},
    "admin": {"read", "write", "delete", "manage"},
    "member": {"read", "write"},
    "viewer": {"read"},
}
ROLES = list(ROLE_PERMISSIONS.keys())
MFA_REQUIRED_PERMISSIONS = {"manage", "billing"}
VALID_SUBSCRIPTION = {"active", "past_due"}


@dataclass
class ProductContext:
    user: dict
    organization: dict
    subscription: dict
    role: str
    product_key: str

    @property
    def org_id(self) -> ObjectId:
        return self.organization["_id"]

    @property
    def user_id(self) -> ObjectId:
        return self.user["_id"]


async def resolve_product_context(request: Request, user: dict, product_key: str, permission: str) -> ProductContext:
    raw = request.headers.get("x-organization-id", "")
    if not ObjectId.is_valid(raw):
        raise HTTPException(status_code=400, detail="Organização ativa não informada")
    org_id = ObjectId(raw)
    member = await db.organization_members.find_one({"organization_id": org_id, "user_id": user["_id"],
                                                     "status": "active"})
    organization = await db.organizations.find_one({"_id": org_id, "status": "active"})
    if not member or not organization:
        raise HTTPException(status_code=403, detail="Sem acesso a esta organização")
    grant = await db.product_permissions.find_one({"organization_id": org_id, "user_id": user["_id"],
                                                   "product_key": product_key})
    if not grant:
        raise HTTPException(status_code=403, detail="Sem acesso a este produto")
    subscription = await db.subscriptions.find_one({"organization_id": org_id, "product_key": product_key,
                                                    "is_current": True})
    if not subscription or subscription["status"] not in VALID_SUBSCRIPTION:
        raise HTTPException(status_code=402, detail="Assinatura do produto inativa")
    if subscription["status"] == "past_due" and permission not in {"read", "billing"}:
        raise HTTPException(status_code=402, detail="Pagamento pendente: acesso somente leitura")
    role = grant["role"]
    if permission not in ROLE_PERMISSIONS.get(role, set()):
        raise HTTPException(status_code=403, detail="Permissão insuficiente")
    if permission in MFA_REQUIRED_PERMISSIONS and not user.get("mfa_enabled"):
        raise HTTPException(status_code=403, detail="Ative a autenticação em dois fatores (MFA) para ações administrativas")
    await enforce(f"org:{org_id}:{product_key}", 1200, 60)
    await enforce(f"user:{user['_id']}", 600, 60)
    return ProductContext(user=user, organization=organization, subscription=subscription, role=role,
                          product_key=product_key)


def require_product(product_key: str, permission: str = "read"):
    async def dependency(request: Request, user: dict = Depends(get_current_user)) -> ProductContext:
        return await resolve_product_context(request, user, product_key, permission)
    return dependency
