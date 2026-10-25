"""Direct Resend delivery (https://resend.com/docs/api-reference/emails/send-email)."""
import logging
import os

import httpx

logger = logging.getLogger("leamse.mailer")
RESEND_URL = "https://api.resend.com/emails"


async def send_via_resend(to: str, subject: str, html: str) -> tuple[str | None, str | None]:
    """Returns (provider_id, error). Never raises."""
    key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("RESEND_FROM_EMAIL", "")
    if not key or not sender:
        return None, "Email provider not configured (RESEND_API_KEY / RESEND_FROM_EMAIL)"
    from_name = os.environ.get("EMAIL_FROM_NAME", "LEAMSE")
    payload = {"from": f"{from_name} <{sender}>", "to": [to], "subject": subject, "html": html}
    reply_to = os.environ.get("EMAIL_REPLY_TO")
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(RESEND_URL, headers={"Authorization": f"Bearer {key}"}, json=payload)
        resp.raise_for_status()
        return resp.json().get("id"), None
    except httpx.HTTPStatusError as exc:
        logger.error("resend send failed %s %s", exc.response.status_code, exc.response.text)
        return None, f"provider_error_{exc.response.status_code}"
    except Exception as exc:  # noqa: BLE001
        logger.error("resend send error %s", exc)
        return None, "provider_unreachable"
