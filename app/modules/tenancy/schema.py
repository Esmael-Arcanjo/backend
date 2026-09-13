from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.core.mongo import BaseDocument


class Organization(BaseDocument):
    name: str
    owner_id: str
    country: str = "BR"
    default_currency: str = "BRL"
    plan: Literal["free", "business", "enterprise"] = "business"
    services: list[str] = Field(default_factory=list)


class Project(BaseDocument):
    organization_id: str
    name: str
    mode: Literal["test", "live"] = "test"
    modules: list[str] = Field(default_factory=list)


class ApiKey(BaseDocument):
    project_id: str
    name: str
    service: Optional[str] = None
    publishable_key: str
    secret_hash: str
    secret_preview: str
    scopes: list[str] = Field(default_factory=list)
    revoked: bool = False


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    default_currency: Optional[str] = None
    plan: Optional[Literal["free", "business", "enterprise"]] = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    mode: Literal["test", "live"] = "test"
    modules: list[str] = Field(default_factory=lambda: ["payments", "marketplace", "email", "wallet", "analytics"])


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    modules: Optional[list[str]] = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    scopes: Optional[list[str]] = None
    service: Optional[str] = None
