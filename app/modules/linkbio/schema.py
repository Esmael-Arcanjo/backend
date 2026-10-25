from typing import Optional

from pydantic import BaseModel, Field

from app.core.mongo import BaseDocument


class BioLink(BaseModel):
    label: str
    url: str
    icon: str = "link"


class BioProduct(BaseModel):
    title: str
    price: str = ""
    url: str = ""


class BioPage(BaseDocument):
    organization_id: str
    slug: str
    display_name: str = ""
    headline: str = ""
    bio: str = ""
    avatar_url: str = ""
    cover_url: str = ""
    custom_domain: str = ""
    accent: str = "#F97316"
    theme: str = "light"
    whatsapp: str = ""
    links: list[dict] = Field(default_factory=list)
    products: list[dict] = Field(default_factory=list)
    published: bool = True
    views: int = 0


class BioUpdate(BaseModel):
    slug: Optional[str] = None
    display_name: Optional[str] = None
    headline: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    custom_domain: Optional[str] = None
    accent: Optional[str] = None
    theme: Optional[str] = None
    whatsapp: Optional[str] = None
    links: Optional[list[BioLink]] = None
    products: Optional[list[BioProduct]] = None
    published: Optional[bool] = None
