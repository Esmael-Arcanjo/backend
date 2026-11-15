from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel

from app.shared.models import BaseDocument, PyObjectId


class _Tenant(BaseDocument):
    organization_id: PyObjectId
    created_at: datetime
    updated_at: datetime
    version: int = 1


class Social(BaseModel):
    network: str
    url: str


class BioPage(_Tenant):
    handle: str
    profile_type: str = "person"
    display_name: str
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    show_map: bool = True
    avatar: Optional[str] = None
    socials: List[Social] = []
    published: bool = True
    segment: str


class BioLink(_Tenant):
    page_id: PyObjectId
    title: str
    url: str
    position: int = 0
    active: bool = True
    clicks: int = 0


class BioTheme(_Tenant):
    preset: str = "grafite"
    accent: str = "#111827"
    button_style: str = "rounded"


class BioAnalytics(BaseDocument):
    organization_id: PyObjectId
    date: str
    views: int = 0
    link_clicks: Dict[str, int] = {}
    social_clicks: Dict[str, int] = {}
