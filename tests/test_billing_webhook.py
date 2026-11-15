import hashlib
import hmac
import json
import time

from bson import ObjectId

from app.core.config.settings import settings
from app.database.mongo import db
from app.shared.models import utcnow
from tests.fixtures import new_session


def _signed(payload: dict):
    body = json.dumps(payload)
    ts = int(time.time())
    sig = hmac.new(settings.stripe_webhook_secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


async def test_signed_webhook_activates_subscription_once():
    s = await new_session()
    me = (await s.get("/api/v1/auth/me")).json()["user"]
    uid = ObjectId(me["id"])
    now = utcnow()
    org_id = (await db.organizations.insert_one({"name": "Webhook Org", "owner_id": uid, "status": "active"})).inserted_id
    await db.organization_members.insert_one({"organization_id": org_id, "user_id": uid, "role": "owner", "status": "active"})
    sub_id = (await db.subscriptions.insert_one({"organization_id": org_id, "product_key": "link_bio", "plan_key": "mensal",
                                                 "segment": "comercio", "status": "pending", "is_current": False,
                                                 "created_by": uid, "price_cents": 600, "currency": "brl",
                                                 "created_at": now, "updated_at": now})).inserted_id
    await db.payment_records.insert_one({"stripe_session_id": "cs_test_webhook1", "subscription_id": sub_id,
                                         "organization_id": org_id, "user_id": uid, "product_key": "link_bio",
                                         "amount": 6.0, "currency": "brl", "status": "initiated",
                                         "payment_status": "pending", "created_at": now})
    event = {"id": "evt_test_1", "object": "event", "type": "checkout.session.completed", "created": int(time.time()),
             "data": {"object": {"id": "cs_test_webhook1", "object": "checkout.session", "payment_status": "paid",
                                 "subscription": "sub_test_1", "customer": "cus_test_1"}}}
    body, sig = _signed(event)
    r = await s.http.post("/api/stripe/webhook", content=body, headers={"stripe-signature": sig, "content-type": "application/json"})
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    sub = await db.subscriptions.find_one({"_id": sub_id})
    assert sub["status"] == "active" and sub["is_current"] and sub["stripe_subscription_id"] == "sub_test_1"
    assert await db.bio_pages.count_documents({"organization_id": org_id}) == 1
    r2 = await s.http.post("/api/stripe/webhook", content=body, headers={"stripe-signature": sig, "content-type": "application/json"})
    assert r2.json()["status"] == "duplicate"
    cancel = {"id": "evt_test_2", "object": "event", "type": "customer.subscription.deleted", "created": int(time.time()) + 5,
              "data": {"object": {"id": "sub_test_1", "object": "subscription", "status": "canceled"}}}
    body3, sig3 = _signed(cancel)
    await s.http.post("/api/stripe/webhook", content=body3, headers={"stripe-signature": sig3, "content-type": "application/json"})
    sub = await db.subscriptions.find_one({"_id": sub_id})
    assert sub["status"] == "canceled" and not sub["is_current"]
