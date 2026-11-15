import logging
from typing import Awaitable, Callable, Dict, Optional

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.audit.service import audit
from app.core.users.router import notify
from app.database.mongo import db
from app.shared.models import utcnow

logger = logging.getLogger("subscriptions")

Provisioner = Callable[[dict], Awaitable[None]]
PROVISIONERS: Dict[str, Provisioner] = {}

STRIPE_STATUS_MAP = {"active": "active", "trialing": "active", "past_due": "past_due", "unpaid": "suspended",
                     "canceled": "canceled", "incomplete_expired": "expired", "paused": "suspended"}


def register_provisioner(product_key: str, fn: Provisioner) -> None:
    PROVISIONERS[product_key] = fn


async def activate_subscription(subscription_id: ObjectId, stripe_subscription_id: Optional[str],
                                stripe_customer_id: Optional[str], source: str) -> bool:
    """Idempotent: only a pending subscription transitions to active."""
    now = utcnow()
    try:
        sub = await db.subscriptions.find_one_and_update(
            {"_id": subscription_id, "status": "pending"},
            {"$set": {"status": "active", "is_current": True, "activated_at": now, "updated_at": now,
                      "stripe_subscription_id": stripe_subscription_id, "stripe_customer_id": stripe_customer_id}},
            return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        await db.subscriptions.update_one({"_id": subscription_id}, {"$set": {"status": "expired",
                                                                             "status_reason": "duplicate_current"}})
        logger.error("Duplicate current subscription blocked for %s", subscription_id)
        return False
    if not sub:
        return False
    await db.product_permissions.update_one(
        {"organization_id": sub["organization_id"], "user_id": sub["created_by"], "product_key": sub["product_key"]},
        {"$set": {"role": "owner", "updated_at": now}, "$setOnInsert": {"created_at": now}}, upsert=True)
    await db.payment_records.update_many({"subscription_id": subscription_id, "status": {"$ne": "paid"}},
                                         {"$set": {"status": "paid", "paid_at": now}})
    await db.subscription_events.insert_one({"subscription_id": subscription_id, "type": "activated",
                                             "source": source, "created_at": now})
    provisioner = PROVISIONERS.get(sub["product_key"])
    if provisioner:
        await provisioner(sub)
    await notify(sub["created_by"], "Assinatura ativada", f"Seu acesso ao plano {sub['plan_key']} foi liberado.",
                 sub["product_key"], sub["organization_id"])
    await audit("subscription.activated", user_id=sub["created_by"], organization_id=sub["organization_id"],
                product_key=sub["product_key"], target_type="subscription", target_id=str(subscription_id),
                metadata={"source": source})
    return True


async def apply_stripe_status(stripe_subscription_id: str, stripe_status: str, event_created: int,
                              period_end: Optional[int], cancel_at_period_end: Optional[bool]) -> None:
    """Out-of-order protection: ignore events older than the last applied one."""
    status = STRIPE_STATUS_MAP.get(stripe_status)
    if not status:
        return
    update = {"status": status, "last_event_at": event_created, "updated_at": utcnow()}
    if period_end:
        update["current_period_end"] = period_end
    if cancel_at_period_end is not None:
        update["cancel_at_period_end"] = cancel_at_period_end
    if status in {"canceled", "expired"}:
        update["is_current"] = False
    await db.subscriptions.update_one(
        {"stripe_subscription_id": stripe_subscription_id, "status": {"$ne": "pending"},
         "$or": [{"last_event_at": {"$exists": False}}, {"last_event_at": {"$lte": event_created}}]},
        {"$set": update})
