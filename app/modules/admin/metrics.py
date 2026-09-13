"""Admin timeseries metrics for the dashboard chart."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from app.core.database import db
from app.core.deps import require_role

router = APIRouter(prefix="/admin/metrics", tags=["Admin - Metrics"])


@router.get("/timeseries")
async def timeseries(_: dict = Depends(require_role("admin"))):
    """Return last 12 months revenue + subscription counts + trial→paid conversion."""
    now = datetime.now(timezone.utc)
    months = []
    for i in range(11, -1, -1):
        # First day of the month, 12 buckets back.
        y = now.year
        m = now.month - i
        while m <= 0:
            m += 12; y -= 1
        start = datetime(y, m, 1, tzinfo=timezone.utc)
        nm = m + 1; ny = y
        if nm > 12: nm = 1; ny += 1
        end = datetime(ny, nm, 1, tzinfo=timezone.utc)
        months.append({"label": start.strftime("%b/%y"), "start": start, "end": end})

    # Revenue = sum of paid invoices per month (invoices.status="paid")
    series = []
    for b in months:
        rev_docs = await db.invoices.find(
            {"status": "paid",
             "period_end": {"$gte": b["start"].isoformat(), "$lt": b["end"].isoformat()}},
            limit=5000,
        ).to_list(5000)
        revenue_cents = sum(int(r.get("amount", 0) or 0) for r in rev_docs)
        new_subs = await db.subscriptions.count_documents(
            {"created_at": {"$gte": b["start"], "$lt": b["end"]}}
        )
        series.append({
            "month": b["label"],
            "revenue": round(revenue_cents / 100, 2),
            "new_subscriptions": new_subs,
        })

    # Trial conversion: trials that became paid vs total trials
    total_trials = await db.subscriptions.count_documents({"trial": True})
    trials_paid = await db.subscriptions.count_documents({"trial": True, "status": "active"})
    conversion = round((trials_paid / total_trials) * 100, 1) if total_trials else 0.0

    active_by_service = {}
    async for row in db.subscriptions.aggregate([
        {"$match": {"status": "active"}},
        {"$group": {"_id": "$service", "count": {"$sum": 1}}},
    ]):
        active_by_service[row["_id"] or "unknown"] = row["count"]

    return {
        "series": series,
        "trial_conversion": {"total_trials": total_trials, "trials_paid": trials_paid, "pct": conversion},
        "active_by_service": active_by_service,
    }
