import logging
import os
import re
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.users.router import notify
from app.database.mongo import db
from app.integrations.email.sender import send_email
from app.products.crm.services import evolution
from app.products.crm.services.crm_service import get_pipeline
from app.shared.models import utcnow

logger = logging.getLogger("crm.inbound")
SOURCE_LABELS = {"site": "Site", "whatsapp": "WhatsApp", "instagram": "Instagram", "manual": "Manual"}
INTENT_LABELS = {"anunciar": "Quero Anunciar", "comprar": "Quero Comprar", "contato": "Contato"}
TRIAGEM = {"key": "triagem", "name": "Triagem", "probability": 5}
LEAD_FIELDS = ("email", "city", "intent", "wants", "price")


def normalize_phone(raw: Optional[str]) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits if 12 <= len(digits) <= 15 else ""


async def crm_segment(org_id: ObjectId) -> str:
    sub = await db.subscriptions.find_one({"organization_id": org_id, "product_key": "crm", "is_current": True})
    return sub["segment"] if sub else "servicos"


async def ensure_triagem(org_id: ObjectId) -> None:
    pipeline = await get_pipeline(org_id, await crm_segment(org_id))
    if "triagem" not in {s.key for s in pipeline.stages}:
        await db.crm_pipelines.update_one({"_id": ObjectId(pipeline.id), "stages.key": {"$ne": "triagem"}},
                                          {"$push": {"stages": {"$each": [TRIAGEM], "$position": 0}}})


async def site_org_id() -> ObjectId:
    """The organization that receives leads from the leamse.com forms (owner set via SITE_OWNER_EMAIL)."""
    user = await db.users.find_one({"email": os.environ.get("SITE_OWNER_EMAIL", "").lower()})
    if user:
        orgs = [o["_id"] async for o in db.organizations.find({"owner_id": user["_id"], "status": "active"})]
        sub = await db.subscriptions.find_one({"organization_id": {"$in": orgs}, "product_key": "crm",
                                               "is_current": True, "status": {"$in": ["active", "past_due"]}})
        if sub:
            return sub["organization_id"]
    raise HTTPException(status_code=503, detail="Recebimento de leads do site ainda não configurado")


async def _upsert_contact(org_id: ObjectId, name: str, phone: str, phone_n: str, email: Optional[str]) -> ObjectId:
    now = utcnow()
    doc = await db.crm_contacts.find_one_and_update(
        {"organization_id": org_id, "phone_normalized": phone_n},
        {"$setOnInsert": {"organization_id": org_id, "name": name, "email": email, "phone": phone,
                          "phone_normalized": phone_n, "company": None, "position": None, "notes": None, "tags": [],
                          "created_by": None, "created_at": now, "updated_at": now, "version": 1}},
        upsert=True, return_document=ReturnDocument.AFTER)
    return doc["_id"]


async def notify_new_lead(org_id: ObjectId, lead: dict) -> None:
    source = SOURCE_LABELS.get(lead.get("source"), "Manual")
    details = " · ".join(str(x) for x in (lead.get("wants"), lead.get("city"), lead.get("price")) if x)
    title, body = "Novo lead no CRM", f"{lead['name']} ({lead.get('phone') or '-'}) via {source}. {details}".strip()
    grants = await db.product_permissions.find({"organization_id": org_id, "product_key": "crm"}).to_list(50)
    for g in grants:
        await notify(g["user_id"], title, body, "crm", org_id)
        user = await db.users.find_one({"_id": g["user_id"]})
        if user and user.get("notification_prefs", {}).get("email_product", True):
            await send_email(user["email"], f"Novo lead: {lead['name']}", f"Olá, {user['name']}!\n\n{body}", "crm_new_lead")
    cfg = await db.crm_whatsapp.find_one({"organization_id": org_id, "status": "open"})
    if cfg and cfg.get("notify_number"):
        try:
            await evolution.send_text(cfg, cfg["notify_number"], f"LEAMSE CRM — {title}\n{body}")
        except HTTPException:
            logger.warning("WhatsApp notification failed for org %s", org_id)


async def upsert_inbound_lead(org_id: ObjectId, source: str, name: Optional[str], phone: str, fields: dict,
                              message: Optional[str] = None) -> tuple[dict, bool]:
    """Same WhatsApp never duplicates: the existing lead is updated instead."""
    phone_n = normalize_phone(phone)
    if not phone_n:
        raise HTTPException(status_code=422, detail="Informe um WhatsApp válido com DDD")
    now = utcnow()
    clean = {k: v for k, v in fields.items() if k in LEAD_FIELDS and v not in (None, "")}
    existing = await db.crm_leads.find_one({"organization_id": org_id, "phone_normalized": phone_n})
    if existing:
        update = {**clean, "updated_at": now}
        if name and source == "site":
            update["name"] = name
        await db.crm_leads.update_one({"_id": existing["_id"]}, {"$set": update, "$inc": {"version": 1}})
        return await db.crm_leads.find_one({"_id": existing["_id"]}), False
    display = name or f"+{phone_n}"
    contact_id = await _upsert_contact(org_id, display, phone, phone_n, clean.get("email"))
    lead = {"organization_id": org_id, "created_by": None, "created_at": now, "updated_at": now, "version": 1,
            "name": display, "email": None, "phone": phone, "phone_normalized": phone_n, "company": None,
            "source": source, "status": "new", "value_cents": 0, "notes": message, "custom_fields": {},
            "city": None, "intent": None, "wants": None, "price": None, "published": False,
            "contact_id": contact_id, **clean}
    try:
        lead["_id"] = (await db.crm_leads.insert_one(lead)).inserted_id
    except DuplicateKeyError:
        return await upsert_inbound_lead(org_id, source, name, phone, fields, message)
    await ensure_triagem(org_id)
    intent = INTENT_LABELS.get(lead.get("intent") or "", "")
    opp = await db.crm_opportunities.insert_one({
        "organization_id": org_id, "title": f"{display} — {lead.get('wants') or intent or 'Novo lead'}",
        "contact_id": contact_id, "value_cents": 0, "stage_key": "triagem", "status": "open",
        "expected_close_date": None, "notes": f"Origem: {SOURCE_LABELS.get(source, source)}",
        "created_by": None, "created_at": now, "updated_at": now, "version": 1})
    await db.crm_leads.update_one({"_id": lead["_id"]}, {"$set": {"opportunity_id": opp.inserted_id}})
    await notify_new_lead(org_id, lead)
    return lead, True
