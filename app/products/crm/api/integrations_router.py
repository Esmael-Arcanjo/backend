import os
import secrets
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, field_validator

from app.core.audit.service import audit
from app.core.authorization.deps import ProductContext, require_product
from app.core.security.crypto import encrypt
from app.core.security.tokens import hash_token
from app.database.mongo import db
from app.products.crm.services import evolution
from app.products.crm.services.inbound import normalize_phone
from app.shared.models import StrictInput, to_oid, utcnow

P = "crm"
router = APIRouter(prefix="/api/v1/crm", tags=["crm-integrations"])
read, write, manage = (require_product(P, p) for p in ("read", "write", "manage"))


def api_public_url(request: Request) -> str:
    return (os.environ.get("PUBLIC_API_URL") or str(request.base_url)).rstrip("/")


class WhatsAppConfigIn(StrictInput):
    base_url: str = Field(max_length=200)
    api_key: Optional[str] = Field(default=None, max_length=200)
    notify_number: Optional[str] = Field(default=None, max_length=30)

    @field_validator("base_url")
    @classmethod
    def https_only(cls, v: str) -> str:
        p = urlparse(v.strip())
        if p.scheme != "https" or not p.netloc:
            raise ValueError("Informe a URL https do servidor Evolution API")
        return f"https://{p.netloc}{p.path.rstrip('/')}"


class SendIn(StrictInput):
    text: str = Field(min_length=1, max_length=4000)


class PublishIn(StrictInput):
    published: bool


def _wa_out(cfg: Optional[dict]) -> dict:
    if not cfg:
        return {"configured": False, "status": "not_configured"}
    return {"configured": True, "base_url": cfg["base_url"], "instance": cfg["instance"],
            "status": cfg.get("status", "close"), "notify_number": cfg.get("notify_number"),
            "has_api_key": bool(cfg.get("api_key_enc"))}


async def _wa(ctx: ProductContext) -> dict:
    cfg = await db.crm_whatsapp.find_one({"organization_id": ctx.org_id})
    if not cfg or not cfg.get("api_key_enc"):
        raise HTTPException(status_code=400, detail="Configure o servidor Evolution API primeiro")
    return cfg


@router.get("/integrations/whatsapp")
async def whatsapp_get(ctx: ProductContext = Depends(read)):
    return _wa_out(await db.crm_whatsapp.find_one({"organization_id": ctx.org_id}))


@router.put("/integrations/whatsapp")
async def whatsapp_config(body: WhatsAppConfigIn, request: Request, ctx: ProductContext = Depends(manage)):
    current = await db.crm_whatsapp.find_one({"organization_id": ctx.org_id})
    if not body.api_key and not (current and current.get("api_key_enc")):
        raise HTTPException(status_code=422, detail="Informe a chave (API key) do servidor Evolution")
    notify_n = normalize_phone(body.notify_number) if body.notify_number else None
    if body.notify_number and not notify_n:
        raise HTTPException(status_code=422, detail="WhatsApp para avisos inválido")
    update = {"base_url": body.base_url, "notify_number": notify_n, "updated_at": utcnow()}
    if body.api_key:
        update["api_key_enc"] = encrypt(body.api_key)
    await db.crm_whatsapp.update_one({"organization_id": ctx.org_id}, {"$set": update, "$setOnInsert": {
        "organization_id": ctx.org_id, "instance": f"leamse-{ctx.org_id}", "webhook_secret": secrets.token_urlsafe(24),
        "status": "close", "created_at": utcnow()}}, upsert=True)
    await audit("crm.whatsapp_configured", user_id=ctx.user_id, organization_id=ctx.org_id, product_key=P, request=request)
    return _wa_out(await db.crm_whatsapp.find_one({"organization_id": ctx.org_id}))


@router.post("/integrations/whatsapp/connect")
async def whatsapp_connect(request: Request, ctx: ProductContext = Depends(write)):
    cfg = await _wa(ctx)
    try:
        await evolution.create_instance(cfg, f"{api_public_url(request)}/api/webhooks/evolution/{cfg['webhook_secret']}")
    except HTTPException:
        pass  # instance already exists on the server
    data = await evolution.connect(cfg)
    await db.crm_whatsapp.update_one({"_id": cfg["_id"]}, {"$set": {"status": "connecting"}})
    return {"status": "connecting", "qr": data.get("base64"), "pairing_code": data.get("pairingCode")}


@router.get("/integrations/whatsapp/status")
async def whatsapp_status(ctx: ProductContext = Depends(read)):
    cfg = await _wa(ctx)
    current = await evolution.state(cfg)
    await db.crm_whatsapp.update_one({"_id": cfg["_id"]}, {"$set": {"status": current}})
    return {"status": current}


