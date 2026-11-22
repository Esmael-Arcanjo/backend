import logging
import re
import time
from datetime import timedelta
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import EmailStr, Field

from app.core.audit.service import audit
from app.core.authentication.deps import get_current_user
from app.core.users.schemas import is_platform_admin
from app.database.mongo import db
from app.shared.models import StrictInput, to_oid, utcnow

logger = logging.getLogger("admin")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
ACTIVE = ["active", "trialing", "past_due"]


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not is_platform_admin(user):
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    return user


class GrantIn(StrictInput):
    email: EmailStr
    product_key: str = Field(max_length=40)
    days: int = Field(ge=1, le=3650)
    segment: Optional[str] = Field(default=None, max_length=40)


def _monthly(sub: dict) -> float:
    cents = sub.get("price_cents", 0) or 0
    return cents / 12 if sub.get("interval") == "year" else cents


def _days_left(sub: dict) -> Optional[int]:
    end = sub.get("current_period_end")
    return None if not end else max(0, int((end - time.time()) // 86400))


@router.get("/stats")
async def stats(_: dict = Depends(require_admin)):
    subs = await db.subscriptions.find({"is_current": True, "status": {"$in": ACTIVE}}).to_list(5000)
    paid = [s for s in subs if s.get("price_cents", 0) > 0]
    by_product: dict = {}
    for s in subs:
        by_product[s["product_key"]] = by_product.get(s["product_key"], 0) + 1
    revenue = await (await db.payment_records.aggregate([
        {"$match": {"payment_status": "paid"}}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}])).to_list(1)
    soon = sum(1 for s in subs if (d := _days_left(s)) is not None and d <= 7)
    return {"users": await db.users.count_documents({"status": {"$ne": "deleted"}}),
            "organizations": await db.organizations.count_documents({"status": "active"}),
            "active_subscriptions": len(subs), "paid_subscriptions": len(paid), "free_subscriptions": len(subs) - len(paid),
            "mrr_cents": int(sum(_monthly(s) for s in paid)), "revenue_total": revenue[0]["total"] if revenue else 0,
            "expiring_7_days": soon, "by_product": by_product}


@router.get("/users")
async def users(q: Optional[str] = Query(None, max_length=100), _: dict = Depends(require_admin)):
    query: dict = {"status": {"$ne": "deleted"}}
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"name": rx}, {"email": rx}, {"document": rx}]
    docs = await db.users.find(query).sort("created_at", -1).to_list(500)
    owned = await db.organization_members.find({"user_id": {"$in": [u["_id"] for u in docs]}, "role": "owner"}).to_list(2000)
    org_ids = {m["organization_id"] for m in owned}
    subs = await db.subscriptions.find({"organization_id": {"$in": list(org_ids)}, "is_current": True}).to_list(5000)
    out = []
    for u in docs:
        mine = {m["organization_id"] for m in owned if m["user_id"] == u["_id"]}
        out.append({"id": str(u["_id"]), "name": u["name"], "email": u["email"], "document": u.get("document"),
                    "email_verified": u.get("email_verified", False), "is_admin": is_platform_admin(u),
                    "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
                    "products": [{"product_key": s["product_key"], "plan_key": s["plan_key"], "status": s["status"]}
                                 for s in subs if s["organization_id"] in mine]})
    return {"items": out}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request, admin: dict = Depends(require_admin)):
    target = await db.users.find_one({"_id": to_oid(user_id), "status": {"$ne": "deleted"}})
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    if target["_id"] == admin["_id"] or is_platform_admin(target):
        raise HTTPException(status_code=400, detail="Não é possível excluir uma conta de administrador")
    orgs = [m["organization_id"] async for m in db.organization_members.find({"user_id": target["_id"], "role": "owner"})]
    async for s in db.subscriptions.find({"organization_id": {"$in": orgs}, "is_current": True,
                                          "stripe_subscription_id": {"$ne": None}}):
        try:
            stripe.Subscription.cancel(s["stripe_subscription_id"])
        except stripe.error.StripeError as e:
            logger.warning("Stripe cancel failed for %s: %s", s["_id"], e)
    now = utcnow()
    await db.subscriptions.update_many({"organization_id": {"$in": orgs}, "is_current": True},
                                       {"$set": {"status": "canceled", "is_current": False, "updated_at": now}})
    await db.organizations.update_many({"_id": {"$in": orgs}}, {"$set": {"status": "deleted", "updated_at": now}})
    await db.organization_members.update_many({"user_id": target["_id"]}, {"$set": {"status": "removed"}})
    await db.product_permissions.delete_many({"user_id": target["_id"]})
    await db.sessions.delete_many({"user_id": target["_id"]})
    await db.users.update_one({"_id": target["_id"]}, {"$set": {
        "status": "deleted", "email": f"deleted_{target['_id']}@deleted.local", "document": None, "name": "Conta excluída",
        "password_hash": None, "phone": None, "deleted_at": now}})
    await audit("admin.user_deleted", user_id=admin["_id"], target_type="user", target_id=user_id, request=request)
    return {"ok": True}


