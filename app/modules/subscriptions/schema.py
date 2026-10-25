from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.mongo import BaseDocument


class Subscription(BaseDocument):
    organization_id: str
    service: str = "payments"
    plan: str = "payments"
    interval: Literal["monthly", "yearly", "grant", "usage"] = "monthly"
    amount: int = 0
    currency: str = "BRL"
    status: Literal["trialing", "active", "past_due", "canceled"] = "active"
    trial_days: int = 0
    current_period_end: Optional[str] = None
    granted_by_admin: bool = False


class SubscriptionCreate(BaseModel):
    service: Literal["payments", "marketplace", "email", "automation", "linkbio"] = "email"
    interval: Literal["monthly", "yearly"] = "monthly"
    currency: str = "BRL"


class PricingUpdate(BaseModel):
    service: Literal["payments", "marketplace", "email", "automation", "linkbio"]
    monthly: Optional[int] = Field(None, ge=0)
    yearly: Optional[int] = Field(None, ge=0)
    currency: Optional[str] = None
