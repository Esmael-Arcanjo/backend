import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def _req(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    def __init__(self) -> None:
        self.app_env = os.environ.get("APP_ENV", "development")
        self.mongo_url = _req("MONGO_URL")
        self.db_name = _req("DB_NAME")
        self.jwt_secret = _req("JWT_SECRET")
        self.data_encryption_key = _req("DATA_ENCRYPTION_KEY")
        self.cors_origins = [o.strip() for o in _req("CORS_ORIGINS").split(",") if o.strip()]
        self.public_app_url = _req("PUBLIC_APP_URL").rstrip("/")
        self.access_ttl_min = int(os.environ.get("ACCESS_TOKEN_TTL_MIN", "15"))
        self.refresh_ttl_days = int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "7"))
        self.cookie_secure = os.environ.get("COOKIE_SECURE", "true") == "true"
        self.cookie_domain = os.environ.get("COOKIE_DOMAIN") or None
        self.redis_url = os.environ.get("REDIS_URL", "")
        self.stripe_secret_key = _req("STRIPE_SECRET_KEY")
        self.stripe_webhook_secret = _req("STRIPE_WEBHOOK_SECRET")
        self.stripe_tax_mode = os.environ.get("STRIPE_TAX_MODE", "calc_only")
        self.smtp_host = os.environ.get("SMTP_HOST", "")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USER", "")
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self.email_from = os.environ.get("EMAIL_FROM", "leamse.com")
        self.require_email_verification = os.environ.get("REQUIRE_EMAIL_VERIFICATION", "false") == "true"


settings = Settings()
