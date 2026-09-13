import logging

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import client, create_indexes
from app.core.errors import register_error_handlers
from app.modules.marketplace_public.routes import router as mp_router, shop_router
from app.modules.marketplace_public.admin import admin_router as mp_admin_router
from app.modules.marketplace_public.chat import chat_router as mp_chat_router
from app.modules.marketplace_public.seed import seed_mp_admin
from app.modules.marketplace_public.seed_products import seed_demo_products
from app.modules.admin.routes import router as admin_router
from app.modules.admin.coupons import router as admin_coupons_router, public_router as public_coupons_router
from app.modules.admin.metrics import router as admin_metrics_router
from app.modules.billing.routes import router as billing_router
from app.modules.cron.routes import router as cron_router
from app.modules.analytics.routes import router as analytics_router
from app.modules.auth.routes import router as auth_router
from app.modules.auth.service import AuthService
from app.modules.automation.routes import router as automation_router
from app.modules.email.routes import router as email_router
from app.modules.ledger.routes import router as ledger_router
from app.modules.linkbio.routes import router as linkbio_router
from app.modules.marketplace.routes import router as marketplace_router
from app.modules.meta.routes import router as meta_router
from app.modules.payments.routes import router as payments_router
from app.modules.subscriptions.routes import router as subscriptions_router, public_router as public_subscriptions_router
from app.modules.storage.routes import router as storage_router
from app.modules.storage.service import init_storage as _init_storage
from app.modules.tenancy.routes import router as tenancy_router
from app.modules.wallet.routes import router as wallet_router
from app.modules.webhooks.routes import router as webhooks_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("leamse")

DESCRIPTION = """
**LEAMSE** — Financial & Commerce Infrastructure.

One account, one project, one API key for Payments, Marketplace, Email, Wallet,
Ledger and Analytics. LEAMSE is its own payment provider.

Authentication: send your secret key as `Authorization: Bearer sk_live_...` or the
`X-Api-Key` header. Dashboard endpoints use the session cookie / JWT.
"""

app = FastAPI(
    title="LEAMSE API",
    version="1.0.0",
    description=DESCRIPTION,
    openapi_version="3.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

api_router = APIRouter(prefix=settings.API_PREFIX)
api_router.include_router(auth_router)
api_router.include_router(tenancy_router)
api_router.include_router(payments_router)
api_router.include_router(wallet_router)
api_router.include_router(ledger_router)
api_router.include_router(marketplace_router)
api_router.include_router(email_router)
api_router.include_router(webhooks_router)
api_router.include_router(analytics_router)
api_router.include_router(subscriptions_router)
api_router.include_router(public_subscriptions_router)
api_router.include_router(automation_router)
api_router.include_router(linkbio_router)
api_router.include_router(meta_router)
api_router.include_router(admin_router)
api_router.include_router(mp_router)
api_router.include_router(shop_router)
api_router.include_router(mp_admin_router)
api_router.include_router(mp_chat_router)
api_router.include_router(storage_router)
api_router.include_router(admin_coupons_router)
api_router.include_router(admin_metrics_router)
api_router.include_router(public_coupons_router)
api_router.include_router(billing_router)
api_router.include_router(cron_router)


@api_router.get("/", tags=["Meta"])
async def root():
    return {"service": "LEAMSE API", "version": "1.0.0", "status": "operational"}


@api_router.get("/health", tags=["Meta"])
async def health():
    return {"status": "healthy"}


app.include_router(api_router)
register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)


@app.on_event("startup")
async def on_startup():
    await create_indexes()
    await AuthService().seed_admin(settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD)
    await seed_mp_admin()
    await seed_demo_products()
    _init_storage()
    logger.info("LEAMSE API ready")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
