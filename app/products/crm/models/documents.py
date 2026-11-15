from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.shared.models import BaseDocument, PyObjectId


class _Tenant(BaseDocument):
    organization_id: PyObjectId
    created_by: Optional[PyObjectId] = None
    created_at: datetime
    updated_at: datetime
    version: int = 1


class Lead(_Tenant):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    source: Optional[str] = None
    status: str = "new"
    value_cents: int = 0
    notes: Optional[str] = None
    custom_fields: Dict[str, Any] = {}
    converted_contact_id: Optional[PyObjectId] = None
    converted_opportunity_id: Optional[PyObjectId] = None


class Contact(_Tenant):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = []


class Opportunity(_Tenant):
    title: str
    contact_id: Optional[PyObjectId] = None
    value_cents: int = 0
    stage_key: str
    status: str = "open"
    expected_close_date: Optional[str] = None
    notes: Optional[str] = None


class Activity(_Tenant):
    type: str
    subject: str
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    done: bool = False
    related_type: Optional[str] = None
    related_id: Optional[PyObjectId] = None


class Stage(BaseModel):
    key: str
    name: str
    probability: int


class Pipeline(_Tenant):
    name: str
    segment: str
    stages: List[Stage]
