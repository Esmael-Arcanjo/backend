from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _to_str(v: Any) -> Any:
    if isinstance(v, ObjectId):
        return str(v)
    return v


PyObjectId = Annotated[str, BeforeValidator(_to_str)]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return ObjectId("0" * 24)


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore", arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    created_at: datetime = Field(default_factory=now_utc)

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=True)
        data.pop("_id", None)
        return data

    @classmethod
    def from_mongo(cls, doc: Optional[dict]):
        if not doc:
            return None
        return cls.model_validate(doc)
