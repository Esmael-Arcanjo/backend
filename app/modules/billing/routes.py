import logging
import os
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.database import db
from app.core.deps import get_current_org, get_current_user
from app.core.mongo import oid
from app.modules.email.internal import send_internal
from app.modules.subscriptions.service import SubscriptionService, get_pricing

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or "sk_test_emergent"
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

router = APIRouter(prefix="/billing", tags=["Billing"])
subs = SubscriptionService()
log = logging.getLogger("leamse.billing")

TRIAL_DAYS = 7
SUBSCRIPTION_SERVICES = {"email", "automation", "linkbio"}


class CheckoutRequest(BaseModel):
    service: str = Field(..., pattern="^(payments|marketplace|email|automation|linkbio)$")
    interval: str = Field("monthly", pattern="^(monthly|yearly)$")
    origin_url: str
    trial: bool = True
    promo_code: str | None = None


class ChangeIntervalRequest(BaseModel):
    interval: str = Field(..., pattern="^(monthly|yearly)$")


def _format_amount(cents: int, currency: str) -> str:
    try:
        return f"{currency.upper()} {cents/100:,.2f}"
    except Exception:
        return f"{cents} {currency}"


async def _get_or_create_stripe_price(service: str, interval: str, amount: int, currency: str) -> str:
    """Create/reuse a Stripe Price for a given service+interval. Needed to modify subscriptions."""
    lookup = f"leamse_{service}_{interval}"
    existing = stripe.Price.list(lookup_keys=[lookup], active=True, limit=1).data
    if existing and existing[0].unit_amount == amount and existing[0].currency == currency.lower():
        return existing[0].id
    for p in existing:
        stripe.Price.modify(p.id, active=False)
    # Look up or create product.
    prod_lookup = f"leamse_{service}"
    products = stripe.Product.list(active=True, limit=100).data
    product = next((p for p in products if (p.metadata or {}).get("emergent_product_id") == prod_lookup), None)
    if not product:
        product = stripe.Product.create(
            name=f"LEAMSE {service.capitalize()}",
            metadata={"emergent_product_id": prod_lookup, "managed_by": "emergent"},
        )
    price = stripe.Price.create(
        product=product.id, unit_amount=amount, currency=currency.lower(),
        recurring={"interval": "year" if interval == "yearly" else "month"},
        lookup_key=lookup, transfer_lookup_key=True,
    )
    return price.id


@router.post("/checkout")
async def create_checkout(payload: CheckoutRequest,
                          user: dict = Depends(get_current_user),
                          org: dict = Depends(get_current_org)):
    pricing = await get_pricing()
    entry = pricing.get(payload.service, {})
    if entry.get("model") != "subscription":
        await subs.subscribe(org["id"], payload.service, "usage", org.get("default_currency", "USD"))
        await send_internal(user["email"], "welcome",
                            {"name": user.get("name", ""), "service": payload.service},
                            organization_id=org["id"])
        return {"checkout_url": None, "session_id": None,
                "message": "Serviço ativo (pay-as-you-go)"}
    amount = entry.get(payload.interval)
    if not amount:
        raise HTTPException(400, "Invalid interval or pricing not configured")
    currency = (entry.get("currency") or "USD").lower()

    # Resolve promo_code if any.
    stripe_promo = None
    if payload.promo_code:
        c = await db.coupons.find_one({"code": payload.promo_code.upper(), "active": True})
        if not c:
            raise HTTPException(400, "Cupom inválido")
        if c.get("max_redemptions") and c.get("redemptions", 0) >= c["max_redemptions"]:
            raise HTTPException(410, "Cupom esgotado")
        if c.get("service") and c["service"] not in ("any", payload.service):
            raise HTTPException(400, f"Cupom válido apenas para {c['service']}")
        if c.get("min_interval") == "yearly" and payload.interval != "yearly":
            raise HTTPException(400, "Cupom válido apenas no plano anual")
        stripe_promo = c.get("stripe_promotion_code_id")

    subscription_data = {"metadata": {
        "organization_id": org["id"], "user_id": user["id"],
        "service": payload.service, "interval": payload.interval,
    }}
    if payload.trial:
        subscription_data["trial_period_days"] = TRIAL_DAYS

    try:
        price_id = await _get_or_create_stripe_price(payload.service, payload.interval, amount, currency)
        session_kwargs = dict(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data=subscription_data,
            success_url=f"{payload.origin_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{payload.origin_url}/payment/cancel",
            customer_email=user.get("email"),
            metadata=subscription_data["metadata"],
        )
        if stripe_promo:
            session_kwargs["discounts"] = [{"promotion_code": stripe_promo}]
        else:
            session_kwargs["allow_promotion_codes"] = True
        session = stripe.checkout.Session.create(**session_kwargs)
    except stripe.error.StripeError as e:
        raise HTTPException(502, f"Stripe error: {e.user_message or str(e)}")

    await db.payment_transactions.insert_one({
        "session_id": session.id, "organization_id": org["id"], "user_id": user["id"],
        "service": payload.service, "interval": payload.interval,
        "amount": amount, "currency": currency,
        "status": "initiated", "payment_status": "pending", "trial": payload.trial,
        "promo_code": payload.promo_code.upper() if payload.promo_code else None,
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    })
    return {"checkout_url": session.url, "session_id": session.id,
            "trial_days": TRIAL_DAYS if payload.trial else 0}


