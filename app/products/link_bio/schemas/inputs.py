from typing import List, Optional

from pydantic import Field, field_validator

from app.shared.models import StrictInput
from app.products.link_bio.services.socials import NETWORKS, normalize_url

HANDLE_PATTERN = r"^[a-z0-9][a-z0-9_.-]{2,29}$"
RESERVED = {"admin", "api", "www", "leamse", "suporte", "login", "entrar", "cadastro", "crm", "erp", "b"}


class SocialIn(StrictInput):
    network: str = Field(max_length=20)
    value: str = Field(min_length=1, max_length=300)

    @field_validator("network")
    @classmethod
    def known(cls, v: str) -> str:
        if v not in NETWORKS:
            raise ValueError("Rede social não suportada")
        return v


class ProfileIn(StrictInput):
    profile_type: str = Field(pattern=r"^(person|company)$")
    display_name: str = Field(min_length=2, max_length=80)
    title: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    location: Optional[str] = Field(default=None, max_length=160)
    show_map: bool = True
    socials: List[SocialIn] = Field(default=[], max_length=20)
    version: Optional[int] = None


class HandleIn(StrictInput):
    handle: str = Field(pattern=HANDLE_PATTERN)

    @field_validator("handle")
    @classmethod
    def not_reserved(cls, v: str) -> str:
        if v in RESERVED:
            raise ValueError("Endereço reservado")
        return v


class PublishIn(StrictInput):
    published: bool


class AvatarIn(StrictInput):
    data_url: str = Field(max_length=700_000)


class LinkIn(StrictInput):
    title: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=3, max_length=500)
    active: bool = True
    version: Optional[int] = None

    @field_validator("url")
    @classmethod
    def safe_url(cls, v: str) -> str:
        return normalize_url("website", v)


class ReorderIn(StrictInput):
    ids: List[str] = Field(max_length=200)


class ThemeIn(StrictInput):
    preset: str = Field(max_length=20)
    accent: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    button_style: str = Field(pattern=r"^(rounded|pill|square)$")


class ClickIn(StrictInput):
    link_id: Optional[str] = Field(default=None, max_length=24)
    network: Optional[str] = Field(default=None, max_length=20)
