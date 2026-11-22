from pymongo import ASCENDING, DESCENDING, IndexModel

from app.database.mongo import db

DAY = 86400

PLATFORM_INDEXES = {
    "users": [IndexModel([("email", ASCENDING)], unique=True),
              IndexModel([("document", ASCENDING)], unique=True, name="one_account_per_document",
                         partialFilterExpression={"document": {"$type": "string"}})],
    "organizations": [IndexModel([("owner_id", ASCENDING)])],
    "organization_members": [
        IndexModel([("organization_id", ASCENDING), ("user_id", ASCENDING)], unique=True),
        IndexModel([("user_id", ASCENDING), ("status", ASCENDING)]),
    ],
    "organization_invites": [
        IndexModel([("token_hash", ASCENDING)], unique=True),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
    ],
    "products": [IndexModel([("key", ASCENDING)], unique=True)],
    "plans": [IndexModel([("product_key", ASCENDING), ("plan_key", ASCENDING)], unique=True)],
    "subscriptions": [
        IndexModel(
            [("organization_id", ASCENDING), ("product_key", ASCENDING)],
            unique=True,
            partialFilterExpression={"is_current": True},
            name="one_current_subscription_per_product",
        ),
        IndexModel([("stripe_subscription_id", ASCENDING)]),
        IndexModel([("created_by", ASCENDING)]),
    ],
    "subscription_events": [
        IndexModel([("stripe_event_id", ASCENDING)], unique=True, sparse=True),
        IndexModel([("subscription_id", ASCENDING), ("created_at", DESCENDING)]),
    ],
    "payment_records": [
        IndexModel([("stripe_session_id", ASCENDING)], unique=True, sparse=True),
        IndexModel([("organization_id", ASCENDING), ("created_at", DESCENDING)]),
    ],
    "sessions": [
        IndexModel([("user_id", ASCENDING), ("revoked_at", ASCENDING)]),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
    ],
    "email_tokens": [
        IndexModel([("token_hash", ASCENDING)], unique=True),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
    ],
    "audit_logs": [
        IndexModel([("organization_id", ASCENDING), ("product_key", ASCENDING), ("created_at", DESCENDING)]),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=365 * DAY),
    ],
    "product_permissions": [
        IndexModel([("organization_id", ASCENDING), ("user_id", ASCENDING), ("product_key", ASCENDING)], unique=True)
    ],
    "notifications": [
        IndexModel([("user_id", ASCENDING), ("product_key", ASCENDING), ("created_at", DESCENDING)]),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=180 * DAY),
    ],
    "email_outbox": [IndexModel([("created_at", ASCENDING)], expireAfterSeconds=30 * DAY)],
}

TENANT_COLLECTIONS = [
    "crm_leads", "crm_contacts", "crm_opportunities", "crm_activities", "crm_pipelines",
    "crm_messages", "crm_whatsapp", "crm_settings",
    "erp_products", "erp_inventory", "erp_purchases", "erp_sales", "erp_invoices",
    "email_domains", "email_messages", "email_templates", "email_api_keys", "email_events",
    "payment_intents", "payment_transactions", "payment_refunds", "payment_webhooks",
    "marketplace_sellers", "marketplace_products", "marketplace_orders",
    "receivables", "collection_records", "receivable_payments",
    "marketing_campaigns", "marketing_contacts", "marketing_automations", "marketing_metrics",
    "chatbot_bots", "chatbot_conversations", "chatbot_messages", "chatbot_channels",
    "bio_pages", "bio_links", "bio_themes", "bio_analytics",
    "doc_envelopes", "doc_documents", "doc_signers", "doc_events",
    "rh_employees", "rh_departments", "rh_time_records", "rh_leaves",
]

EXTRA_TENANT_INDEXES = {
    "crm_leads": [IndexModel([("organization_id", ASCENDING), ("status", ASCENDING)]),
                  IndexModel([("organization_id", ASCENDING), ("phone_normalized", ASCENDING)], unique=True,
                             name="one_lead_per_whatsapp",
                             partialFilterExpression={"phone_normalized": {"$type": "string"}})],
    "crm_messages": [IndexModel([("organization_id", ASCENDING), ("contact_id", ASCENDING), ("created_at", ASCENDING)]),
                     IndexModel([("wa_id", ASCENDING)], unique=True, name="one_wa_message",
                                partialFilterExpression={"wa_id": {"$type": "string"}})],
    "crm_opportunities": [IndexModel([("organization_id", ASCENDING), ("stage_key", ASCENDING)])],
    "crm_activities": [IndexModel([("organization_id", ASCENDING), ("done", ASCENDING), ("due_at", ASCENDING)])],
    "crm_pipelines": [IndexModel([("organization_id", ASCENDING)], unique=True)],
    "crm_contacts": [IndexModel([("organization_id", ASCENDING), ("email", ASCENDING)]),
                     IndexModel([("organization_id", ASCENDING), ("phone_normalized", ASCENDING)], unique=True,
                                name="one_contact_per_whatsapp",
                                partialFilterExpression={"phone_normalized": {"$type": "string"}})],
    "crm_whatsapp": [IndexModel([("organization_id", ASCENDING)], unique=True),
                     IndexModel([("webhook_secret", ASCENDING)], unique=True)],
    "crm_settings": [IndexModel([("organization_id", ASCENDING)], unique=True),
                     IndexModel([("webhook_token_hash", ASCENDING)])],
    "bio_pages": [IndexModel([("handle", ASCENDING)], unique=True),
                  IndexModel([("organization_id", ASCENDING)], unique=True, name="one_page_per_org")],
    "bio_links": [IndexModel([("organization_id", ASCENDING), ("position", ASCENDING)])],
    "bio_themes": [IndexModel([("organization_id", ASCENDING)], unique=True, name="one_theme_per_org")],
    "bio_analytics": [IndexModel([("organization_id", ASCENDING), ("date", ASCENDING)], unique=True,
                                  name="one_bucket_per_day")],
}


async def ensure_indexes() -> None:
    for name, models in PLATFORM_INDEXES.items():
        await db[name].create_indexes(models)
    for name in TENANT_COLLECTIONS:
        models = [IndexModel([("organization_id", ASCENDING), ("created_at", DESCENDING)])]
        models += EXTRA_TENANT_INDEXES.get(name, [])
        await db[name].create_indexes(models)
