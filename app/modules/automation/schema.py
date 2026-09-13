from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.mongo import BaseDocument

STAGES = ["lead", "qualified", "proposal", "won", "lost"]
AppointmentStatus = Literal["scheduled", "confirmed", "cancelled", "done"]


class Appointment(BaseDocument):
    project_id: str
    customer_name: str
    contact: str = ""
    service_name: str = ""
    scheduled_at: str
    status: AppointmentStatus = "scheduled"
    notes: str = ""
    reminder_sent: bool = False


class AppointmentCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    contact: str = ""
    service_name: str = ""
    scheduled_at: str
    notes: str = ""


class AppointmentUpdate(BaseModel):
    customer_name: Optional[str] = None
    contact: Optional[str] = None
    service_name: Optional[str] = None
    scheduled_at: Optional[str] = None
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None


class Contact(BaseDocument):
    project_id: str
    name: str
    email: str = ""
    phone: str = ""
    stage: str = "lead"
    value: float = 0
    notes: str = ""


class ContactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = ""
    phone: str = ""
    stage: str = "lead"
    value: float = 0
    notes: str = ""


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    stage: Optional[str] = None
    value: Optional[float] = None
    notes: Optional[str] = None


class Flow(BaseDocument):
    project_id: str
    name: str
    trigger: str
    action: str
    active: bool = True
    runs: int = 0


class FlowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    trigger: str
    action: str
    active: bool = True


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    trigger: Optional[str] = None
    action: Optional[str] = None
    active: Optional[bool] = None


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str = Field(min_length=1, max_length=2000)
