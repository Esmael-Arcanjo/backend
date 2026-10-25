from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.mongo import BaseDocument


class Split(BaseModel):
    destination: str
    bps: int = Field(ge=0, le=10000)


class PaymentIntent(BaseDocument):
    project_id: str
    amount: int
    currency: str
    status: Literal["requires_payment_method", "requires_confirmation", "processing",
                    "requires_capture", "succeeded", "canceled", "failed"] = "requires_confirmation"
    capture_method: Literal["automatic", "manual"] = "automatic"
    description: str = ""
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    splits: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    client_secret: str = ""
    charge_id: Optional[str] = None


class Charge(BaseDocument):
    project_id: str
    payment_intent_id: str
    amount: int
    amount_captured: int = 0
    amount_refunded: int = 0
    currency: str
    status: Literal["authorized", "captured", "failed", "refunded", "partially_refunded"] = "authorized"
    payment_method: dict = Field(default_factory=dict)
    fee: int = 0
    net: int = 0
    ledger_group: Optional[str] = None
    risk_score: int = 0


class PaymentIntentCreate(BaseModel):
    amount: int = Field(gt=0)
    currency: str = "BRL"
    description: str = ""
    capture_method: Literal["automatic", "manual"] = "automatic"
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    splits: list[Split] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class PaymentMethod(BaseModel):
    type: Literal["card", "pix", "boleto", "wallet", "bank_transfer"] = "card"
    card_number: Optional[str] = None
    holder_name: Optional[str] = None
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None
    cvc: Optional[str] = None


class ChargeCreate(BaseModel):
    payment_intent_id: str
    payment_method: PaymentMethod = PaymentMethod()


class CaptureRequest(BaseModel):
    amount: Optional[int] = Field(default=None, gt=0)


class RefundCreate(BaseModel):
    charge_id: str
    amount: Optional[int] = Field(default=None, gt=0)
    reason: str = "requested_by_customer"


class PaymentLinkCreate(BaseModel):
    amount: int = Field(gt=0)
    currency: str = "BRL"
    title: str
    description: str = ""
    mode: Literal["payment", "subscription"] = "payment"