@router.get("/status/{session_id}")
async def status(session_id: str):
    record = await db.payment_transactions.find_one({"session_id": session_id})
    if not record:
        raise HTTPException(404, "Transaction not found")
    if record.get("payment_status") != "paid":
        try:
            s = stripe.checkout.Session.retrieve(session_id, expand=["subscription"])
            paid = s.payment_status == "paid" or s.status == "complete"
            if paid:
                sub_id = s.subscription.id if s.subscription else None
                await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "completed", "payment_status": "paid",
                              "stripe_subscription_id": sub_id,
                              "updated_at": datetime.now(timezone.utc)}},
                )
                await subs.subscribe(record["organization_id"], record["service"],
                                     record["interval"], record["currency"].upper())
                await db.subscriptions.update_many(
                    {"organization_id": record["organization_id"], "status": {"$ne": "canceled"}},
                    {"$set": {"stripe_subscription_id": sub_id,
                              "trial": bool(record.get("trial"))}},
                )
                if record.get("promo_code"):
                    await db.coupons.update_one({"code": record["promo_code"]},
                                                {"$inc": {"redemptions": 1}})
                user = await db.users.find_one({"_id": oid(record["user_id"])})
                if user:
                    await send_internal(
                        user["email"], "payment_success",
                        {"service": record["service"], "interval": record["interval"],
                         "amount_formatted": _format_amount(record["amount"], record["currency"])},
                        organization_id=record["organization_id"],
                    )
                record = await db.payment_transactions.find_one({"session_id": session_id})
        except stripe.error.StripeError:
            pass
    return {"session_id": record["session_id"], "status": record.get("status"),
            "payment_status": record.get("payment_status"), "service": record.get("service"),
            "amount": record.get("amount"), "currency": record.get("currency")}


@router.get("/subscription")
async def my_subscription(org: dict = Depends(get_current_org)):
    return {
        "subscription": await subs.current(org["id"]),
        "invoices": await subs.list_invoices(org["id"]),
        "pricing": await get_pricing(),
    }


@router.post("/subscription/cancel")
async def cancel_subscription(org: dict = Depends(get_current_org)):
    sub = await subs.current(org["id"])
    if not sub:
        raise HTTPException(404, "No active subscription")
    stripe_sub_id = sub.get("stripe_subscription_id")
    if stripe_sub_id:
        try:
            stripe.Subscription.modify(stripe_sub_id, cancel_at_period_end=True)
        except stripe.error.StripeError as e:
            log.warning("Stripe cancel failed: %s", e)
    return await subs.cancel(org["id"])


@router.post("/subscription/change-interval")
async def change_interval(payload: ChangeIntervalRequest, org: dict = Depends(get_current_org)):
    """Change monthly<->yearly with prorated credit for unused time."""
    sub = await subs.current(org["id"])
    if not sub:
        raise HTTPException(404, "No active subscription")
    if sub.get("interval") == payload.interval:
        return sub
    pricing = await get_pricing()
    entry = pricing.get(sub["service"], {})
    if entry.get("model") != "subscription":
        raise HTTPException(400, "This service does not support plan changes")
    amount = entry.get(payload.interval)
    currency = (entry.get("currency") or sub.get("currency", "USD")).lower()

    stripe_sub_id = sub.get("stripe_subscription_id")
    proration_applied = False
    if stripe_sub_id:
        try:
            stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
            item_id = stripe_sub["items"]["data"][0]["id"]
            new_price_id = await _get_or_create_stripe_price(sub["service"], payload.interval, amount, currency)
            stripe.Subscription.modify(
                stripe_sub_id,
                items=[{"id": item_id, "price": new_price_id}],
                proration_behavior="create_prorations",
                billing_cycle_anchor="now",
            )
            proration_applied = True
        except stripe.error.StripeError as e:
            log.warning("Stripe proration failed: %s", e)
    updated = await subs.subscribe(org["id"], sub["service"], payload.interval, currency.upper())
    updated["proration_applied"] = proration_applied
    return updated


@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    obj = event["data"]["object"]
    etype = event["type"]

    if etype == "checkout.session.completed":
        sid = obj["id"]
        record = await db.payment_transactions.find_one({"session_id": sid})
        await db.payment_transactions.update_one(
            {"session_id": sid, "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": obj.get("payment_status", "paid"),
                      "stripe_subscription_id": obj.get("subscription"),
                      "updated_at": datetime.now(timezone.utc)}},
        )
        if record:
            await subs.subscribe(record["organization_id"], record["service"],
                                 record["interval"], record["currency"].upper())
            await db.subscriptions.update_many(
                {"organization_id": record["organization_id"], "status": {"$ne": "canceled"}},
                {"$set": {"stripe_subscription_id": obj.get("subscription"),
                          "trial": bool(record.get("trial"))}},
            )
    elif etype == "invoice.payment_failed":
        sub_id = obj.get("subscription")
        customer_email = obj.get("customer_email")
        if sub_id and customer_email:
            sub_doc = await db.subscriptions.find_one({"stripe_subscription_id": sub_id})
            org_id = sub_doc.get("organization_id") if sub_doc else None
            svc = sub_doc.get("service", "") if sub_doc else ""
            await send_internal(customer_email, "card_recovery",
                                {"service": svc}, organization_id=org_id)
    elif etype == "customer.subscription.deleted":
        sub_id = obj.get("id")
        if sub_id:
            await db.subscriptions.update_many(
                {"stripe_subscription_id": sub_id},
                {"$set": {"status": "canceled"}},
            )
    return {"status": "ok"}
