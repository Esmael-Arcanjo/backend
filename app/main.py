import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.audit.router import router as audit_router
from app.core.authentication.router import router as auth_router
from app.core.billing.router import router as billing_router
from app.core.config.settings import settings
from app.core.organizations.router import router as org_router
from app.core.products_catalog.router import router as catalog_router, seed_catalog
from app.core.security.middleware import SecurityMiddleware
from app.core.subscriptions.router import router as subscriptions_router
from app.core.subscriptions.service import register_provisioner
from app.core.users.router import router as users_router
from app.database.indexes import ensure_indexes
from app.products.crm.services.crm_service import provision_crm
from app.products.link_bio.api.public_router import router as bio_public_router
from app.products.link_bio.services.bio_service import provision_link_bio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

PRODUCT_MODULES = ["crm", "erp", "email_api", "payments_api", "marketplace", "recebimento", "marketing", "chatbot",
                   "link_bio", "assinatura_docs", "rh"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes()
    await seed_catalog()
    register_provisioner("crm", provision_crm)
    register_provisioner("link_bio", provision_link_bio)
    yield


app = FastAPI(title="LEAMSE Platform API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
              redoc_url=None, lifespan=lifespan)

for r in [auth_router, users_router, catalog_router, subscriptions_router, billing_router, org_router, audit_router,
          bio_public_router]:
    app.include_router(r)
for module in PRODUCT_MODULES:
    app.include_router(importlib.import_module(f"app.products.{module}.api.router").router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "env": settings.app_env}


app.add_middleware(SecurityMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "X-CSRF-Token", "X-Organization-Id", "Authorization"])