@router.post("/integrations/whatsapp/disconnect")
async def whatsapp_disconnect(request: Request, ctx: ProductContext = Depends(write)):
    cfg = await _wa(ctx)
    try:
        await evolution.logout(cfg)
    finally:
        await db.crm_whatsapp.update_one({"_id": cfg["_id"]}, {"$set": {"status": "close"}})
    await audit("crm.whatsapp_disconnected", user_id=ctx.user_id, organization_id=ctx.org_id, product_key=P,
                request=request)
    return {"status": "close"}


@router.get("/integrations/site")
async def site_get(request: Request, ctx: ProductContext = Depends(read)):
    cfg = await db.crm_settings.find_one({"organization_id": ctx.org_id}) or {}
    return {"webhook_url": f"{api_public_url(request)}/api/leads", "has_token": bool(cfg.get("webhook_token_hash")),
            "token_hint": cfg.get("token_hint")}


@router.post("/integrations/site/token")
async def site_token(request: Request, ctx: ProductContext = Depends(manage)):
    token = f"lk_{secrets.token_urlsafe(24)}"
    await db.crm_settings.update_one({"organization_id": ctx.org_id}, {"$set": {
        "webhook_token_hash": hash_token(token), "token_hint": token[-4:], "updated_at": utcnow()}}, upsert=True)
    await audit("crm.webhook_token_rotated", user_id=ctx.user_id, organization_id=ctx.org_id, product_key=P,
                request=request)
    return {"token": token}


@router.get("/conversations")
async def conversations(ctx: ProductContext = Depends(read)):
    rows = await (await db.crm_messages.aggregate([
        {"$match": {"organization_id": ctx.org_id}}, {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$contact_id", "last": {"$first": "$text"}, "at": {"$first": "$created_at"},
                    "direction": {"$first": "$direction"}, "count": {"$sum": 1}}},
        {"$sort": {"at": -1}}, {"$limit": 100}])).to_list(100)
    contacts = {c["_id"]: c async for c in db.crm_contacts.find({"_id": {"$in": [r["_id"] for r in rows]},
                                                                  "organization_id": ctx.org_id})}
    return {"items": [{"contact_id": str(r["_id"]), "name": contacts.get(r["_id"], {}).get("name", "Contato"),
                       "phone": contacts.get(r["_id"], {}).get("phone"), "last": r["last"], "direction": r["direction"],
                       "at": r["at"].isoformat(), "count": r["count"]} for r in rows if r["_id"] in contacts]}


async def _contact(ctx: ProductContext, contact_id: str) -> dict:
    contact = await db.crm_contacts.find_one({"_id": to_oid(contact_id), "organization_id": ctx.org_id})
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    return contact


@router.get("/conversations/{contact_id}")
async def conversation_messages(contact_id: str, ctx: ProductContext = Depends(read)):
    contact = await _contact(ctx, contact_id)
    msgs = await db.crm_messages.find({"organization_id": ctx.org_id, "contact_id": contact["_id"]}) \
        .sort("created_at", 1).to_list(500)
    return {"contact": {"id": str(contact["_id"]), "name": contact["name"], "phone": contact.get("phone")},
            "items": [{"id": str(m["_id"]), "direction": m["direction"], "text": m["text"],
                       "at": m["created_at"].isoformat()} for m in msgs]}


@router.post("/conversations/{contact_id}/send", status_code=201)
async def conversation_send(contact_id: str, body: SendIn, ctx: ProductContext = Depends(write)):
    contact = await _contact(ctx, contact_id)
    cfg = await _wa(ctx)
    if cfg.get("status") != "open":
        raise HTTPException(status_code=409, detail="WhatsApp desconectado. Conecte em Integrações > WhatsApp")
    number = contact.get("phone_normalized") or normalize_phone(contact.get("phone"))
    if not number:
        raise HTTPException(status_code=422, detail="Contato sem WhatsApp válido")
    res = await evolution.send_text(cfg, number, body.text)
    doc = {"organization_id": ctx.org_id, "contact_id": contact["_id"], "phone": number, "direction": "out",
           "text": body.text, "wa_id": (res.get("key") or {}).get("id"), "sent_by": ctx.user_id, "created_at": utcnow()}
    doc["_id"] = (await db.crm_messages.insert_one(doc)).inserted_id
    return {"id": str(doc["_id"]), "direction": "out", "text": body.text, "at": doc["created_at"].isoformat()}


@router.patch("/leads/{lead_id}/publish")
async def publish_listing(lead_id: str, body: PublishIn, request: Request, ctx: ProductContext = Depends(write)):
    res = await db.crm_leads.update_one({"_id": to_oid(lead_id), "organization_id": ctx.org_id, "intent": "anunciar"},
                                        {"$set": {"published": body.published, "updated_at": utcnow()},
                                         "$inc": {"version": 1}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Anúncio não encontrado")
    await audit("crm.listing_published" if body.published else "crm.listing_unpublished", user_id=ctx.user_id,
                organization_id=ctx.org_id, product_key=P, target_type="lead", target_id=lead_id, request=request)
    return {"published": body.published}
