import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import EmailStr, Field
from pymongo.errors import DuplicateKeyError

from app.core.security.rate_limit import rate_limit
from app.core.security.tokens import hash_token
from app.database.mongo import db
from app.products.crm.services.inbound import normalize_phone, site_org_id, upsert_inbound_lead
from app.shared.models import StrictInput, utcnow

logger = logging.getLogger("crm.public")
router = APIRouter(tags=["crm-public"])


class SiteLeadIn(StrictInput):
    name: str = Field(min_length=2, max_length=140)
    whatsapp: str = Field(min_length=8, max_length=30)
    city: Optional[str] = Field(default=None, max_length=100)
    intent: str = Field(default="contato", pattern=r"^(anunciar|comprar|contato)$")
    wants: Optional[str] = Field(default=None, max_length=500)
    price: Optional[str] = Field(default=None, max_length=60)
    email: Optional[EmailStr] = None
    source: str = Field(default="site", pattern=r"^(site|instagram)$")
    website: Optional[str] = Field(default=None, max_length=200)


@router.post("/api/leads", status_code=201, dependencies=[rate_limit("site-lead", 20, 3600)])
async def receive_lead(body: SiteLeadIn, x_webhook_token: Optional[str] = Header(default=None)):
    if body.website:
        return {"ok": True}  # honeypot filled by a bot
    if x_webhook_token:
        cfg = await db.crm_settings.find_one({"webhook_token_hash": hash_token(x_webhook_token)})
        if not cfg:
            raise HTTPException(status_code=401, detail="Token do webhook inválido")
        org_id = cfg["organization_id"]
    else:
        org_id = await site_org_id()
    fields = body.model_dump(include={"city", "intent", "wants", "price", "email"})
    _, created = await upsert_inbound_lead(org_id, body.source, body.name, body.whatsapp, fields)
    return {"ok": True, "created": created}


@router.get("/api/v1/public/listings")
async def listings():
    try:
        org_id = await site_org_id()
    except HTTPException:
        return {"items": []}
    docs = await db.crm_leads.find({"organization_id": org_id, "intent": "anunciar", "published": True}) \
        .sort("updated_at", -1).limit(60).to_list(60)
    return {"items": [{"id": str(d["_id"]), "title": d.get("wants") or "Anúncio", "city": d.get("city"),
                       "price": d.get("price"), "created_at": d["created_at"].isoformat()} for d in docs]}


def _text(message: dict) -> str:
    return (message.get("conversation") or (message.get("extendedTextMessage") or {}).get("text")
            or (message.get("imageMessage") or {}).get("caption") or "[mídia]")


async def _store(org_id, contact_id, phone: str, direction: str, text: str, wa_id: Optional[str]) -> None:
    try:
        await db.crm_messages.insert_one({"organization_id": org_id, "contact_id": contact_id, "phone": phone,
                                          "direction": direction, "text": text[:4000], "wa_id": wa_id,
                                          "created_at": utcnow()})
    except DuplicateKeyError:
        pass


@router.post("/api/webhooks/evolution/{secret}")
async def evolution_webhook(secret: str, request: Request):
    cfg = await db.crm_whatsapp.find_one({"webhook_secret": secret})
    if not cfg:
        raise HTTPException(status_code=404, detail="Not found")
    payload = await request.json()
    event = str(payload.get("event", "")).lower().replace("_", ".")
    data = payload.get("data") or {}
    if event == "connection.update":
        await db.crm_whatsapp.update_one({"_id": cfg["_id"]}, {"$set": {"status": data.get("state", "close")}})
        return {"ok": True}
    if event != "messages.upsert":
        return {"ok": True}
    for item in data if isinstance(data, list) else [data]:
        key = item.get("key") or {}
        jid = key.get("remoteJid") or ""
        if not jid.endswith("@s.whatsapp.net") or not item.get("message"):
            continue
        phone = normalize_phone(jid.split("@")[0])
        text = _text(item["message"])
        org_id = cfg["organization_id"]
        if key.get("fromMe"):
            contact = await db.crm_contacts.find_one({"organization_id": org_id, "phone_normalized": phone})
            if contact:
                await _store(org_id, contact["_id"], phone, "out", text, key.get("id"))
            continue
        lead, _ = await upsert_inbound_lead(org_id, "whatsapp", item.get("pushName"), phone, {}, message=text)
        await _store(org_id, lead["contact_id"], phone, "in", text, key.get("id"))
    return {"ok": True}
