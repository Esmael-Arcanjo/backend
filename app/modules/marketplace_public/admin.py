"""Marketplace Admin routes. Separate from the SaaS admin.
Admins live in `mp_users` with `user_type=admin` and have no seller/buyer state.
They can moderate products, users and orders for the wibaza marketplace."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import db
from app.core.mongo import oid
from app.modules.marketplace_public.routes import _serialize, get_mp_user

admin_router = APIRouter(prefix="/mp/admin", tags=["Marketplace Admin"])


def require_mp_admin(user: dict = Depends(get_mp_user)) -> dict:
    if user.get("user_type") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


@admin_router.get("/stats")
async def mp_admin_stats(_: dict = Depends(require_mp_admin)):
    sellers = await db.mp_users.count_documents({"user_type": "seller"})
    buyers = await db.mp_users.count_documents({"user_type": "buyer"})
    products = await db.mp_products.count_documents({})
    active_products = await db.mp_products.count_documents({"active": True})
    total_orders = await db.mp_orders.count_documents({})
    paid_orders_cursor = db.mp_orders.find(
        {"status": {"$in": ["pending", "processing", "shipped", "delivered"]}},
        {"amount": 1, "currency": 1},
    )
    revenue = 0
    orders_paid = 0
    async for o in paid_orders_cursor:
        revenue += o.get("amount", 0)
        orders_paid += 1
    pending_reviews = await db.mp_products.count_documents({"active": True, "moderation": "pending"})
    return {
        "sellers": sellers,
        "buyers": buyers,
        "products_total": products,
        "products_active": active_products,
        "orders_total": total_orders,
        "orders_paid": orders_paid,
        "revenue_cents": revenue,
        "products_pending_review": pending_reviews,
    }


@admin_router.get("/users")
async def mp_admin_users(user_type: Optional[str] = None, banned: Optional[bool] = None,
                          limit: int = 200, skip: int = 0,
                          _: dict = Depends(require_mp_admin)):
    q: dict = {}
    if user_type in ("buyer", "seller"):
        q["user_type"] = user_type
    if banned is not None:
        q["banned"] = banned
    rows = await db.mp_users.find(q, limit=limit, skip=skip).sort("created_at", -1).to_list(limit)
    return [_serialize(r) for r in rows]


class BanRequest(BaseModel):
    banned: bool = True
    reason: Optional[str] = None


@admin_router.post("/users/{user_id}/ban")
async def mp_admin_ban(user_id: str, payload: BanRequest, _: dict = Depends(require_mp_admin)):
    target = await db.mp_users.find_one({"_id": oid(user_id)})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("user_type") == "admin":
        raise HTTPException(400, "Cannot ban another admin")
    await db.mp_users.update_one(
        {"_id": oid(user_id)},
        {"$set": {"banned": payload.banned, "ban_reason": payload.reason,
                  "banned_at": datetime.now(timezone.utc) if payload.banned else None}},
    )
    if payload.banned and target.get("user_type") == "seller":
        await db.mp_products.update_many({"seller_id": user_id}, {"$set": {"active": False}})
    return {"status": "ok", "banned": payload.banned}


@admin_router.delete("/users/{user_id}")
async def mp_admin_delete_user(user_id: str, _: dict = Depends(require_mp_admin)):
    target = await db.mp_users.find_one({"_id": oid(user_id)})
    if not target:
        raise HTTPException(404, "User not found")
    if target.get("user_type") == "admin":
        raise HTTPException(400, "Cannot delete admin")
    await db.mp_users.delete_one({"_id": oid(user_id)})
    if target.get("user_type") == "seller":
        await db.mp_products.delete_many({"seller_id": user_id})
    return {"status": "deleted"}


@admin_router.get("/products")
async def mp_admin_products(active: Optional[bool] = None, seller_id: Optional[str] = None,
                             search: Optional[str] = None, limit: int = 100, skip: int = 0,
                             _: dict = Depends(require_mp_admin)):
    q: dict = {}
    if active is not None:
        q["active"] = active
    if seller_id:
        q["seller_id"] = seller_id
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    rows = await db.mp_products.find(q, limit=limit, skip=skip).sort("created_at", -1).to_list(limit)
    return [_serialize(r) for r in rows]


class ProductModeration(BaseModel):
    active: Optional[bool] = None
    moderation_note: Optional[str] = None


@admin_router.patch("/products/{product_id}")
async def mp_admin_moderate(product_id: str, payload: ProductModeration,
                             _: dict = Depends(require_mp_admin)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    r = await db.mp_products.update_one({"_id": oid(product_id)}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "Product not found")
    doc = await db.mp_products.find_one({"_id": oid(product_id)})
    return _serialize(doc)


@admin_router.delete("/products/{product_id}")
async def mp_admin_delete_product(product_id: str, _: dict = Depends(require_mp_admin)):
    r = await db.mp_products.delete_one({"_id": oid(product_id)})
    if r.deleted_count == 0:
        raise HTTPException(404, "Product not found")
    return {"status": "deleted"}


@admin_router.get("/orders")
async def mp_admin_orders(status: Optional[str] = None, limit: int = 200,
                          _: dict = Depends(require_mp_admin)):
    q: dict = {}
    if status:
        q["status"] = status
    rows = await db.mp_orders.find(q, limit=limit).sort("created_at", -1).to_list(limit)
    return [_serialize(r) for r in rows]
