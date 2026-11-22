import logging

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from app.core.audit.service import audit
from app.core.authentication.deps import get_current_user
from app.core.authorization.deps import resolve_product_context
from app.core.billing.schemas import CheckoutIn
from app.core.config.settings import settings
from app.core.products_catalog.catalog_data import lookup_key
from app.core.security.rate_limit import rate_limit
from app.core.subscriptions import service as subs
from app.database.mongo import db
from app.integrations.stripe import client as stripe_client
from app.shared.models import to_oid, utcnow

logger = logging.getLogger("billing")
router = APIRouter(tags=["billing"])


async def _resolve_organization(body: CheckoutIn, user: dict) -> ObjectId:
    now = utcnow()
    if body.organization_id:
        org_id = to_oid(body.organization_id)
        member = await db.organization_members.find_one({"organization_id": org_id, "user_id": user["_id"],
                                                         "role": "owner", "status": "active"})
        if not member:
            raise HTTPException(status_code=403, detail="Apenas o proprietário pode contratar para esta organização")
        return org_id
    if not body.organization:
        raise HTTPException(status_code=422, detail="Informe os dados da organização")
    reusable = await db.organizations.find_one({"owner_id": user["_id"], "status": "active",
                                               "name": body.organization.name})
    if reusable and not await db.subscriptions.find_one({"organization_id": reusable["_id"], "price_cents": {"$gt": 0},
                                                         "product_key": body.product_key, "is_current": True}):
        await db.subscriptions.update_many({"organization_id": reusable["_id"], "product_key": body.product_key,
                                            "status": "pending"}, {"$set": {"status": "expired",
                                                                            "status_reason": "superseded"}})
        return reusable["_id"]
    result = await db.organizations.insert_one({**body.organization.model_dump(), "owner_id": user["_id"],
                                                "status": "active", "created_at": now, "updated_at": now})
    await db.organization_members.insert_one({"organization_id": result.inserted_id, "user_id": user["_id"],
                                              "role": "owner", "status": "active", "created_at": now})
    return result.inserted_id


@router.post("/api/v1/billing/checkout", dependencies=[rate_limit("checkout", 20, 3600)])
async def create_checkout(body: CheckoutIn, request: Request, user: dict = Depends(get_current_user)):
    if settings.require_email_verification and not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Confirme seu e-mail antes de contratar")
    product = await db.products.find_one({"key": body.product_key})
    if not product or product["status"] != "available":
        raise HTTPException(status_code=400, detail="Produto indisponível para contratação")
    if body.segment not in product["supported_segments"]:
        raise HTTPException(status_code=400, detail="Segmento não suportado por este produto")
    plan = await db.plans.find_one({"product_key": body.product_key, "plan_key": body.plan_key, "active": True})
    if not plan:
        raise HTTPException(status_code=400, detail="Plano inválido")
    org_id = await _resolve_organization(body, user)
    current = await db.subscriptions.find_one({"organization_id": org_id, "product_key": body.product_key,
                                               "is_current": True})
    if current and current.get("price_cents", 0) > 0 and current.get("billing_method") not in ("pix", "grant"):
        if not current.get("stripe_subscription_id") or plan["price_cents"] == 0 or body.payment_method == "pix":
            raise HTTPException(status_code=409, detail="Para trocar este plano use cartão; para o Grátis, cancele a assinatura atual")
        if current["plan_key"] == body.plan_key:
            raise HTTPException(status_code=409, detail="Você já está neste plano")
        stripe_client.change_plan(current["stripe_subscription_id"], lookup_key(body.product_key, body.plan_key, plan["interval"]))
        await db.subscriptions.update_one({"_id": current["_id"]}, {"$set": {
            "plan_key": body.plan_key, "price_cents": plan["price_cents"], "interval": plan["interval"],
            "cancel_at_period_end": False, "updated_at": utcnow()}})
        await audit("subscription.plan_changed", user_id=user["_id"], organization_id=org_id, product_key=body.product_key,
                    target_type="subscription", target_id=str(current["_id"]), request=request,
                    metadata={"from": current["plan_key"], "to": body.plan_key})
        return {"checkout_url": None, "activated": True, "changed": True, "slug": product["slug"]}
    if current and plan["price_cents"] == 0:
        raise HTTPException(status_code=409, detail="Esta organização já possui este produto")
    pix = body.payment_method == "pix" and plan["price_cents"] > 0
    now = utcnow()
    sub = {"organization_id": org_id, "product_key": body.product_key, "plan_key": body.plan_key,
           "segment": body.segment, "status": "pending", "is_current": False, "created_by": user["_id"],
           "price_cents": plan["price_cents"], "currency": plan["currency"], "cancel_at_period_end": False,
           "billing_method": "pix" if pix else ("free" if plan["price_cents"] == 0 else "card"),
           "interval": plan["interval"], "created_at": now, "updated_at": now}
    sub_id = (await db.subscriptions.insert_one(sub)).inserted_id
    if plan["price_cents"] == 0:
        await subs.activate_subscription(sub_id, None, None, "free_plan")
        await audit("billing.free_plan_activated", user_id=user["_id"], organization_id=org_id,
                    product_key=body.product_key, target_type="subscription", target_id=str(sub_id), request=request)
        return {"checkout_url": None, "activated": True, "slug": product["slug"]}
    metadata = {"subscription_id": str(sub_id), "organization_id": str(org_id), "user_id": str(user["_id"]),
                "product_key": body.product_key}
    if pix:
        session = stripe_client.create_pix_checkout(plan["price_cents"], f"{product['name']} — {plan['name']}",
                                                    body.origin_url, user["email"], metadata)
    else:
        session = stripe_client.create_subscription_checkout(
            lookup_key(body.product_key, body.plan_key, plan["interval"]), body.origin_url, user["email"], metadata)
    await db.payment_records.insert_one({
        "stripe_session_id": session.id, "subscription_id": sub_id, "organization_id": org_id,
        "user_id": user["_id"], "product_key": body.product_key, "amount": float(plan["price_cents"]) / 100,
        "currency": plan["currency"], "status": "initiated", "payment_status": "pending", "created_at": now})
    await audit("billing.checkout_created", user_id=user["_id"], organization_id=org_id,
                product_key=body.product_key, target_type="subscription", target_id=str(sub_id), request=request)
    return {"checkout_url": session.url, "session_id": session.id}


