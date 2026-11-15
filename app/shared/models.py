from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from bson import ObjectId
from fastapi import HTTPException
from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field

PyObjectId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, ObjectId) else v)]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_oid(value: Any, not_found: str = "Recurso não encontrado") -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not isinstance(value, str) or not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail=not_found)
    return ObjectId(value)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    id: Optional[PyObjectId] = Field(default=None, validation_alias=AliasChoices("_id", "id"))

    @classmethod
    def from_mongo(cls, doc: Optional[dict]):
        return cls.model_validate(doc) if doc else None

    def to_mongo(self) -> dict:
        data = self.model_dump(exclude={"id"})
        if self.id:
            data["_id"] = ObjectId(self.id)
        return data

    def out(self) -> dict:
        return self.model_dump(mode="json")
