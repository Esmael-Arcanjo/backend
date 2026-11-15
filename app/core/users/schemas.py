from typing import Optional

from pydantic import Field

from app.shared.models import StrictInput


def user_out(user: dict) -> dict:
    return {
        "id": str(user["_id"]), "name": user["name"], "email": user["email"],
        "email_verified": user.get("email_verified", False), "mfa_enabled": user.get("mfa_enabled", False),
        "phone": user.get("phone"), "locale": user.get("locale"), "timezone": user.get("timezone"),
        "notification_prefs": user.get("notification_prefs", {}),
        "created_at": user["created_at"].isoformat() if user.get("created_at") else None,
    }


class ProfileIn(StrictInput):
    name: str = Field(min_length=2, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    locale: str = Field(default="pt-BR", pattern=r"^(pt-BR|en-US|es-ES)$")
    timezone: str = Field(default="America/Sao_Paulo", max_length=60, pattern=r"^[A-Za-z_/+-]+$")


class NotificationPrefsIn(StrictInput):
    email_billing: bool
    email_security: bool
    email_product: bool


class MfaCodeIn(StrictInput):
    code: str = Field(min_length=6, max_length=6)


class MfaDisableIn(StrictInput):
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=1, max_length=128)
