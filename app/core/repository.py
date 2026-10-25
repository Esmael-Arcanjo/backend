from typing import Any, Optional

from app.core.database import db
from app.core.mongo import now_utc, oid


class BaseRepository:
    """Thin async data-access layer shared by all modules (Repository Pattern)."""

    collection_name: str = ""

    def __init__(self, collection_name: Optional[str] = None) -> None:
        self.collection = db[collection_name or self.collection_name]

    async def insert(self, doc: dict) -> dict:
        doc.setdefault("created_at", now_utc())
        result = await self.collection.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc

    async def get(self, _id: str, extra: Optional[dict] = None) -> Optional[dict]:
        query: dict[str, Any] = {"_id": oid(_id)}
        if extra:
            query.update(extra)
        return self._clean(await self.collection.find_one(query))

    async def find_one(self, query: dict) -> Optional[dict]:
        return self._clean(await self.collection.find_one(query))

    async def find_many(self, query: dict, limit: int = 50, skip: int = 0, sort_field: str = "created_at") -> list[dict]:
        cursor = self.collection.find(query).sort(sort_field, -1).skip(skip).limit(limit)
        return [self._clean(d) for d in await cursor.to_list(length=limit)]

    async def count(self, query: dict) -> int:
        return await self.collection.count_documents(query)

    async def update(self, _id: str, changes: dict, extra: Optional[dict] = None) -> Optional[dict]:
        query: dict[str, Any] = {"_id": oid(_id)}
        if extra:
            query.update(extra)
        changes["updated_at"] = now_utc()
        await self.collection.update_one(query, {"$set": changes})
        return self._clean(await self.collection.find_one(query))

    async def delete(self, _id: str, extra: Optional[dict] = None) -> bool:
        query: dict[str, Any] = {"_id": oid(_id)}
        if extra:
            query.update(extra)
        result = await self.collection.delete_one(query)
        return result.deleted_count > 0

    async def aggregate(self, pipeline: list[dict]) -> list[dict]:
        return await self.collection.aggregate(pipeline).to_list(length=1000)

    @staticmethod
    def _clean(doc: Optional[dict]) -> Optional[dict]:
        if doc is None:
            return None
        doc["id"] = str(doc.pop("_id"))
        return doc
