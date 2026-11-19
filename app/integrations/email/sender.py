import ipaddress
import logging
import os
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

import resend

from app.database.mongo import db
from app.shared.models import utcnow

logger = logging.getLogger("email")

# Configuração da API do Resend direto pelo .env
resend.api_key = os.environ.get("RESEND_API_KEY")

EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@leamse.com")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "LEAMSE")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)
_URL = re.compile(r"https://[^\s<]+")


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


def _render_html(body: str) -> str:
    """Server-side template: escaped text, https links turned into a button."""
    paragraphs = []
    for line in escape(body).split("\n"):
        line = _URL.sub(lambda m: (f'<a href="{m.group(0)}" style="display:inline-block;margin:8px 0;padding:10px 18px;'
                                   f'background:#0f766e;color:#ffffff;border-radius:999px;text-decoration:none;'
                                   f'font-weight:bold">Abrir link</a>'), line)
        paragraphs.append(f'<p style="margin:0 0 12px">{line}</p>' if line.strip() else "")
    return ('<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;'
            'font-size:15px;color:#111827">' + "".join(paragraphs) +
            f'<p style="font-size:12px;color:#888;margin-top:24px">Enviado por {escape(EMAIL_FROM_NAME)}. '
            'Nunca pedimos sua senha ou dados de cartão por e-mail.</p></td></tr></table>')


async def _send_resend(to: str, subject: str, html: str) -> str | None:
    _assert_safe_email(subject, html)
    
    params = {
        "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if EMAIL_REPLY_TO:
        params["reply_to"] = EMAIL_REPLY_TO

    # Chamada oficial assíncrona/direta do SDK do Resend
    response = resend.Emails.send(params)
    return response.get("id") if isinstance(response, dict) else getattr(response, "id", None)


async def send_email(to: str, subject: str, body: str, kind: str) -> None:
    """Sends via native Resend; a failed send is logged and recorded, never raised to the caller."""
    html = _render_html(body)
    delivery, provider_id = "sent", None
    try:
        provider_id = await _send_resend(to, subject, html)
    except Exception as e:
        delivery = "failed:error"
        logger.error("Email '%s' send error: %s", kind, e)
        
    redacted = re.sub(r"token=[^\s&]+", "token=[REDACTED]", body)
    await db.email_outbox.insert_one({"to": to, "subject": subject, "body": redacted, "kind": kind,
                                      "delivery": delivery, "provider_id": provider_id, "created_at": utcnow()})