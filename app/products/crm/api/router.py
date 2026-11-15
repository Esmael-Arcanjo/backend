from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.audit.service import audit
from app.core.authorization.deps import ProductContext, require_product
from app.products.crm.repositories import repos
from app.products.crm.schemas.inputs import (ActivityIn, ContactIn, LeadIn, OpportunityIn, PipelineIn, StageMoveIn)
from app.products.crm.services import crm_service as svc
from app.products.crm.services.segments import get_segment_config, validate_custom_fields

P = "crm"
router = APIRouter(prefix="/api/v1/crm", tags=["crm"])
read, write, delete, manage = (require_product(P, p) for p in ("read", "write", "delete", "manage"))


def _payload(body, exclude=("version",)) -> dict:
    return body.model_dump(exclude=set(exclude))


async def _log(ctx: ProductContext, action: str, target_type: str, target_id: str, request: Request):
    await audit(f"crm.{action}", user_id=ctx.user_id, organization_id=ctx.org_id, product_key=P,
                target_type=target_type, target_id=target_id, request=request)


def _search(q: Optional[str], fields) -> dict:
    if not q:
        return {}
    import re
    pattern = re.escape(q[:80])
    return {"$or": [{f: {"$regex": pattern, "$options": "i"}} for f in fields]}


@router.get("/overview")
async def overview(ctx: ProductContext = Depends(read)):
    return await svc.overview(ctx.org_id, ctx.subscription["segment"])


@router.get("/segment-config")
async def segment_config(ctx: ProductContext = Depends(read)):
    return {"segment": ctx.subscription["segment"], **get_segment_config(ctx.subscription["segment"])}


# Leads
@router.get("/leads")
async def list_leads(q: Optional[str] = Query(None, max_length=80),
                     status: Optional[str] = Query(None, pattern=r"^(new|contacted|qualified|lost|converted)$"),
                     ctx: ProductContext = Depends(read)):
    filters = _search(q, ["name", "email", "company"])
    if status:
        filters["status"] = status
    return {"items": [x.out() for x in await repos.leads.list(ctx.org_id, filters)]}


