from bson import ObjectId
from fastapi import HTTPException

from app.products.crm.repositories import repos
from app.products.crm.services.segments import get_segment_config
from app.database.mongo import db
from app.shared.models import utcnow


async def provision_crm(subscription: dict) -> None:
    """Creates the segment's default pipeline once per organization."""
    org_id = subscription["organization_id"]
    now = utcnow()
    await db.crm_pipelines.update_one(
        {"organization_id": org_id},
        {"$setOnInsert": {"organization_id": org_id, "name": "Funil de vendas", "segment": subscription["segment"],
                          "stages": get_segment_config(subscription["segment"])["stages"],
                          "created_by": subscription["created_by"], "created_at": now, "updated_at": now,
                          "version": 1}},
        upsert=True)


async def get_pipeline(org_id: ObjectId, segment: str):
    found = await repos.pipelines.list(org_id, limit=1)
    if found:
        return found[0]
    await provision_crm({"organization_id": org_id, "segment": segment, "created_by": None})
    return (await repos.pipelines.list(org_id, limit=1))[0]


async def ensure_stage(org_id: ObjectId, segment: str, stage_key: str) -> None:
    pipeline = await get_pipeline(org_id, segment)
    if stage_key not in {s.key for s in pipeline.stages}:
        raise HTTPException(status_code=422, detail="Etapa inexistente no funil")


async def ensure_related(org_id: ObjectId, related_type, related_id) -> None:
    if bool(related_type) != bool(related_id):
        raise HTTPException(status_code=422, detail="Vínculo incompleto")
    if not related_type:
        return
    repo = {"lead": repos.leads, "contact": repos.contacts, "opportunity": repos.opportunities}[related_type]
    if not await repo.exists(org_id, related_id):
        raise HTTPException(status_code=422, detail="Registro vinculado não encontrado")


async def _agg(collection: str, pipeline: list) -> list:
    cursor = await db[collection].aggregate(pipeline)
    return await cursor.to_list(100)


async def overview(org_id: ObjectId, segment: str) -> dict:
    pipeline = await get_pipeline(org_id, segment)
    by_stage = {d["_id"]: d for d in await _agg("crm_opportunities", [
        {"$match": {"organization_id": org_id, "status": "open"}},
        {"$group": {"_id": "$stage_key", "count": {"$sum": 1}, "value": {"$sum": "$value_cents"}}}])}
    lead_status = {d["_id"]: d["count"] for d in await _agg("crm_leads", [
        {"$match": {"organization_id": org_id}}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}])}
    won = await _agg("crm_opportunities", [
        {"$match": {"organization_id": org_id, "status": "won"}},
        {"$group": {"_id": None, "count": {"$sum": 1}, "value": {"$sum": "$value_cents"}}}])
    upcoming = await db.crm_activities.find({"organization_id": org_id, "done": False}) \
        .sort("due_at", 1).limit(5).to_list(5)
    open_value = sum(d["value"] for d in by_stage.values())
    weighted = sum(by_stage.get(s.key, {}).get("value", 0) * s.probability / 100 for s in pipeline.stages)
    return {
        "leads_total": sum(lead_status.values()), "leads_by_status": lead_status,
        "contacts_total": await repos.contacts.count(org_id),
        "open_opportunities": sum(d["count"] for d in by_stage.values()),
        "open_value_cents": open_value, "weighted_value_cents": int(weighted),
        "won_count": won[0]["count"] if won else 0, "won_value_cents": won[0]["value"] if won else 0,
        "pending_activities": await repos.activities.count(org_id, {"done": False}),
        "stages": [{"key": s.key, "name": s.name, "count": by_stage.get(s.key, {}).get("count", 0),
                    "value_cents": by_stage.get(s.key, {}).get("value", 0)} for s in pipeline.stages],
        "upcoming_activities": [{"id": str(a["_id"]), "subject": a["subject"], "type": a["type"],
                                 "due_at": a["due_at"].isoformat() if a.get("due_at") else None} for a in upcoming],
    }