@router.get("/api/v1/billing/checkout/{session_id}/status")
async def checkout_status(session_id: str, user: dict = Depends(get_current_user)):
    record = await db.payment_records.find_one({"stripe_session_id": session_id, "user_id": user["_id"]})
    if not record:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    if record["payment_status"] != "paid":
        session = stripe_client.retrieve_session(session_id)
        if session and (session.payment_status == "paid" or session.status == "complete"):
            await db.payment_records.update_one({"_id": record["_id"], "payment_status": {"$ne": "paid"}},
                                                {"$set": {"payment_status": "paid", "status": "completed",
                                                          "updated_at": utcnow()}})
            await subs.activate_subscription(record["subscription_id"], session.subscription, session.customer,
                                             "status_check")
        elif session and session.status == "expired":
            await db.payment_records.update_one({"_id": record["_id"]}, {"$set": {"payment_status": "expired",
                                                                                 "status": "expired"}})
            await db.subscriptions.update_one({"_id": record["subscription_id"], "status": "pending"},
                                              {"$set": {"status": "expired"}})
    record = await db.payment_records.find_one({"_id": record["_id"]})
    sub = await db.subscriptions.find_one({"_id": record["subscription_id"]})
    product = await db.products.find_one({"key": sub["product_key"]})
    return {"session_id": session_id, "payment_status": record["payment_status"],
            "subscription_status": sub["status"], "product_key": sub["product_key"], "slug": product["slug"]}


