from typing import Optional

from pydantic import BaseModel, Field

from app.core.mongo import BaseDocument

EVENTS = [
    "payment.succeeded",
    "payment.failed",
    "refund.created",
    "order.created",
    "wallet.updated",
    "email.sent",
    "subscription.renewed",
]


class Webhook(BaseDocument):
    project_id: str
    url: str
    events: list[str] = Field(default_factory=list)
    secret: str
    enabled: bool = True
    description: str = ""


class WebhookCreate(BaseModel):
    url: str
    events: list[str] = Field(default_factory=lambda: EVENTS)
    description: str = ""


class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    events: Optional[list[str]] = None
    enabled: Optional[bool] = None
