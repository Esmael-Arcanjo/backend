from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import EmailStr, Field

from app.shared.models import StrictInput

LEAD_STATUSES = ["new", "contacted", "qualified", "lost", "converted"]
ACTIVITY_TYPES = ["call", "email", "meeting", "task", "note"]
CustomValue = Union[str, int, float, bool, None]


class LeadIn(StrictInput):
    name: str = Field(min_length=2, max_length=140)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    company: Optional[str] = Field(default=None, max_length=140)
    source: Optional[str] = Field(default=None, max_length=60)
    status: str = Field(default="new", pattern=r"^(new|contacted|qualified|lost)$")
    value_cents: int = Field(default=0, ge=0, le=10**12)
    notes: Optional[str] = Field(default=None, max_length=4000)
    custom_fields: Dict[str, CustomValue] = {}
    version: Optional[int] = None


class ContactIn(StrictInput):
    name: str = Field(min_length=2, max_length=140)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    company: Optional[str] = Field(default=None, max_length=140)
    position: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=4000)
    tags: List[str] = Field(default=[], max_length=20)
    version: Optional[int] = None


class OpportunityIn(StrictInput):
    title: str = Field(min_length=2, max_length=160)
    contact_id: Optional[str] = Field(default=None, max_length=24)
    value_cents: int = Field(default=0, ge=0, le=10**12)
    stage_key: str = Field(max_length=40)
    status: str = Field(default="open", pattern=r"^(open|won|lost)$")
    expected_close_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: Optional[str] = Field(default=None, max_length=4000)
    version: Optional[int] = None


class StageMoveIn(StrictInput):
    stage_key: str = Field(max_length=40)
    version: Optional[int] = None


class ActivityIn(StrictInput):
    type: str = Field(pattern=r"^(call|email|meeting|task|note)$")
    subject: str = Field(min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    due_at: Optional[datetime] = None
    done: bool = False
    related_type: Optional[str] = Field(default=None, pattern=r"^(lead|contact|opportunity)$")
    related_id: Optional[str] = Field(default=None, max_length=24)
    version: Optional[int] = None


class StageIn(StrictInput):
    key: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=60)
    probability: int = Field(ge=0, le=100)


class PipelineIn(StrictInput):
    name: str = Field(min_length=2, max_length=80)
    stages: List[StageIn] = Field(min_length=2, max_length=12)
