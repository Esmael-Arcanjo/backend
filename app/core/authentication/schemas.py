import re

from pydantic import EmailStr, Field, field_validator

from app.shared.models import StrictInput


def _strong(v: str) -> str:
    if len(v) < 10 or not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("A senha deve ter ao menos 10 caracteres, com letras e números")
    return v


class RegisterIn(StrictInput):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(max_length=128)
    _v = field_validator("password")(_strong)


class LoginIn(StrictInput):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class MfaLoginIn(StrictInput):
    mfa_token: str = Field(max_length=2000)
    code: str = Field(min_length=6, max_length=6)


class TokenIn(StrictInput):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(StrictInput):
    email: EmailStr


class ResetPasswordIn(StrictInput):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(max_length=128)
    _v = field_validator("password")(_strong)


class ChangePasswordIn(StrictInput):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)
    _v = field_validator("new_password")(_strong)
