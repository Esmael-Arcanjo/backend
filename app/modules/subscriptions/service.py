from datetime import timedelta

from fastapi import HTTPException

from app.core.database import db
from app.core.mongo import now_utc, oid as _oid
from app.core.repository import BaseRepository
from app.modules.tenancy.service import TenancyService
from app.modules.webhooks.service import WebhookService

# Prices in cents. `usage` services are pay-as-you-go and don't have plans.
DEFAULT_PRICING = {
    "payments": {"model": "usage", "note": "Pague conforme usa (fee por transação)"},
    "marketplace": {"model": "usage", "note": "Pague conforme usa (fee por venda)"},
    "email": {"model": "subscription", "currency": "USD", "monthly": 2500, "yearly": 25000},
    "automation": {"model": "subscription", "currency": "BRL", "monthly": 3000, "yearly": 35000},
    "linkbio": {"model": "subscription", "currency": "BRL", "monthly": 500, "yearly": 5000},
}


async def get_pricing() -> dict:
    doc = await db.pricing_config.find_one({"_id": "default"})
    if not doc:
        await db.pricing_config.insert_one({"_id": "default", "pricing": DEFAULT_PRICING})
        return DEFAULT_PRICING
    return doc.get("pricing", DEFAULT_PRICING)


async def set_pricing(new_pricing: dict) -> dict:
    current = await get_pricing()
    merged = {**current, **new_pricing}
    await db.pricing_config.update_one(
        {"_id": "default"}, {"$set": {"pricing": merged}}, upsert=True
    )
    return merged


class SubscriptionRepository(BaseRepository):
    collection_name = "subscriptions"


class InvoiceRepository(BaseRepository):
    collection_name = "invoices"


class SubscriptionService:
    def __init__(self) -> None:
        self.repo = SubscriptionRepository()
        self.invoices = InvoiceRepository()
        self.tenancy = TenancyService()
        self.webhooks = WebhookService()

    async def current(self, org_id: str) -> dict | None:
        return await self.repo.find_one({"organization_id": org_id, "status": {"$ne": "canceled"}})

    async def subscribe(self, org_id: str, service: str, interval: str, currency: str) -> dict:
        pricing = await get_pricing()
        entry = pricing.get(service, {})
        amount = entry.get(interval, 0) if entry.get("model") == "subscription" else 0
        existing = await self.current(org_id)
        period_end = now_utc() + timedelta(days=365 if interval == "yearly" else 30)
        data = {
            "organization_id": org_id, "service": service, "plan": service,
            "interval": interval, "amount": amount,
            "currency": (entry.get("currency") or currency).upper(),
            "status": "active",
            "trial_days": 0,
            "current_period_end": period_end.isoformat(),
        }
        if existing:
            sub = await self.repo.update(existing["id"], data)
        else:
            doc = await self.repo.insert(data)
            doc["id"] = doc.pop("_id")
            sub = doc
        if amount:
            await self.invoices.insert(
                {"organization_id": org_id, "subscription_id": sub["id"], "amount": amount,
                 "currency": data["currency"], "status": "paid",
                 "period_end": period_end.isoformat()}
            )
        # Unlock dashboard access once payment lands.
        await db.organizations.update_one(
            {"_id": _oid(org_id)}, {"$set": {"payment_pending": False}}
        )
        return sub

    async def grant_free(self, org_id: str, service: str, days: int = 30) -> dict:
        existing = await self.current(org_id)
        period_end = now_utc() + timedelta(days=days)
        data = {
            "organization_id": org_id, "service": service, "plan": service,
            "interval": "grant", "amount": 0, "currency": "BRL",
            "status": "active", "trial_days": days,
            "current_period_end": period_end.isoformat(), "granted_by_admin": True,
        }
        if existing:
            return await self.repo.update(existing["id"], data)
        doc = await self.repo.insert(data)
        doc["id"] = doc.pop("_id")
        return doc

    async def cancel(self, org_id: str) -> dict:
        sub = await self.current(org_id)
        if not sub:
            raise HTTPException(status_code=404, detail="No active subscription")
        return await self.repo.update(sub["id"], {"status": "canceled"})

    async def renew(self, org_id: str) -> dict:
        sub = await self.current(org_id)
        if not sub:
            raise HTTPException(status_code=404, detail="No active subscription")
        period_end = now_utc() + timedelta(days=365 if sub["interval"] == "yearly" else 30)
        return await self.repo.update(sub["id"], {"status": "active",
                                                  "current_period_end": period_end.isoformat()})

    async def list_invoices(self, org_id: str) -> list[dict]:
        return await self.invoices.find_many({"organization_id": org_id}, limit=50)
