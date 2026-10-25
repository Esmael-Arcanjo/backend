"""Idempotent seeding of the Marketplace admin account."""
import logging
import os
from datetime import datetime, timezone

from app.core.database import db
from app.core.security import hash_password

logger = logging.getLogger("leamse.mp.seed")

MP_ADMIN_EMAIL = os.environ.get("MP_ADMIN_EMAIL", "admin@wibaza.com")
MP_ADMIN_PASSWORD = os.environ.get("MP_ADMIN_PASSWORD", "WibazaAdmin2026!")
MP_ADMIN_NAME = "Wibaza Admin"


async def seed_mp_admin() -> None:
    email = MP_ADMIN_EMAIL.lower()
    existing = await db.mp_users.find_one({"email": email})
    if existing:
        # Ensure it's really an admin (self-heal if row was created as buyer/seller).
        if existing.get("user_type") != "admin":
            await db.mp_users.update_one(
                {"_id": existing["_id"]},
                {"$set": {"user_type": "admin", "banned": False}},
            )
            logger.info("MP admin promoted: %s", email)
        return
    await db.mp_users.insert_one({
        "email": email, "name": MP_ADMIN_NAME,
        "password_hash": hash_password(MP_ADMIN_PASSWORD),
        "user_type": "admin",
        "created_at": datetime.now(timezone.utc),
    })
    logger.info("MP admin seeded: %s", email)
