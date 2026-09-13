import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


class Settings:
    APP_NAME = "LEAMSE"
    API_PREFIX = "/api"
    MONGO_URL = os.environ["MONGO_URL"]
    DB_NAME = os.environ["DB_NAME"]
    JWT_SECRET = os.environ["JWT_SECRET"]
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_MINUTES = 60
    REFRESH_TOKEN_DAYS = 7
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@leamse.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "leamse123")
    EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
    EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "LEAMSE")
    EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")
    PLATFORM_FEE_BPS = 290  # 2.9%
    PLATFORM_FEE_FIXED = 30  # cents


settings = Settings()

MODULES = ["payments", "marketplace", "email", "automation", "wallet", "analytics"]

SCOPES = [
    "payments:read",
    "payments:write",
    "marketplace:read",
    "marketplace:write",
    "email:send",
    "email:templates",
    "automation:read",
    "automation:write",
    "analytics:read",
    "webhooks:read",
]

# Services a user can pick at sign-up. linkbio is always enabled and needs no API key.
SERVICE_CATALOG = [
    {"id": "payments", "name": "LEAMSE Payments", "requires_api": True,
     "description": "Meio de pagamento próprio: checkout, cobranças, carteira e ledger."},
    {"id": "marketplace", "name": "Marketplace API", "requires_api": True,
     "description": "Pedidos, produtos, vendedores, clientes e split automático."},
    {"id": "email", "name": "Email API", "requires_api": True,
     "description": "Envio transacional com templates, variáveis e logs de entrega."},
    {"id": "automation", "name": "Automação", "requires_api": True,
     "description": "Agenda, CRM visual, Assistente WhatsApp com IA e fluxos automáticos."},
    {"id": "linkbio", "name": "Link na Bio", "requires_api": False, "always_on": True,
     "description": "Sua página pública que apresenta o negócio e vende para você."},
]

SELECTABLE_SERVICES = ["payments", "marketplace", "email", "automation"]

# Scopes granted to the default API key created for each service.
SERVICE_SCOPES = {
    "payments": ["payments:read", "payments:write", "webhooks:read"],
    "marketplace": ["marketplace:read", "marketplace:write", "webhooks:read"],
    "email": ["email:send", "email:templates"],
    "automation": ["automation:read", "automation:write"],
    "analytics": ["analytics:read"],
}

# Modules each service turns on inside the single production project.
SERVICE_MODULES = {
    "payments": ["payments", "wallet", "analytics"],
    "marketplace": ["marketplace", "analytics"],
    "email": ["email"],
    "automation": ["automation"],
}

# Kept for backward-compat with existing modules. Only production mode exists.
PLANS = {
    "free": {"modules": MODULES, "live_mode": True, "email_quota": 100000},
    "business": {"modules": MODULES, "live_mode": True, "email_quota": 500000},
    "enterprise": {"modules": MODULES, "live_mode": True, "email_quota": 5000000},
}
