"""Marketplace public frontend backend. Fully isolated from SaaS auth.
Own users (mp_users), own products (mp_products), own orders (mp_orders).
Uses a separate cookie (`mp_access_token`) so SaaS and Marketplace sessions
never collide in the same browser."""
import os
import re
from datetime import datetime, timezone
from typing import Literal, Optional

import stripe
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings
from app.core.database import db
from app.core.mongo import now_utc, oid
from app.core.security import (
    decode_token,
    hash_password,
    verify_password,
)
from datetime import timedelta
import jwt

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or "sk_test_emergent"

router = APIRouter(prefix="/mp", tags=["Marketplace Public"])
shop_router = APIRouter(prefix="/shop", tags=["Marketplace Shop"])


def _mp_create_token(user_id: str, email: str, user_type: str) -> str:
    payload = {"sub": user_id, "email": email, "role": user_type, "type": "access",
               "aud": "marketplace", "exp": now_utc() + timedelta(days=7)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "loja"


def _serialize(doc: dict) -> dict:
    if not doc:
        return doc
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
        elif isinstance(v, ObjectId):
            doc[k] = str(v)
    return doc


async def get_mp_user(request: Request) -> dict:
    token = request.cookies.get("mp_access_token") or ""
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid token")
    if payload.get("aud") != "marketplace":
        raise HTTPException(401, "Invalid audience")
    user = await db.mp_users.find_one({"_id": oid(payload["sub"])})
    if not user:
        raise HTTPException(401, "User not found")
    if user.get("banned"):
        raise HTTPException(403, "Conta suspensa")
    return _serialize(user)


def require_seller(user: dict = Depends(get_mp_user)) -> dict:
    if user.get("user_type") != "seller":
        raise HTTPException(403, "Seller account required")
    return user


def _set_mp_cookie(response: Response, token: str) -> None:
    response.set_cookie("mp_access_token", token, httponly=True, secure=True,
                        samesite="none", max_age=60 * 60 * 24 * 7, path="/")


# ------------- Auth -------------

class MpRegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    user_type: Literal["buyer", "seller"] = "buyer"
    store_name: Optional[str] = None
    phone: Optional[str] = None


class MpLoginRequest(BaseModel):
    email: EmailStr
    password: str


async def _unique_slug(base: str) -> str:
    slug = base
    i = 2
    while await db.mp_users.find_one({"slug": slug}):
        slug = f"{base}-{i}"; i += 1
    return slug


@router.post("/auth/register")
async def mp_register(payload: MpRegisterRequest, response: Response):
    if await db.mp_users.find_one({"email": payload.email.lower()}):
        raise HTTPException(409, "Email já cadastrado")
    if payload.user_type == "seller" and not payload.store_name:
        raise HTTPException(400, "Nome da loja é obrigatório para vendedores")
    doc = {
        "email": payload.email.lower(), "name": payload.name,
        "password_hash": hash_password(payload.password),
        "user_type": payload.user_type, "phone": payload.phone,
        "store_name": payload.store_name, "created_at": datetime.now(timezone.utc),
    }
    if payload.user_type == "seller":
        doc["slug"] = await _unique_slug(_slugify(payload.store_name))
        doc["banner_url"] = None
        doc["bio"] = None
    r = await db.mp_users.insert_one(doc)
    user_id = str(r.inserted_id)
    token = _mp_create_token(user_id, doc["email"], doc["user_type"])
    _set_mp_cookie(response, token)
    return {"id": user_id, "email": doc["email"], "name": doc["name"],
            "user_type": doc["user_type"], "store_name": doc.get("store_name"),
            "slug": doc.get("slug"), "access_token": token}


@router.post("/auth/login")
async def mp_login(payload: MpLoginRequest, response: Response):
    user = await db.mp_users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(401, "Credenciais inválidas")
    if user.get("banned"):
        raise HTTPException(403, "Conta suspensa")
    user = _serialize(user)
    token = _mp_create_token(user["id"], user["email"], user["user_type"])
    _set_mp_cookie(response, token)
    return {**user, "access_token": token}


@router.post("/auth/logout")
async def mp_logout(response: Response):
    response.delete_cookie("mp_access_token", path="/")
    return {"status": "ok"}


@router.get("/auth/me")
async def mp_me(user: dict = Depends(get_mp_user)):
    return user


class MpUserSelfUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    shipping_address: Optional[str] = None


@router.patch("/auth/me")
async def mp_update_me(payload: MpUserSelfUpdate, user: dict = Depends(get_mp_user)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        await db.mp_users.update_one({"_id": oid(user["id"])}, {"$set": updates})
    doc = await db.mp_users.find_one({"_id": oid(user["id"])})
    return _serialize(doc)


class SellerProfileUpdate(BaseModel):
    store_name: Optional[str] = None
    banner_url: Optional[str] = None
    bio: Optional[str] = None


@router.patch("/seller/profile")
async def seller_profile_update(payload: SellerProfileUpdate, user: dict = Depends(require_seller)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if updates:
        await db.mp_users.update_one({"_id": oid(user["id"])}, {"$set": updates})
    doc = await db.mp_users.find_one({"_id": oid(user["id"])})
    return _serialize(doc)


# ------------- Seller: products & orders -------------

class MpProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    description: str = Field(default="", max_length=4000)
    price_cents: int = Field(gt=0)
    currency: str = "BRL"
    image_url: Optional[str] = None
    images: list[str] = Field(default_factory=list)
    stock: int = Field(default=0, ge=0)
    category: Optional[str] = None
    sizes: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)


class MpProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_cents: Optional[int] = Field(None, gt=0)
    image_url: Optional[str] = None
    images: Optional[list[str]] = None
    stock: Optional[int] = Field(None, ge=0)
    category: Optional[str] = None
    sizes: Optional[list[str]] = None
    colors: Optional[list[str]] = None
    active: Optional[bool] = None


@router.get("/seller/products")
async def seller_products(user: dict = Depends(require_seller)):
    rows = await db.mp_products.find({"seller_id": user["id"]}, limit=200).to_list(200)
    return [_serialize(r) for r in rows]


@router.post("/seller/products")
async def seller_create_product(payload: MpProductCreate, user: dict = Depends(require_seller)):
    doc = {**payload.model_dump(), "seller_id": user["id"],
           "seller_name": user.get("store_name") or user.get("name"),
           "seller_slug": user.get("slug"),
           "active": True, "created_at": datetime.now(timezone.utc)}
    r = await db.mp_products.insert_one(doc)
    return _serialize({**doc, "_id": r.inserted_id})


@router.patch("/seller/products/{product_id}")
async def seller_update_product(product_id: str, payload: MpProductUpdate,
                                user: dict = Depends(require_seller)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    r = await db.mp_products.update_one({"_id": oid(product_id), "seller_id": user["id"]},
                                        {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "Product not found")
    doc = await db.mp_products.find_one({"_id": oid(product_id)})
    return _serialize(doc)


@router.delete("/seller/products/{product_id}")
async def seller_delete_product(product_id: str, user: dict = Depends(require_seller)):
    r = await db.mp_products.delete_one({"_id": oid(product_id), "seller_id": user["id"]})
    if r.deleted_count == 0:
        raise HTTPException(404, "Product not found")
    return {"status": "deleted"}


@router.get("/seller/orders")
async def seller_orders(user: dict = Depends(require_seller)):
    rows = await db.mp_orders.find({"seller_id": user["id"]}, limit=200).sort("created_at", -1).to_list(200)
    return [_serialize(r) for r in rows]


@router.patch("/seller/orders/{order_id}")
async def seller_update_order(order_id: str, status: str, user: dict = Depends(require_seller)):
    if status not in ("processing", "shipped", "delivered", "canceled"):
        raise HTTPException(400, "Invalid status")
    r = await db.mp_orders.update_one({"_id": oid(order_id), "seller_id": user["id"]},
                                      {"$set": {"status": status,
                                                "updated_at": datetime.now(timezone.utc)}})
    if r.matched_count == 0:
        raise HTTPException(404, "Order not found")
    return {"status": "ok"}


# ------------- Buyer -------------

@router.get("/my/orders")
async def my_orders(user: dict = Depends(get_mp_user)):
    rows = await db.mp_orders.find({"buyer_id": user["id"]}, limit=100).sort("created_at", -1).to_list(100)
    return [_serialize(r) for r in rows]


# ------------- Public shop -------------

async def _product_review_summary(product_id: str) -> dict:
    pipeline = [
        {"$match": {"product_id": product_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}},
    ]
    result = await db.mp_reviews.aggregate(pipeline).to_list(1)
    if result:
        return {"avg": round(result[0]["avg"], 1), "count": result[0]["count"]}
    return {"avg": 0.0, "count": 0}


@shop_router.get("/products")
async def shop_products(search: Optional[str] = None, category: Optional[str] = None,
                        limit: int = 60, skip: int = 0):
    query = {"active": True}
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    if category:
        query["category"] = category
    rows = await db.mp_products.find(query, limit=limit, skip=skip).sort("created_at", -1).to_list(limit)
    return [_serialize(r) for r in rows]


@shop_router.get("/products/{product_id}")
async def shop_product(product_id: str):
    try:
        doc = await db.mp_products.find_one({"_id": oid(product_id), "active": True})
    except Exception:
        raise HTTPException(404, "Product not found")
    if not doc:
        raise HTTPException(404, "Product not found")
    result = _serialize(doc)
    result["reviews_summary"] = await _product_review_summary(str(doc["_id"]) if "_id" in doc else result["id"])
    return result


@shop_router.get("/categories")
async def shop_categories():
    cats = await db.mp_products.distinct("category", {"active": True})
    return [c for c in cats if c]


@shop_router.get("/store/{slug}")
async def public_store(slug: str):
    seller = await db.mp_users.find_one({"slug": slug, "user_type": "seller"})
    if not seller:
        raise HTTPException(404, "Loja não encontrada")
    seller_id = str(seller["_id"])
    products = await db.mp_products.find({"seller_id": seller_id, "active": True},
                                         limit=200).to_list(200)
    orders_count = await db.mp_orders.count_documents({"seller_id": seller_id,
                                                       "status": {"$ne": "canceled"}})
    return {
        "seller": {
            "id": seller_id, "store_name": seller.get("store_name"),
            "slug": seller.get("slug"), "banner_url": seller.get("banner_url"),
            "bio": seller.get("bio"),
            "created_at": seller.get("created_at").isoformat() if seller.get("created_at") else None,
        },
        "products": [_serialize(p) for p in products],
        "stats": {"products": len(products), "orders_completed": orders_count},
    }


# ------------- Reviews -------------

class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


@shop_router.get("/products/{product_id}/reviews")
async def list_reviews(product_id: str):
    rows = await db.mp_reviews.find({"product_id": product_id}, limit=100).sort("created_at", -1).to_list(100)
    return [_serialize(r) for r in rows]


@shop_router.post("/products/{product_id}/reviews")
async def create_review(product_id: str, payload: ReviewCreate, user: dict = Depends(get_mp_user)):
    if user.get("user_type") != "buyer":
        raise HTTPException(403, "Apenas compradores podem avaliar")
    # Must have a delivered order for this product.
    delivered = await db.mp_orders.find_one({
        "buyer_id": user["id"], "status": "delivered",
        "items.product_id": product_id,
    })
    if not delivered:
        raise HTTPException(403, "Você só pode avaliar produtos que já recebeu")
    if await db.mp_reviews.find_one({"buyer_id": user["id"], "product_id": product_id}):
        raise HTTPException(409, "Você já avaliou este produto")
    doc = {
        "product_id": product_id, "buyer_id": user["id"], "buyer_name": user["name"],
        "rating": payload.rating, "comment": payload.comment,
        "created_at": datetime.now(timezone.utc),
    }
    r = await db.mp_reviews.insert_one(doc)
    return _serialize({**doc, "_id": r.inserted_id})


# ------------- Stripe Checkout -------------

class ShopCheckoutItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    size: str = ""
    color: str = ""


class ShopCheckoutRequest(BaseModel):
    items: list[ShopCheckoutItem]
    shipping_address: str = Field(min_length=5, max_length=400)
    phone: str = Field(min_length=6, max_length=32)
    origin_url: str


@shop_router.post("/checkout")
async def shop_checkout(payload: ShopCheckoutRequest, user: dict = Depends(get_mp_user)):
    """Create Stripe checkout session for the whole cart. Orders are created in
    'awaiting_payment' state and flip to 'pending' (seller queue) once Stripe pays."""
    if user.get("user_type") != "buyer":
        raise HTTPException(403, "Apenas compradores podem comprar")
    orders_by_seller: dict[str, dict] = {}
    line_items = []
    total_cents = 0
    currency = "brl"
    for item in payload.items:
        prod = await db.mp_products.find_one({"_id": oid(item.product_id), "active": True})
        if not prod:
            raise HTTPException(400, f"Produto indisponível: {item.product_id}")
        if prod.get("stock", 0) < item.quantity:
            raise HTTPException(400, f"Estoque insuficiente para {prod['name']}")
        seller_id = str(prod["seller_id"])
        currency = (prod.get("currency") or "BRL").lower()
        bucket = orders_by_seller.setdefault(seller_id, {"items": [], "total": 0,
                                                         "currency": prod.get("currency", "BRL"),
                                                         "seller_name": prod.get("seller_name")})
        line_total = prod["price_cents"] * item.quantity
        bucket["items"].append({
            "product_id": str(prod["_id"]), "name": prod["name"],
            "quantity": item.quantity, "unit_price_cents": prod["price_cents"],
            "line_total_cents": line_total, "image_url": prod.get("image_url"),
            "category": prod.get("category", ""),
            "size": item.size, "color": item.color,
            "seller_name": prod.get("seller_name", ""),
        })
        bucket["total"] += line_total
        total_cents += line_total
        line_items.append({
            "price_data": {
                "currency": currency,
                "product_data": {"name": prod["name"]},
                "unit_amount": prod["price_cents"],
            },
            "quantity": item.quantity,
        })

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=line_items,
            success_url=f"{payload.origin_url}/order/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{payload.origin_url}/order/cancel",
            customer_email=user["email"],
            metadata={"buyer_id": user["id"], "kind": "shop_checkout"},
        )
    except stripe.error.StripeError as e:
        raise HTTPException(502, f"Stripe: {e.user_message or str(e)}")

    # Draft orders — activated on payment success.
    created_ids: list[str] = []
    for seller_id, bucket in orders_by_seller.items():
        doc = {
            "buyer_id": user["id"], "buyer_name": user["name"], "buyer_email": user["email"],
            "seller_id": seller_id, "seller_name": bucket["seller_name"],
            "items": bucket["items"], "amount": bucket["total"], "currency": bucket["currency"],
            "status": "awaiting_payment",
            "shipping_address": payload.shipping_address, "phone": payload.phone,
            "stripe_session_id": session.id,
            "created_at": datetime.now(timezone.utc),
        }
        r = await db.mp_orders.insert_one(doc)
        created_ids.append(str(r.inserted_id))

    await db.payment_transactions.insert_one({
        "session_id": session.id, "kind": "shop_checkout",
        "buyer_id": user["id"], "order_ids": created_ids,
        "amount": total_cents, "currency": currency.upper(),
        "status": "initiated", "payment_status": "pending",
        "created_at": datetime.now(timezone.utc),
    })
    return {"checkout_url": session.url, "session_id": session.id}


@shop_router.get("/checkout/status/{session_id}")
async def shop_checkout_status(session_id: str, user: dict = Depends(get_mp_user)):
    record = await db.payment_transactions.find_one({"session_id": session_id, "kind": "shop_checkout"})
    if not record or record.get("buyer_id") != user["id"]:
        raise HTTPException(404, "Transação não encontrada")
    if record.get("payment_status") != "paid":
        try:
            s = stripe.checkout.Session.retrieve(session_id)
            if s.payment_status == "paid" or s.status == "complete":
                await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "completed", "payment_status": "paid",
                              "updated_at": datetime.now(timezone.utc)}},
                )
                # Activate the buyer orders and decrement stock.
                for oid_str in record.get("order_ids", []):
                    order = await db.mp_orders.find_one({"_id": oid(oid_str),
                                                         "status": "awaiting_payment"})
                    if not order:
                        continue
                    await db.mp_orders.update_one(
                        {"_id": order["_id"]},
                        {"$set": {"status": "pending", "paid_at": datetime.now(timezone.utc)}},
                    )
                    for it in order["items"]:
                        await db.mp_products.update_one(
                            {"_id": oid(it["product_id"])},
                            {"$inc": {"stock": -it["quantity"]}},
                        )
                record = await db.payment_transactions.find_one({"session_id": session_id})
        except stripe.error.StripeError:
            pass
    return {"session_id": record["session_id"], "payment_status": record.get("payment_status"),
            "status": record.get("status"), "order_ids": record.get("order_ids", []),
            "amount": record.get("amount"), "currency": record.get("currency")}
