import logging
import re
from html import escape

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.modules.email.guardrails import assert_safe_email
from app.modules.email.repository import EmailLogRepository, EmailTemplateRepository
from app.modules.email.schema import TemplateCreate
from app.modules.webhooks.service import WebhookService

logger = logging.getLogger("leamse.email")
EMAIL_BASE_URL = "https://integrations.emergentagent.com"

DEFAULT_TEMPLATES = [
    {
        "slug": "order_created",
        "name": "Order created",
        "subject": "Your order {{order}} is confirmed",
        "html": "<table role=\"presentation\" width=\"100%\"><tr><td style=\"padding:24px;font-family:Arial,sans-serif\">"
                "<h2 style=\"margin:0 0 12px\">Hi {{name}},</h2>"
                "<p>Your order <strong>{{order}}</strong> was confirmed and is being processed.</p>"
                "<p style=\"font-size:12px;color:#888\">Sent by LEAMSE. We never ask for your password or card "
                "details by email.</p></td></tr></table>",
        "variables": ["name", "order"],
    },
    {
        "slug": "payment_receipt",
        "name": "Payment receipt",
        "subject": "Payment received - {{amount}}",
        "html": "<table role=\"presentation\" width=\"100%\"><tr><td style=\"padding:24px;font-family:Arial,sans-serif\">"
                "<h2 style=\"margin:0 0 12px\">Payment confirmed</h2>"
                "<p>Hi {{name}}, we received your payment of <strong>{{amount}}</strong>.</p>"
                "<p style=\"font-size:12px;color:#888\">Sent by LEAMSE.</p></td></tr></table>",
        "variables": ["name", "amount"],
    },
    {
        "slug": "welcome",
        "name": "Welcome",
        "subject": "Welcome to LEAMSE",
        "html": "<table role=\"presentation\" width=\"100%\"><tr><td style=\"padding:24px;font-family:Arial,sans-serif\">"
                "<h2 style=\"margin:0 0 12px\">Welcome, {{name}}!</h2>"
                "<p>Your LEAMSE workspace is ready. Payments, marketplace and email in one API.</p>"
                "<p style=\"font-size:12px;color:#888\">Sent by LEAMSE.</p></td></tr></table>",
        "variables": ["name"],
    },
]


def render(template: str, variables: dict) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1).strip()
        return escape(str(variables.get(key, "")))

    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", replace, template)


class EmailService:
    def __init__(self) -> None:
        self.templates = EmailTemplateRepository()
        self.logs = EmailLogRepository()
        self.webhooks = WebhookService()

    async def seed_templates(self, project_id: str) -> None:
        for t in DEFAULT_TEMPLATES:
            existing = await self.templates.find_one({"project_id": project_id, "slug": t["slug"]})
            if not existing:
                await self.templates.insert({**t, "project_id": project_id, "text": ""})

    async def create_template(self, project_id: str, payload: TemplateCreate) -> dict:
        if await self.templates.find_one({"project_id": project_id, "slug": payload.slug}):
            raise HTTPException(status_code=409, detail="Template slug already exists")
        doc = await self.templates.insert({**payload.model_dump(), "project_id": project_id})
        doc["id"] = doc.pop("_id")
        return doc

    async def list_templates(self, project_id: str) -> list[dict]:
        await self.seed_templates(project_id)
        return await self.templates.find_many({"project_id": project_id}, limit=100)

    async def update_template(self, project_id: str, template_id: str, changes: dict) -> dict:
        tpl = await self.templates.update(template_id, changes, extra={"project_id": project_id})
        if not tpl:
            raise HTTPException(status_code=404, detail="Template not found")
        return tpl

    async def delete_template(self, project_id: str, template_id: str) -> dict:
        await self.templates.delete(template_id, extra={"project_id": project_id})
        return {"status": "deleted"}

    async def list_logs(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.logs.find_many({"project_id": project_id}, limit=limit, skip=skip)

    async def stats(self, project_id: str) -> dict:
        pipeline = [
            {"$match": {"project_id": project_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        rows = await self.logs.aggregate(pipeline)
        by_status = {r["_id"]: r["count"] for r in rows}
        total = sum(by_status.values())
        return {
            "total": total,
            "sent": by_status.get("sent", 0),
            "failed": by_status.get("failed", 0),
            "queued": by_status.get("queued", 0),
            "delivery_rate": round((by_status.get("sent", 0) / total) * 100, 2) if total else 0.0,
        }

    async def send(self, project_id: str, to: str, template_slug: str, variables: dict) -> dict:
        await self.seed_templates(project_id)
        template = await self.templates.find_one({"project_id": project_id, "slug": template_slug})
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        subject = render(template["subject"], variables)
        html = render(template["html"], variables)
        log = await self.logs.insert({"project_id": project_id, "template_slug": template_slug, "to": to,
                                       "subject": subject, "status": "queued", "variables": variables,
                                       "attempts": 0})
        log_id = log.pop("_id")
        provider_id, error = await self._deliver(to, subject, html)
        status = "sent" if provider_id else "failed"
        await self.logs.update(log_id, {"status": status, "provider_id": provider_id,
                                        "error": error, "attempts": 1})
        if status == "sent":
            await self.webhooks.dispatch(project_id, "email.sent", {"email_id": log_id, "to": to,
                                                                    "template": template_slug})
        return {"id": log_id, "to": to, "subject": subject, "status": status,
                "provider_id": provider_id, "error": error}

    async def resend(self, project_id: str, log_id: str) -> dict:
        log = await self.logs.get(log_id, extra={"project_id": project_id})
        if not log:
            raise HTTPException(status_code=404, detail="Email log not found")
        return await self.send(project_id, log["to"], log["template_slug"], log.get("variables", {}))

    async def _deliver(self, to: str, subject: str, html: str) -> tuple[str | None, str | None]:
        try:
            assert_safe_email(subject, html)
        except ValueError as exc:
            return None, str(exc)
        if not settings.EMAIL_KEY:
            return None, "Email provider not configured"
        payload = {"to": [to], "subject": subject, "html": html, "from_name": settings.EMAIL_FROM_NAME}
        if settings.EMAIL_REPLY_TO:
            payload["contact_email"] = settings.EMAIL_REPLY_TO
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{EMAIL_BASE_URL}/api/v1/email/send",
                                         headers={"X-Email-Key": settings.EMAIL_KEY}, json=payload)
            resp.raise_for_status()
            return resp.json().get("id"), None
        except httpx.HTTPStatusError as exc:
            logger.error("email send failed %s %s", exc.response.status_code, exc.response.text)
            return None, f"provider_error_{exc.response.status_code}"
        except Exception as exc:
            logger.error("email send error %s", exc)
            return None, "provider_unreachable"
