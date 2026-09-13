from typing import Literal, Optional

from pydantic import Field

from app.core.mongo import BaseDocument


class LedgerEntry(BaseDocument):
    project_id: str
    transaction_group: str
    account: str
    account_type: Literal["customer", "seller", "platform", "organization", "external"]
    direction: Literal["debit", "credit"]
    amount: int
    currency: str
    reference_type: str
    reference_id: str
    description: str = ""
    reversal_of: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