@router.get("/subscriptions")
async def subscriptions(status: Optional[str] = Query(None, pattern=r"^(active|past_due|canceled|pending|expired)$"),
                        _: dict = Depends(require_admin)):
    query: dict = {"is_current": True} if not status else {"status": status}
    subs = await db.subscriptions.find(query).sort("updated_at", -1).to_list(1000)
    orgs = {o["_id"]: o async for o in db.organizations.find({"_id": {"$in": [s["organization_id"] for s in subs]}})}
    owners = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [o["owner_id"] for o in orgs.values()]}})}
    items = []
    for s in subs:
        org = orgs.get(s["organization_id"], {})
        owner = owners.get(org.get("owner_id"), {})
        items.append({"id": str(s["_id"]), "organization": org.get("name"), "owner_email": owner.get("email"),
                      "product_key": s["product_key"], "plan_key": s["plan_key"], "status": s["status"],
                      "price_cents": s.get("price_cents", 0), "billing_method": s.get("billing_method", "card"),
                      "current_period_end": s.get("current_period_end"), "days_left": _days_left(s),
                      "cancel_at_period_end": s.get("cancel_at_period_end", False)})
    items.sort(key=lambda i: (i["days_left"] is None, i["days_left"] or 0))
    return {"items": items}


@router.post("/grant-free", status_code=201)
async def grant_free(body: GrantIn, request: Request, admin: dict = Depends(require_admin)):
    target = await db.users.find_one({"email": body.email.lower(), "status": {"$ne": "deleted"}})
    if not target:
        raise HTTPException(status_code=404, detail="Nenhuma conta com este e-mail")
    product = await db.products.find_one({"key": body.product_key})
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    segment = body.segment or product["supported_segments"][0]
    if segment not in product["supported_segments"]:
        raise HTTPException(status_code=400, detail="Segmento não suportado por este produto")
    now = utcnow()
    member = await db.organization_members.find_one({"user_id": target["_id"], "role": "owner", "status": "active"})
    if member:
        org_id = member["organization_id"]
    else:
        org_id = (await db.organizations.insert_one({"name": target["name"], "document": target.get("document"),
                                                     "country": "BR", "owner_id": target["_id"], "status": "active",
                                                     "created_at": now, "updated_at": now})).inserted_id
        await db.organization_members.insert_one({"organization_id": org_id, "user_id": target["_id"], "role": "owner",
                                                  "status": "active", "created_at": now})
    current = await db.subscriptions.find_one({"organization_id": org_id, "product_key": body.product_key, "is_current": True})
    if current and current.get("stripe_subscription_id") and current["status"] in ACTIVE:
        raise HTTPException(status_code=409, detail="Este cliente já tem uma assinatura paga ativa deste produto")
    await db.subscriptions.update_many({"organization_id": org_id, "product_key": body.product_key, "is_current": True},
                                       {"$set": {"is_current": False, "status": "replaced", "updated_at": now}})
    from app.core.subscriptions import service as subs
    sub_id = (await db.subscriptions.insert_one({
        "organization_id": org_id, "product_key": body.product_key, "plan_key": "cortesia", "segment": segment,
        "status": "pending", "is_current": False, "created_by": admin["_id"], "price_cents": 0, "currency": "brl",
        "billing_method": "grant", "interval": "month", "cancel_at_period_end": False, "created_at": now,
        "updated_at": now})).inserted_id
    await subs.activate_subscription(sub_id, None, None, "admin_grant")
    await db.subscriptions.update_one({"_id": sub_id}, {"$set": {
        "current_period_end": int((now + timedelta(days=body.days)).timestamp())}})
    await audit("admin.free_plan_granted", user_id=admin["_id"], organization_id=org_id, product_key=body.product_key,
                target_type="subscription", target_id=str(sub_id), request=request,
                metadata={"email": target["email"], "days": body.days})
    return {"ok": True, "subscription_id": str(sub_id)}


@router.get("/revenue")
async def revenue(_: dict = Depends(require_admin)):
    months = await (await db.payment_records.aggregate([
        {"$match": {"payment_status": "paid"}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$created_at"}},
                    "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"_id": -1}}, {"$limit": 12}])).to_list(12)
    recent = await db.payment_records.find({"payment_status": "paid"}).sort("created_at", -1).to_list(50)
    users = {u["_id"]: u async for u in db.users.find({"_id": {"$in": [r["user_id"] for r in recent]}})}
    return {"months": [{"month": m["_id"], "total": m["total"], "count": m["count"]} for m in months],
            "recent": [{"id": str(r["_id"]), "product_key": r["product_key"], "amount": r["amount"],
                        "currency": r["currency"], "email": users.get(r["user_id"], {}).get("email"),
                        "created_at": r["created_at"].isoformat()} for r in recent]}
