import asyncio
import json
import logging

import httpx
from fastapi import HTTPException

from app.core.mongo import now_utc
from app.core.security import random_token, sign_hmac
from app.modules.webhooks.repository import WebhookDeliveryRepository, WebhookRepository
from app.modules.webhooks.schema import EVENTS

logger = logging.getLogger("leamse.webhooks")
MAX_ATTEMPTS = 3


class WebhookService:
    def __init__(self) -> None:
        self.repo = WebhookRepository()
        self.deliveries = WebhookDeliveryRepository()

    async def create(self, project_id: str, url: str, events: list[str], description: str = "") -> dict:
        doc = await self.repo.insert(
            {
                "project_id": project_id,
                "url": url,
                "events": [e for e in events if e in EVENTS],
                "secret": f"whsec_{random_token(24)}",
                "enabled": True,
                "description": description,
            }
        )
        doc["id"] = doc.pop("_id")
        return doc

    async def list_all(self, project_id: str) -> list[dict]:
        return await self.repo.find_many({"project_id": project_id}, limit=100)

    async def update(self, webhook_id: str, project_id: str, changes: dict) -> dict:
        hook = await self.repo.update(webhook_id, changes, extra={"project_id": project_id})
        if not hook:
            raise HTTPException(status_code=404, detail="Webhook not found")
        return hook

    async def delete(self, webhook_id: str, project_id: str) -> dict:
        if not await self.repo.delete(webhook_id, extra={"project_id": project_id}):
            raise HTTPException(status_code=404, detail="Webhook not found")
        return {"status": "deleted"}

    async def deliveries_for(self, project_id: str, limit: int = 50) -> list[dict]:
        return await self.deliveries.find_many({"project_id": project_id}, limit=limit)

    async def dispatch(self, project_id: str, event: str, payload: dict) -> None:
        hooks = await self.repo.find_many({"project_id": project_id, "enabled": True}, limit=50)
        for hook in hooks:
            if event not in hook.get("events", []):
                continue
            asyncio.create_task(self._deliver(hook, event, payload))

    async def _deliver(self, hook: dict, event: str, payload: dict) -> None:
        body = json.dumps({"event": event, "created_at": now_utc().isoformat(), "data": payload}, default=str)
        signature = sign_hmac(hook["secret"], body)
        status_code = None
        error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        hook["url"],
                        content=body,
                        headers={"Content-Type": "application/json",
                                 "X-Leamse-Signature": signature,
                                 "X-Leamse-Event": event},
                    )
                status_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    break
            except Exception as exc:  # network failures are expected for user URLs
                error = str(exc)
            await asyncio.sleep(min(2 ** attempt, 8))
        await self.deliveries.insert({"project_id": hook["project_id"], "webhook_id": hook["id"], "event": event,
                                      "url": hook["url"], "status_code": status_code, "error": error,
                                      "signature": signature, "payload": payload,
                                      "status": "succeeded" if status_code and status_code < 300 else "failed"})
