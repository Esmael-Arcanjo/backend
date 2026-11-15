import logging
from typing import Optional

from bson import ObjectId
from fastapi import Request

from app.core.security.rate_limit import client_ip
from app.database.mongo import db
from app.shared.models import utcnow

logger = logging.getLogger("audit")


async def audit(action: str, *, user_id: Optional[ObjectId] = None, organization_id: Optional[ObjectId] = None,
                product_key: Optional[str] = None, target_type: Optional[str] = None,
                target_id: Optional[str] = None, metadata: Optional[dict] = None,
                request: Optional[Request] = None) -> None:
    await db.audit_logs.insert_one({
        "action": action,
        "user_id": user_id,
        "organization_id": organization_id,
        "product_key": product_key,
        "target_type": target_type,
        "target_id": target_id,
        "metadata": metadata or {},
        "ip": client_ip(request) if request else None,
        "user_agent": (request.headers.get("user-agent", "")[:200] if request else None),
        "created_at": utcnow(),
    })
    logger.info("audit action=%s org=%s product=%s", action, organization_id, product_key)
