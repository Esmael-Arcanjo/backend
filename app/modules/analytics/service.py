from datetime import timedelta

from app.core.database import db
from app.core.mongo import now_utc


class AnalyticsService:
    async def overview(self, project_id: str, organization_id: str, days: int = 30) -> dict:
        since = now_utc() - timedelta(days=days)
        charges = await db.charges.find({"project_id": project_id}).to_list(length=5000)
        captured = [c for c in charges if c.get("status") in ("captured", "partially_refunded", "refunded")]
        gross = sum(c.get("amount_captured", 0) for c in captured)
        fees = sum(c.get("fee", 0) for c in captured)
        refunded = sum(c.get("amount_refunded", 0) for c in charges)
        attempts = len(charges)
        approval = round((len(captured) / attempts) * 100, 2) if attempts else 0.0
        currency = captured[0]["currency"] if captured else "BRL"

        orders = await db.orders.count_documents({"project_id": project_id})
        paid_orders = await db.orders.count_documents({"project_id": project_id, "status": "paid"})
        customers = await db.customers.count_documents({"project_id": project_id})
        sellers = await db.sellers.count_documents({"project_id": project_id})
        products = await db.products.count_documents({"project_id": project_id})
        emails = await db.email_logs.count_documents({"project_id": project_id})
        emails_sent = await db.email_logs.count_documents({"project_id": project_id, "status": "sent"})
        wallets = await db.wallets.find({"owner_type": "organization", "owner_id": organization_id}).to_list(length=20)
        available = sum(w.get("available", 0) for w in wallets)
        reserved = sum(w.get("reserved", 0) for w in wallets)

        series: dict[str, dict] = {}
        for c in captured:
            created = c.get("created_at")
            if not created:
                continue
            day = created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else str(created)[:10]
            bucket = series.setdefault(day, {"date": day, "volume": 0, "fees": 0, "count": 0})
            bucket["volume"] += c.get("amount_captured", 0)
            bucket["fees"] += c.get("fee", 0)
            bucket["count"] += 1
        timeseries = sorted(series.values(), key=lambda x: x["date"])[-days:]

        methods: dict[str, int] = {}
        for c in captured:
            key = (c.get("payment_method") or {}).get("type", "unknown")
            methods[key] = methods.get(key, 0) + c.get("amount_captured", 0)

        return {
            "currency": currency,
            "kpis": {
                "gross_volume": gross,
                "net_revenue": gross - fees - refunded,
                "platform_fees": fees,
                "refunded": refunded,
                "approval_rate": approval,
                "transactions": attempts,
                "orders": orders,
                "paid_orders": paid_orders,
                "customers": customers,
                "sellers": sellers,
                "products": products,
                "emails": emails,
                "emails_sent": emails_sent,
                "wallet_available": available,
                "wallet_reserved": reserved,
            },
            "timeseries": timeseries,
            "payment_methods": [{"name": k, "value": v} for k, v in methods.items()],
        }

    async def recent_activity(self, project_id: str, limit: int = 8) -> list[dict]:
        items: list[dict] = []
        for c in await db.charges.find({"project_id": project_id}).sort("created_at", -1).limit(limit).to_list(length=limit):
            items.append({"type": "charge", "title": f"Charge {c.get('status')}", "amount": c.get("amount"),
                          "currency": c.get("currency"), "created_at": c.get("created_at")})
        for o in await db.orders.find({"project_id": project_id}).sort("created_at", -1).limit(limit).to_list(length=limit):
            items.append({"type": "order", "title": f"Order {o.get('status')}", "amount": o.get("total"),
                          "currency": o.get("currency"), "created_at": o.get("created_at")})
        for e in await db.email_logs.find({"project_id": project_id}).sort("created_at", -1).limit(limit).to_list(length=limit):
            items.append({"type": "email", "title": f"Email {e.get('status')} to {e.get('to')}", "amount": None,
                          "currency": None, "created_at": e.get("created_at")})
        items.sort(key=lambda x: str(x.get("created_at")), reverse=True)
        return items[:limit]

    async def global_search(self, project_id: str, query: str) -> dict:
        rx = {"$regex": query, "$options": "i"}
        return {
            "customers": [{"id": str(d["_id"]), "label": d.get("name"), "sub": d.get("email")}
                          for d in await db.customers.find({"project_id": project_id, "$or": [{"name": rx}, {"email": rx}]}).limit(5).to_list(5)],
            "products": [{"id": str(d["_id"]), "label": d.get("name"), "sub": d.get("sku")}
                         for d in await db.products.find({"project_id": project_id, "$or": [{"name": rx}, {"sku": rx}]}).limit(5).to_list(5)],
            "sellers": [{"id": str(d["_id"]), "label": d.get("name"), "sub": d.get("email")}
                        for d in await db.sellers.find({"project_id": project_id, "$or": [{"name": rx}, {"email": rx}]}).limit(5).to_list(5)],
            "orders": [{"id": str(d["_id"]), "label": f"Order {str(d['_id'])[-6:]}", "sub": d.get("status")}
                       for d in await db.orders.find({"project_id": project_id}).limit(5).to_list(5)],
            "emails": [{"id": str(d["_id"]), "label": d.get("to"), "sub": d.get("template_slug")}
                       for d in await db.email_logs.find({"project_id": project_id, "to": rx}).limit(5).to_list(5)],
        }
