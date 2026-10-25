"""Admin-controlled coupons applied at Stripe Checkout."""
from datetime import datetime, timezone
from typing import Literal, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.database import db
from app.core.deps import require_role

router = APIRouter(prefix="/admin/coupons", tags=["Admin - Coupons"])


class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    kind: Literal["percent", "amount"] = "percent"
    value: int = Field(gt=0)  # percent 1-100 OR amount in cents
    currency: Optional[str] = "USD"
    duration: Literal["once", "repeating", "forever"] = "once"
    duration_in_months: Optional[int] = Field(None, ge=1, le=36)
    max_redemptions: Optional[int] = Field(None, ge=1)
    active: bool = True
    # Segmentação: restringe o cupom a um serviço específico e/ou intervalo mínimo.
    service: Optional[Literal["payments", "marketplace", "email", "automation", "linkbio", "any"]] = "any"
    min_interval: Optional[Literal["monthly", "yearly", "any"]] = "any"


def _serialize(c: dict) -> dict:
    c["id"] = str(c.pop("_id"))
    for k, v in list(c.items()):
        if isinstance(v, datetime):
            c[k] = v.isoformat()
    return c


@router.get("")
async def list_coupons(_: dict = Depends(require_role("admin"))):
    rows = await db.coupons.find({}, limit=200).to_list(200)
    return [_serialize(r) for r in rows]


@router.post("")
async def create_coupon(payload: CouponCreate, _: dict = Depends(require_role("admin"))):
    existing = await db.coupons.find_one({"code": payload.code.upper()})
    if existing:
        raise HTTPException(409, "Código já existe")

    kwargs: dict = {"duration": payload.duration, "id": payload.code.upper()}
    if payload.kind == "percent":
        if payload.value > 100:
            raise HTTPException(400, "Percent deve ser 1-100")
        kwargs["percent_off"] = payload.value
    else:
        kwargs["amount_off"] = payload.value
        kwargs["currency"] = (payload.currency or "USD").lower()
    if payload.duration == "repeating" and payload.duration_in_months:
        kwargs["duration_in_months"] = payload.duration_in_months
    if payload.max_redemptions:
        kwargs["max_redemptions"] = payload.max_redemptions
    try:
        coupon = stripe.Coupon.create(**kwargs)
        promo = stripe.PromotionCode.create(
            promotion={"type": "coupon", "coupon": coupon.id},
            code=payload.code.upper(),
        )
    except stripe.error.StripeError as e:
        raise HTTPException(502, f"Stripe: {e.user_message or str(e)}")

    doc = {
        "code": payload.code.upper(),
        "kind": payload.kind, "value": payload.value,
        "currency": (payload.currency or "USD").upper() if payload.kind == "amount" else None,
        "duration": payload.duration, "duration_in_months": payload.duration_in_months,
        "max_redemptions": payload.max_redemptions, "active": payload.active,
        "service": payload.service or "any",
        "min_interval": payload.min_interval or "any",
        "stripe_coupon_id": coupon.id, "stripe_promotion_code_id": promo.id,
        "redemptions": 0, "created_at": datetime.now(timezone.utc),
    }
    r = await db.coupons.insert_one(doc)
    doc["id"] = str(r.inserted_id); doc.pop("_id", None)
    return doc


@router.delete("/{coupon_id}")
async def delete_coupon(coupon_id: str, _: dict = Depends(require_role("admin"))):
    from app.core.mongo import oid
    c = await db.coupons.find_one({"_id": oid(coupon_id)})
    if not c:
        raise HTTPException(404, "Coupon not found")
    try:
        if c.get("stripe_coupon_id"):
            stripe.Coupon.delete(c["stripe_coupon_id"])
    except stripe.error.StripeError:
        pass
    await db.coupons.delete_one({"_id": oid(coupon_id)})
    return {"status": "deleted"}


public_router = APIRouter(prefix="/public/coupons", tags=["Public"])


@public_router.get("/{code}")
async def validate_coupon(code: str, service: Optional[str] = None, interval: Optional[str] = None):
    c = await db.coupons.find_one({"code": code.upper(), "active": True})
    if not c:
        raise HTTPException(404, "Cupom inválido")
    if c.get("max_redemptions") and c.get("redemptions", 0) >= c["max_redemptions"]:
        raise HTTPException(410, "Cupom esgotado")
    if service and c.get("service") and c["service"] not in ("any", service):
        raise HTTPException(400, f"Cupom válido apenas para {c['service']}")
    if interval and c.get("min_interval") in ("yearly",) and interval != "yearly":
        raise HTTPException(400, "Cupom válido apenas no plano anual")
    return {"code": c["code"], "kind": c["kind"], "value": c["value"],
            "currency": c.get("currency"), "duration": c["duration"],
            "service": c.get("service", "any"), "min_interval": c.get("min_interval", "any")}
