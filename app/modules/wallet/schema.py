from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.mongo import BaseDocument


class Wallet(BaseDocument):
    owner_type: Literal["organization", "seller", "customer", "platform"]
    owner_id: str
    currency: str
    available: int = 0
    pending: int = 0
    reserved: int = 0
    project_id: Optional[str] = None


class WalletTransaction(BaseDocument):
    wallet_id: str
    project_id: Optional[str] = None
    type: str
    amount: int
    currency: str
    balance_after: int
    reference_type: str = ""
    reference_id: str = ""
    description: str = ""


class TransferRequest(BaseModel):
    destination_type: Literal["organization", "seller", "customer"] = "seller"
    destination_id: str
    amount: int = Field(gt=0)
    currency: str = "BRL"
    description: str = ""


class WalletOperation(BaseModel):
    amount: int = Field(gt=0)
    currency: str = "BRL"
    description: str = ""
