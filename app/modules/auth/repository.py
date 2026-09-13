from typing import Optional

from app.core.mongo import now_utc
from app.core.repository import BaseRepository


class UserRepository(BaseRepository):
    collection_name = "users"

    async def by_email(self, email: str) -> Optional[dict]:
        return await self.find_one({"email": email.lower()})


class LoginAttemptRepository(BaseRepository):
    collection_name = "login_attempts"

    async def register_failure(self, identifier: str) -> int:
        doc = await self.collection.find_one_and_update(
            {"identifier": identifier},
            {"$inc": {"count": 1}, "$set": {"last_at": now_utc()}},
            upsert=True,
            return_document=True,
        )
        return doc.get("count", 1)

    async def clear(self, identifier: str) -> None:
        await self.collection.delete_many({"identifier": identifier})

    async def current(self, identifier: str) -> Optional[dict]:
        return await self.find_one({"identifier": identifier})


class ResetTokenRepository(BaseRepository):
    collection_name = "password_reset_tokens"