@router.post("/leads", status_code=201)
async def create_lead(body: LeadIn, request: Request, ctx: ProductContext = Depends(write)):
    data = _payload(body)
    try:
        data["custom_fields"] = validate_custom_fields(ctx.subscription["segment"], data["custom_fields"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    lead = await repos.leads.create(ctx.org_id, data, ctx.user_id)
    await _log(ctx, "lead_created", "lead", lead.id, request)
    return lead.out()


@router.put("/leads/{lead_id}")
async def update_lead(lead_id: str, body: LeadIn, request: Request, ctx: ProductContext = Depends(write)):
    current = await repos.leads.get(ctx.org_id, lead_id)
    if current.status == "converted":
        raise HTTPException(status_code=409, detail="Lead convertido não pode ser editado")
    data = _payload(body)
    try:
        data["custom_fields"] = validate_custom_fields(ctx.subscription["segment"], data["custom_fields"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    lead = await repos.leads.update(ctx.org_id, lead_id, data, body.version)
    await _log(ctx, "lead_updated", "lead", lead_id, request)
    return lead.out()


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(lead_id: str, request: Request, ctx: ProductContext = Depends(delete)):
    await repos.leads.delete(ctx.org_id, lead_id)
    await _log(ctx, "lead_deleted", "lead", lead_id, request)


@router.post("/leads/{lead_id}/convert")
async def convert_lead(lead_id: str, request: Request, ctx: ProductContext = Depends(write)):
    lead = await repos.leads.get(ctx.org_id, lead_id)
    if lead.status == "converted":
        raise HTTPException(status_code=409, detail="Lead já convertido")
    pipeline = await svc.get_pipeline(ctx.org_id, ctx.subscription["segment"])
    claimed = await repos.leads.update(ctx.org_id, lead_id, {"status": "converted"}, lead.version)
    contact = await repos.contacts.create(ctx.org_id, {"name": lead.name, "email": lead.email, "phone": lead.phone,
                                                       "company": lead.company, "position": None,
                                                       "notes": lead.notes, "tags": []}, ctx.user_id)
    opp = await repos.opportunities.create(ctx.org_id, {
        "title": f"{lead.company or lead.name}", "contact_id": ObjectId(contact.id), "value_cents": lead.value_cents,
        "stage_key": pipeline.stages[0].key, "status": "open", "expected_close_date": None,
        "notes": lead.notes}, ctx.user_id)
    await repos.leads.update(ctx.org_id, lead_id, {"converted_contact_id": ObjectId(contact.id),
                                                   "converted_opportunity_id": ObjectId(opp.id)}, claimed.version)
    await _log(ctx, "lead_converted", "lead", lead_id, request)
    return {"contact_id": contact.id, "opportunity_id": opp.id}


# Contacts
@router.get("/contacts")
async def list_contacts(q: Optional[str] = Query(None, max_length=80), ctx: ProductContext = Depends(read)):
    return {"items": [x.out() for x in await repos.contacts.list(ctx.org_id, _search(q, ["name", "email", "company"]))]}


@router.post("/contacts", status_code=201)
async def create_contact(body: ContactIn, request: Request, ctx: ProductContext = Depends(write)):
    contact = await repos.contacts.create(ctx.org_id, _payload(body), ctx.user_id)
    await _log(ctx, "contact_created", "contact", contact.id, request)
    return contact.out()


@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, body: ContactIn, request: Request, ctx: ProductContext = Depends(write)):
    contact = await repos.contacts.update(ctx.org_id, contact_id, _payload(body), body.version)
    await _log(ctx, "contact_updated", "contact", contact_id, request)
    return contact.out()


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: str, request: Request, ctx: ProductContext = Depends(delete)):
    if await repos.opportunities.count(ctx.org_id, {"contact_id": ObjectId(contact_id) if ObjectId.is_valid(contact_id) else None, "status": "open"}):
        raise HTTPException(status_code=409, detail="Contato possui oportunidades abertas")
    await repos.contacts.delete(ctx.org_id, contact_id)
    await _log(ctx, "contact_deleted", "contact", contact_id, request)


# Opportunities
async def _opp_data(body: OpportunityIn, ctx: ProductContext) -> dict:
    await svc.ensure_stage(ctx.org_id, ctx.subscription["segment"], body.stage_key)
    data = _payload(body)
    if body.contact_id:
        if not await repos.contacts.exists(ctx.org_id, body.contact_id):
            raise HTTPException(status_code=422, detail="Contato não encontrado")
        data["contact_id"] = ObjectId(body.contact_id)
    return data


@router.get("/opportunities")
async def list_opportunities(status: Optional[str] = Query(None, pattern=r"^(open|won|lost)$"),
                             ctx: ProductContext = Depends(read)):
    return {"items": [x.out() for x in await repos.opportunities.list(ctx.org_id, {"status": status} if status else {})]}


@router.post("/opportunities", status_code=201)
async def create_opportunity(body: OpportunityIn, request: Request, ctx: ProductContext = Depends(write)):
    opp = await repos.opportunities.create(ctx.org_id, await _opp_data(body, ctx), ctx.user_id)
    await _log(ctx, "opportunity_created", "opportunity", opp.id, request)
    return opp.out()


@router.put("/opportunities/{opp_id}")
async def update_opportunity(opp_id: str, body: OpportunityIn, request: Request, ctx: ProductContext = Depends(write)):
    opp = await repos.opportunities.update(ctx.org_id, opp_id, await _opp_data(body, ctx), body.version)
    await _log(ctx, "opportunity_updated", "opportunity", opp_id, request)
    return opp.out()


@router.patch("/opportunities/{opp_id}/stage")
async def move_stage(opp_id: str, body: StageMoveIn, request: Request, ctx: ProductContext = Depends(write)):
    await svc.ensure_stage(ctx.org_id, ctx.subscription["segment"], body.stage_key)
    opp = await repos.opportunities.update(ctx.org_id, opp_id, {"stage_key": body.stage_key}, body.version)
    await _log(ctx, "opportunity_stage_moved", "opportunity", opp_id, request)
    return opp.out()


@router.delete("/opportunities/{opp_id}", status_code=204)
async def delete_opportunity(opp_id: str, request: Request, ctx: ProductContext = Depends(delete)):
    await repos.opportunities.delete(ctx.org_id, opp_id)
    await _log(ctx, "opportunity_deleted", "opportunity", opp_id, request)


# Activities
@router.get("/activities")
async def list_activities(done: Optional[bool] = None, ctx: ProductContext = Depends(read)):
    filters = {} if done is None else {"done": done}
    return {"items": [x.out() for x in await repos.activities.list(ctx.org_id, filters, sort=("due_at", 1))]}


async def _act_data(body: ActivityIn, ctx: ProductContext) -> dict:
    await svc.ensure_related(ctx.org_id, body.related_type, body.related_id)
    data = _payload(body)
    if body.related_id:
        data["related_id"] = ObjectId(body.related_id)
    return data


@router.post("/activities", status_code=201)
async def create_activity(body: ActivityIn, request: Request, ctx: ProductContext = Depends(write)):
    act = await repos.activities.create(ctx.org_id, await _act_data(body, ctx), ctx.user_id)
    await _log(ctx, "activity_created", "activity", act.id, request)
    return act.out()


@router.put("/activities/{act_id}")
async def update_activity(act_id: str, body: ActivityIn, request: Request, ctx: ProductContext = Depends(write)):
    act = await repos.activities.update(ctx.org_id, act_id, await _act_data(body, ctx), body.version)
    await _log(ctx, "activity_updated", "activity", act_id, request)
    return act.out()


@router.delete("/activities/{act_id}", status_code=204)
async def delete_activity(act_id: str, request: Request, ctx: ProductContext = Depends(delete)):
    await repos.activities.delete(ctx.org_id, act_id)
    await _log(ctx, "activity_deleted", "activity", act_id, request)


# Pipeline
@router.get("/pipeline")
async def get_pipeline(ctx: ProductContext = Depends(read)):
    return (await svc.get_pipeline(ctx.org_id, ctx.subscription["segment"])).out()


@router.put("/pipeline")
async def update_pipeline(body: PipelineIn, request: Request, ctx: ProductContext = Depends(manage)):
    keys = [s.key for s in body.stages]
    if len(set(keys)) != len(keys):
        raise HTTPException(status_code=422, detail="Etapas duplicadas")
    pipeline = await svc.get_pipeline(ctx.org_id, ctx.subscription["segment"])
    in_use = await repos.opportunities.col.distinct("stage_key", {"organization_id": ctx.org_id, "status": "open"})
    missing = set(in_use) - set(keys)
    if missing:
        raise HTTPException(status_code=409, detail="Existem oportunidades abertas em etapas removidas")
    updated = await repos.pipelines.update(ctx.org_id, pipeline.id, {"name": body.name,
                                                                     "stages": [s.model_dump() for s in body.stages]})
    await _log(ctx, "pipeline_updated", "pipeline", pipeline.id, request)
    return updated.out()
