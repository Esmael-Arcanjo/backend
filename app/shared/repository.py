from typing import Optional, Type

from bson import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from app.database.mongo import db
from app.shared.models import BaseDocument, to_oid, utcnow


class TenantRepository:
    """Every query is scoped by organization_id; cross-tenant ids answer 404."""

    def __init__(self, collection: str, model: Type[BaseDocument]):
        self.collection = collection
        self.model = model

    @property
    def col(self):
        return db[self.collection]

    async def list(self, org_id: ObjectId, filters: Optional[dict] = None, sort=("created_at", -1),
                   limit: int = 200, skip: int = 0):
        query = {**(filters or {}), "organization_id": org_id}
        cursor = self.col.find(query).sort(*sort).skip(skip).limit(limit)
        return [self.model.from_mongo(d) for d in await cursor.to_list(limit)]

    async def count(self, org_id: ObjectId, filters: Optional[dict] = None) -> int:
        return await self.col.count_documents({**(filters or {}), "organization_id": org_id})

    async def get(self, org_id: ObjectId, item_id: str):
        doc = await self.col.find_one({"_id": to_oid(item_id), "organization_id": org_id})
        if not doc:
            raise HTTPException(status_code=404, detail="Recurso não encontrado")
        return self.model.from_mongo(doc)

    async def exists(self, org_id: ObjectId, item_id: str) -> bool:
        if not ObjectId.is_valid(item_id):
            return False
        return await self.col.count_documents({"_id": ObjectId(item_id), "organization_id": org_id}, limit=1) > 0

    async def create(self, org_id: ObjectId, data: dict, user_id: ObjectId):
        now = utcnow()
        doc = {**data, "organization_id": org_id, "created_by": user_id, "created_at": now,
               "updated_at": now, "version": 1}
        result = await self.col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return self.model.from_mongo(doc)

    async def update(self, org_id: ObjectId, item_id: str, data: dict, expected_version: Optional[int] = None):
        query = {"_id": to_oid(item_id), "organization_id": org_id}
        if expected_version is not None:
            query["version"] = expected_version
        doc = await self.col.find_one_and_update(
            query, {"$set": {**data, "updated_at": utcnow()}, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            if expected_version is not None and await self.exists(org_id, item_id):
                raise HTTPException(status_code=409, detail="Registro alterado por outro usuário. Recarregue.")
            raise HTTPException(status_code=404, detail="Recurso não encontrado")
        return self.model.from_mongo(doc)

    async def delete(self, org_id: ObjectId, item_id: str) -> None:
        result = await self.col.delete_one({"_id": to_oid(item_id), "organization_id": org_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Recurso não encontrado")