@router.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    try:
        event = stripe_client.construct_event(payload, request.headers.get("stripe-signature", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="Assinatura inválida")
    try:
        await db.subscription_events.insert_one({"stripe_event_id": event["id"], "type": event["type"],
                                                 "event_created": event["created"], "created_at": utcnow()})
    except DuplicateKeyError:
        return {"status": "duplicate"}
    obj, kind = event["data"]["object"], event["type"]
    if (kind == "checkout.session.completed" and obj.get("payment_status") == "paid") \
            or kind == "checkout.session.async_payment_succeeded":
        record = await db.payment_records.find_one({"stripe_session_id": obj["id"]})
        if record:
            await db.payment_records.update_one({"_id": record["_id"]}, {"$set": {"payment_status": "paid",
                                                                                 "status": "completed"}})
            await subs.activate_subscription(record["subscription_id"], obj.get("subscription"),
                                             obj.get("customer"), "webhook")
    elif kind == "checkout.session.expired":
        await db.payment_records.update_one({"stripe_session_id": obj["id"], "payment_status": {"$ne": "paid"}},
                                            {"$set": {"payment_status": "expired", "status": "expired"}})
    elif kind in {"customer.subscription.updated", "customer.subscription.deleted"}:
        status = "canceled" if kind.endswith("deleted") else obj.get("status")
        await subs.apply_stripe_status(obj["id"], status, event["created"], obj.get("current_period_end"),
                                       obj.get("cancel_at_period_end"))
    elif kind == "invoice.payment_failed" and obj.get("subscription"):
        await subs.apply_stripe_status(obj["subscription"], "past_due", event["created"], None, None)
    elif kind == "invoice.paid" and obj.get("subscription"):
        await subs.apply_stripe_status(obj["subscription"], "active", event["created"], None, None)
    return {"status": "ok"}


@router.get("/api/v1/billing/{product_key}/current")
async def my_current(product_key: str, user: dict = Depends(get_current_user)):
    """Current subscription the user owns for a product, so plan changes reuse org and segment."""
    orgs = [m["organization_id"] async for m in db.organization_members.find(
        {"user_id": user["_id"], "role": "owner", "status": "active"})]
    sub = await db.subscriptions.find_one({"organization_id": {"$in": orgs}, "product_key": product_key,
                                           "is_current": True})
    if not sub:
        return {"current": None}
    org = await db.organizations.find_one({"_id": sub["organization_id"]})
    return {"current": {"organization_id": str(sub["organization_id"]), "organization_name": org["name"] if org else "",
                        "segment": sub["segment"], "plan_key": sub["plan_key"], "status": sub["status"],
                        "billing_method": sub.get("billing_method", "card")}}


@router.get("/api/v1/billing/{product_key}/subscription")
async def subscription_detail(product_key: str, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "read")
    s = ctx.subscription
    plan = await db.plans.find_one({"product_key": product_key, "plan_key": s["plan_key"]})
    history = await db.payment_records.find({"organization_id": ctx.org_id, "product_key": product_key}) \
        .sort("created_at", -1).to_list(50)
    return {"subscription": {"id": str(s["_id"]), "status": s["status"], "plan_key": s["plan_key"],
                             "plan_name": plan["name"] if plan else s["plan_key"], "price_cents": s["price_cents"],
                             "currency": s["currency"], "segment": s["segment"],
                             "cancel_at_period_end": s.get("cancel_at_period_end", False),
                             "current_period_end": s.get("current_period_end"),
                             "activated_at": s["activated_at"].isoformat() if s.get("activated_at") else None},
            "history": [{"id": str(h["_id"]), "amount": h["amount"], "currency": h["currency"],
                         "payment_status": h["payment_status"], "created_at": h["created_at"].isoformat()}
                        for h in history],
            "can_manage": ctx.role == "owner"}


@router.post("/api/v1/billing/{product_key}/cancel")
async def cancel_subscription(product_key: str, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "billing")
    sid = ctx.subscription.get("stripe_subscription_id")
    if not sid:
        raise HTTPException(status_code=400, detail="Assinatura sem vínculo com o provedor")
    stripe_client.cancel_at_period_end(sid)
    await db.subscriptions.update_one({"_id": ctx.subscription["_id"]}, {"$set": {"cancel_at_period_end": True}})
    await audit("subscription.cancel_requested", user_id=user["_id"], organization_id=ctx.org_id,
                product_key=product_key, request=request)
    return {"ok": True}


@router.post("/api/v1/billing/{product_key}/resume")
async def resume_subscription(product_key: str, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "billing")
    sid = ctx.subscription.get("stripe_subscription_id")
    if not sid:
        raise HTTPException(status_code=400, detail="Assinatura sem vínculo com o provedor")
    stripe_client.resume(sid)
    await db.subscriptions.update_one({"_id": ctx.subscription["_id"]}, {"$set": {"cancel_at_period_end": False}})
    await audit("subscription.resumed", user_id=user["_id"], organization_id=ctx.org_id, product_key=product_key,
                request=request)
    return {"ok": True}
