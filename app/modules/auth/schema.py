from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.mongo import BaseDocument


class User(BaseDocument):
    email: str
    password_hash: str
    name: str
    role: Literal["owner", "admin", "developer", "viewer"] = "owner"
    organization_id: Optional[str] = None
    locale: str = "pt"
    mfa_enabled: bool = False
    banned: bool = False


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    company: str = Field(min_length=2, max_length=80)
    country: str = "BR"
    currency: str = "BRL"
    # A user must pick EXACTLY ONE service at signup and cannot change it later.
    service: Literal["payments", "marketplace", "email", "automation", "linkbio"] = "payments"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=6, max_length=128)


class UserPublic(BaseModel):
    id: str
    email: str
    name: str
    role: str
    organization_id: Optional[str] = None
    locale: str = "pt"
