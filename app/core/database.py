from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

client = AsyncIOMotorClient(settings.MONGO_URL)
db: AsyncIOMotorDatabase = client[settings.DB_NAME]


def get_db() -> AsyncIOMotorDatabase:
    return db


async def create_indexes() -> None:
    await db.users.create_index("email", unique=True)
    await db.login_attempts.create_index("identifier")
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.organizations.create_index("owner_id")
    await db.mp_users.create_index("email", unique=True)
    await db.mp_products.create_index([("seller_id", 1), ("active", 1)])
    await db.mp_products.create_index("category")
    await db.mp_orders.create_index([("buyer_id", 1), ("created_at", -1)])
    await db.mp_orders.create_index([("seller_id", 1), ("created_at", -1)])
    await db.mp_users.create_index("slug", unique=True, sparse=True)
    await db.mp_reviews.create_index([("product_id", 1), ("created_at", -1)])
    await db.mp_reviews.create_index([("buyer_id", 1), ("product_id", 1)], unique=True)
    await db.mp_chat_threads.create_index([("buyer_id", 1), ("seller_id", 1)], unique=True)
    await db.mp_chat_threads.create_index([("seller_id", 1), ("last_at", -1)])
    await db.mp_chat_threads.create_index([("buyer_id", 1), ("last_at", -1)])
    await db.mp_chat_messages.create_index([("thread_id", 1), ("created_at", 1)])
    await db.projects.create_index([("organization_id", 1), ("mode", 1)])
    await db.api_keys.create_index("secret_hash", unique=True)
    await db.api_keys.create_index("project_id")
    await db.wallets.create_index([("owner_type", 1), ("owner_id", 1), ("currency", 1)], unique=True)
    await db.ledger.create_index([("project_id", 1), ("created_at", -1)])
    await db.transactions.create_index([("project_id", 1), ("created_at", -1)])
    await db.transfers.create_index("project_id")
    await db.payment_intents.create_index([("project_id", 1), ("created_at", -1)])
    await db.charges.create_index([("project_id", 1), ("created_at", -1)])
    await db.refunds.create_index("charge_id")
    await db.settlements.create_index("project_id")
    await db.fees.create_index("charge_id")
    await db.stores.create_index("project_id")
    await db.sellers.create_index("project_id")
    await db.customers.create_index([("project_id", 1), ("email", 1)])
    await db.products.create_index([("project_id", 1), ("sku", 1)])
    await db.categories.create_index("project_id")
    await db.inventory.create_index("product_id")
    await db.orders.create_index([("project_id", 1), ("created_at", -1)])
    await db.coupons.create_index([("project_id", 1), ("code", 1)])
    await db.email_templates.create_index([("project_id", 1), ("slug", 1)], unique=True)
    await db.email_logs.create_index([("project_id", 1), ("created_at", -1)])
    await db.subscriptions.create_index("organization_id")
    await db.webhooks.create_index("project_id")
    await db.webhook_deliveries.create_index([("webhook_id", 1), ("created_at", -1)])
    await db.audit_logs.create_index([("organization_id", 1), ("created_at", -1)])
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.appointments.create_index([("project_id", 1), ("scheduled_at", 1)])
    await db.crm_contacts.create_index([("project_id", 1), ("stage", 1)])
    await db.automation_flows.create_index("project_id")
    await db.wa_messages.create_index([("project_id", 1), ("session_id", 1), ("created_at", 1)])
    await db.bio_pages.create_index("slug", unique=True)
    await db.bio_pages.create_index("organization_id")
    await db.currencies.create_index("code", unique=True)
    await db.exchange_rates.create_index([("base", 1), ("quote", 1)], unique=True)
