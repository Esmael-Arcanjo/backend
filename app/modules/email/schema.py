from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.mongo import BaseDocument


class EmailTemplate(BaseDocument):
    project_id: str
    slug: str
    name: str
    subject: str
    html: str
    text: str = ""
    variables: list[str] = Field(default_factory=list)


class EmailLog(BaseDocument):
    project_id: str
    template_slug: str
    to: str
    subject: str
    status: str = "queued"
    provider_id: Optional[str] = None
    error: Optional[str] = None
    variables: dict = Field(default_factory=dict)
    attempts: int = 0


class TemplateCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=60)
    name: str
    subject: str
    html: str
    text: str = ""
    variables: list[str] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    html: Optional[str] = None
    text: Optional[str] = None


class SendRequest(BaseModel):
    """Callers pass a recipient reference + template slug + variables — never raw HTML."""
    to: EmailStr
    template: str
    variables: dict = Field(default_factory=dict)
