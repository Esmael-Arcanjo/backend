from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.database import db
from app.core.deps import require_role
from app.core.mongo import oid
from app.modules.subscriptions.schema import PricingUpdate
from app.modules.subscriptions.service import SubscriptionService, get_pricing, set_pricing

router = APIRouter(prefix="/admin", tags=["Admin"])
subs = SubscriptionService()


def _serialize(doc: dict) -> dict:
    if not doc:
        return doc
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


@router.get("/stats")
async def stats(_: dict = Depends(require_role("admin"))):
    total_users = await db.users.count_documents({})
    banned = await db.users.count_documents({"banned": True})
    total_orgs = await db.organizations.count_documents({})
    active_subs = await db.subscriptions.count_documents({"status": "active"})
    total_payments = await db.charges.count_documents({}) if "charges" in await db.list_collection_names() else 0
    return {
        "total_users": total_users,
        "banned_users": banned,
        "total_organizations": total_orgs,
        "active_subscriptions": active_subs,
        "total_payments": total_payments,
    }


@router.get("/users")
async def list_users(_: dict = Depends(require_role("admin"))):
    users = await db.users.find({}, limit=500).to_list(500)
    result = []
    for u in users:
        u = _serialize(u)
        org = None
        sub = None
        if u.get("organization_id"):
            org_doc = await db.organizations.find_one({"_id": oid(u["organization_id"])})
            if org_doc:
                org = _serialize(org_doc)
            sub_doc = await db.subscriptions.find_one(
                {"organization_id": u["organization_id"], "status": {"$ne": "canceled"}}
            )
            if sub_doc:
                sub = _serialize(sub_doc)
        u["organization"] = org
        u["subscription"] = sub
        result.append(u)
    return result


@router.post("/users/{user_id}/ban")
async def ban_user(user_id: str, _: dict = Depends(require_role("admin"))):
    r = await db.users.update_one({"_id": oid(user_id)}, {"$set": {"banned": True}})
    if r.matched_count == 0:
        raise HTTPException(404, "User not found")
    return {"status": "banned"}


@router.post("/users/{user_id}/unban")
async def unban_user(user_id: str, _: dict = Depends(require_role("admin"))):
    r = await db.users.update_one({"_id": oid(user_id)}, {"$set": {"banned": False}})
    if r.matched_count == 0:
        raise HTTPException(404, "User not found")
    return {"status": "unbanned"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, _: dict = Depends(require_role("admin"))):
    user = await db.users.find_one({"_id": oid(user_id)})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("role") == "admin":
        raise HTTPException(400, "Cannot delete an admin account")
    org_id = user.get("organization_id")
    await db.users.delete_one({"_id": oid(user_id)})
    if org_id:
        await db.organizations.delete_one({"_id": oid(org_id)})
        await db.subscriptions.delete_many({"organization_id": org_id})
    return {"status": "deleted"}


class GrantRequest(BaseModel):
    days: int = Field(30, ge=1, le=3650)
    service: str = "email"


@router.post("/users/{user_id}/grant")
async def grant_plan(user_id: str, payload: GrantRequest, _: dict = Depends(require_role("admin"))):
    user = await db.users.find_one({"_id": oid(user_id)})
    if not user or not user.get("organization_id"):
        raise HTTPException(404, "User or organization not found")
    sub = await subs.grant_free(user["organization_id"], payload.service, payload.days)
    return _serialize(sub)


@router.get("/pricing")
async def get_admin_pricing(_: dict = Depends(require_role("admin"))):
    return await get_pricing()


@router.patch("/pricing")
async def update_pricing(payload: PricingUpdate, _: dict = Depends(require_role("admin"))):
    current = await get_pricing()
    entry = dict(current.get(payload.service, {}))
    if payload.monthly is not None:
        entry["monthly"] = payload.monthly
    if payload.yearly is not None:
        entry["yearly"] = payload.yearly
    if payload.currency:
        entry["currency"] = payload.currency.upper()
    if not entry.get("model"):
        entry["model"] = "subscription"
    updated = await set_pricing({payload.service: entry})
    return updated
