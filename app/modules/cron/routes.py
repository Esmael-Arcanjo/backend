"""Cron endpoint for scheduled platform tasks. Every route validates the shared
secret in constant time and enqueues background work via FastAPI BackgroundTasks."""
import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from app.core.database import db
from app.modules.email.internal import send_internal

router = APIRouter(prefix="/cron", tags=["Cron"])


def _authorize(auth: str) -> None:
    expected = os.environ.get("WEBHOOK_CRON_SECRET", "")
    if not expected:
        raise HTTPException(401, "Cron secret not configured")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    if not hmac.compare_digest(auth[7:], expected):
        raise HTTPException(401, "Unauthorized")


async def _process_trial_ending(run_id: str) -> None:
    """Scan trial subscriptions ending in ~2 days and send reminder emails."""
    seen = await db.cron_runs.find_one({"_id": run_id})
    if seen:
        return
    await db.cron_runs.insert_one({"_id": run_id, "kind": "trial_ending",
                                   "at": datetime.now(timezone.utc)})
    now = datetime.now(timezone.utc)
    target_start = now + timedelta(days=2)
    target_end = now + timedelta(days=3)
    subs = await db.subscriptions.find({
        "status": {"$in": ["active", "trialing"]},
        "trial": True,
    }, limit=500).to_list(500)
    for sub in subs:
        end = sub.get("current_period_end")
        if not end:
            continue
        try:
            dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if isinstance(end, str) else end
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if not (target_start <= dt <= target_end):
            continue
        if sub.get("trial_reminder_sent"):
            continue
        # Find the owner user's email.
        org = await db.organizations.find_one({"_id": _oid(sub["organization_id"])})
        if not org:
            continue
        owner = await db.users.find_one({"_id": _oid(org.get("owner_id", ""))})
        if not owner:
            continue
        days_left = max(1, (dt - now).days)
        await send_internal(
            owner["email"], "trial_ending",
            {"service": sub.get("service", ""), "days_left": days_left},
            organization_id=sub["organization_id"],
        )
        await db.subscriptions.update_one({"_id": sub["_id"]},
                                          {"$set": {"trial_reminder_sent": True}})


def _oid(value):
    from app.core.mongo import oid
    return oid(value)


@router.post("/trial-ending")
async def cron_trial_ending(
    background: BackgroundTasks,
    authorization: str = Header(""),
    x_webhook_id: str = Header(""),
):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _authorize(authorization)
    run_id = x_webhook_id or f"trial-{datetime.now(timezone.utc).isoformat()}"
    background.add_task(_process_trial_ending, run_id)
    return {"status": "queued", "run_id": run_id}
