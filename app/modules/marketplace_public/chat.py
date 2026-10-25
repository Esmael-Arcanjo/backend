"""Marketplace chat between buyers and sellers.
Simple REST + polling design: a thread is a pair (buyer_id, seller_id).
Optionally scoped to a product_id for the initial context."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import db
from app.core.mongo import oid
from app.modules.marketplace_public.routes import _serialize, get_mp_user

chat_router = APIRouter(prefix="/mp/chat", tags=["Marketplace Chat"])


class ChatStart(BaseModel):
    seller_id: str
    product_id: Optional[str] = None


class ChatMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _now():
    return datetime.now(timezone.utc)


async def _get_thread_for_user(thread_id: str, user: dict) -> dict:
    thread = await db.mp_chat_threads.find_one({"_id": oid(thread_id)})
    if not thread:
        raise HTTPException(404, "Thread not found")
    uid = user["id"]
    if thread["buyer_id"] != uid and thread["seller_id"] != uid:
        raise HTTPException(403, "Not a participant")
    return thread


@chat_router.post("/start")
async def chat_start(payload: ChatStart, user: dict = Depends(get_mp_user)):
    """Buyer creates or reuses a thread with a seller (optionally about a product).
    Only buyers can start a thread; sellers reply through the inbox."""
    if user.get("user_type") != "buyer":
        raise HTTPException(403, "Apenas compradores podem iniciar conversas")
    seller = await db.mp_users.find_one({"_id": oid(payload.seller_id), "user_type": "seller"})
    if not seller:
        raise HTTPException(404, "Vendedor não encontrado")
    seller_id = str(seller["_id"])
    existing = await db.mp_chat_threads.find_one({
        "buyer_id": user["id"], "seller_id": seller_id,
    })
    product_snapshot = None
    if payload.product_id:
        prod = await db.mp_products.find_one({"_id": oid(payload.product_id)})
        if prod:
            product_snapshot = {
                "id": str(prod["_id"]), "name": prod.get("name"),
                "image_url": prod.get("image_url"),
                "price_cents": prod.get("price_cents"),
                "currency": prod.get("currency"),
            }
    if existing:
        if product_snapshot and not existing.get("product"):
            await db.mp_chat_threads.update_one(
                {"_id": existing["_id"]}, {"$set": {"product": product_snapshot}},
            )
        return {"thread_id": str(existing["_id"])}
    doc = {
        "buyer_id": user["id"], "buyer_name": user["name"],
        "seller_id": seller_id, "seller_name": seller.get("store_name") or seller.get("name"),
        "seller_slug": seller.get("slug"),
        "product": product_snapshot,
        "created_at": _now(), "last_at": _now(),
        "last_message": None,
        "unread_buyer": 0, "unread_seller": 0,
    }
    r = await db.mp_chat_threads.insert_one(doc)
    return {"thread_id": str(r.inserted_id)}


@chat_router.get("/threads")
async def chat_threads(user: dict = Depends(get_mp_user)):
    field = "buyer_id" if user.get("user_type") == "buyer" else "seller_id"
    if user.get("user_type") not in ("buyer", "seller"):
        return []
    rows = await db.mp_chat_threads.find({field: user["id"]}, limit=100).sort("last_at", -1).to_list(100)
    out = []
    for t in rows:
        t = _serialize(t)
        t["unread"] = t.get("unread_buyer", 0) if user["user_type"] == "buyer" else t.get("unread_seller", 0)
        out.append(t)
    return out


@chat_router.get("/threads/{thread_id}")
async def chat_thread_info(thread_id: str, user: dict = Depends(get_mp_user)):
    thread = await _get_thread_for_user(thread_id, user)
    return _serialize(thread)


@chat_router.get("/threads/{thread_id}/messages")
async def chat_messages(thread_id: str, after: Optional[str] = Query(None),
                        user: dict = Depends(get_mp_user)):
    thread = await _get_thread_for_user(thread_id, user)
    q: dict = {"thread_id": str(thread["_id"])}
    if after:
        try:
            q["created_at"] = {"$gt": datetime.fromisoformat(after.replace("Z", "+00:00"))}
        except ValueError:
            pass
    rows = await db.mp_chat_messages.find(q, limit=200).sort("created_at", 1).to_list(200)
    # Mark thread as read for the reader only when we actually deliver messages.
    unread_field = "unread_buyer" if user["user_type"] == "buyer" else "unread_seller"
    if rows and thread.get(unread_field, 0) > 0:
        await db.mp_chat_threads.update_one({"_id": thread["_id"]}, {"$set": {unread_field: 0}})
    return [_serialize(r) for r in rows]


@chat_router.post("/threads/{thread_id}/messages")
async def chat_send(thread_id: str, payload: ChatMessage, user: dict = Depends(get_mp_user)):
    thread = await _get_thread_for_user(thread_id, user)
    role = user["user_type"]  # buyer or seller
    now = _now()
    msg = {
        "thread_id": str(thread["_id"]),
        "sender_id": user["id"], "sender_name": user["name"],
        "sender_role": role,
        "text": payload.text,
        "created_at": now,
    }
    r = await db.mp_chat_messages.insert_one(msg)
    # Increment unread for the OTHER party.
    other = "unread_seller" if role == "buyer" else "unread_buyer"
    await db.mp_chat_threads.update_one(
        {"_id": thread["_id"]},
        {"$set": {"last_at": now, "last_message": payload.text[:180]},
         "$inc": {other: 1}},
    )
    return _serialize({**msg, "_id": r.inserted_id})
