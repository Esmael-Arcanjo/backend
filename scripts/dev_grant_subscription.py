"""QA/ops tool: grants an active subscription to an existing user without payment.
Usage: python scripts/dev_grant_subscription.py <email> [segment] [org name] [product] [plan]. Never expose via API."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.subscriptions.service import activate_subscription, register_provisioner  # noqa: E402
from app.database.mongo import db  # noqa: E402
from app.products.crm.services.crm_service import provision_crm  # noqa: E402
from app.products.link_bio.services.bio_service import provision_link_bio  # noqa: E402
from app.shared.models import utcnow  # noqa: E402


async def main(email: str, segment: str, org_name: str, product: str, plan: str):
    register_provisioner("crm", provision_crm)
    register_provisioner("link_bio", provision_link_bio)
    user = await db.users.find_one({"email": email.lower()})
    if not user:
        raise SystemExit("user not found")
    now = utcnow()
    existing = await db.organizations.find_one({"owner_id": user["_id"], "name": org_name})
    if existing and await db.subscriptions.find_one({"organization_id": existing["_id"], "product_key": product,
                                                     "is_current": True}):
        print("already granted", existing["_id"])
        return
    if existing:
        org_id = existing["_id"]
    else:
        org_id = (await db.organizations.insert_one({"name": org_name, "owner_id": user["_id"], "status": "active",
                                                     "country": "BR", "created_at": now, "updated_at": now})).inserted_id
        await db.organization_members.insert_one({"organization_id": org_id, "user_id": user["_id"],
                                                  "role": "owner", "status": "active", "created_at": now})
    sub_id = (await db.subscriptions.insert_one({
        "organization_id": org_id, "product_key": product, "plan_key": plan, "segment": segment,
        "status": "pending", "is_current": False, "created_by": user["_id"], "price_cents": 9900, "currency": "brl",
        "cancel_at_period_end": False, "created_at": now, "updated_at": now, "granted_manually": True})).inserted_id
    await activate_subscription(sub_id, None, None, "manual_grant")
    print("granted", org_id)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "agro",
                     sys.argv[3] if len(sys.argv) > 3 else "Fazenda Exemplo",
                     sys.argv[4] if len(sys.argv) > 4 else "crm", sys.argv[5] if len(sys.argv) > 5 else "starter"))
