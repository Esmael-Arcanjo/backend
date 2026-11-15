from fastapi import APIRouter, Depends, Request

from app.core.authentication.deps import get_current_user
from app.core.authorization.deps import resolve_product_context
from app.database.mongo import db

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/{product_key}")
async def product_audit(product_key: str, request: Request, user: dict = Depends(get_current_user)):
    ctx = await resolve_product_context(request, user, product_key, "read")
    query = {"organization_id": ctx.org_id, "product_key": product_key}
    if ctx.role in {"member", "viewer"}:
        query["user_id"] = user["_id"]
    docs = await db.audit_logs.find(query).sort("created_at", -1).to_list(200)
    names = {u["_id"]: u["name"] for u in await db.users.find(
        {"_id": {"$in": list({d["user_id"] for d in docs if d.get("user_id")})}}).to_list(500)}
    return {"events": [{"id": str(d["_id"]), "action": d["action"], "user_name": names.get(d.get("user_id"), "Sistema"),
                        "target_type": d.get("target_type"), "target_id": d.get("target_id"),
                        "created_at": d["created_at"].isoformat()} for d in docs]}
