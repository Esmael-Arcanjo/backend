from typing import Optional
from urllib.parse import urlparse

from pydantic import Field, field_validator

from app.core.config.settings import settings
from app.shared.models import StrictInput


class OrganizationIn(StrictInput):
    name: str = Field(min_length=2, max_length=140)
    document: Optional[str] = Field(default=None, max_length=30, pattern=r"^[0-9./\-A-Za-z ]*$")
    country: str = Field(default="BR", pattern=r"^[A-Z]{2}$")


class CheckoutIn(StrictInput):
    product_key: str = Field(max_length=40)
    plan_key: str = Field(max_length=40)
    segment: str = Field(max_length=40)
    organization: Optional[OrganizationIn] = None
    organization_id: Optional[str] = Field(default=None, max_length=24)
    origin_url: str = Field(max_length=300)

    @field_validator("origin_url")
    @classmethod
    def allowed_origin(cls, v: str) -> str:
        parsed = urlparse(v)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        allowed = set(settings.cors_origins) | {settings.public_app_url}
        if origin not in allowed:
            raise ValueError("Origem não autorizada")
        return origin
