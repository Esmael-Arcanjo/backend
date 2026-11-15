from pymongo import AsyncMongoClient

from app.core.config.settings import settings

client: AsyncMongoClient = AsyncMongoClient(settings.mongo_url, tz_aware=True)
db = client[settings.db_name]
