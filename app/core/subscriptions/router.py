from fastapi import APIRouter, Depends, HTTPException

from app.core.authentication.deps import get_current_user
from app.core.products_catalog.catalog_data import PRODUCT_KEYS, SEGMENTS
from app.database.mongo import db

router = APIRouter(prefix="/api/v1", tags=["subscriptions"])


@router.get("/access/{product_key}")
async def product_access(product_key: str, user: dict = Depends(get_current_user)):
    """Organizations where the caller can open this product (membership + grant + valid subscription)."""
    if product_key not in PRODUCT_KEYS:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    grants = await db.product_permissions.find({"user_id": user["_id"], "product_key": product_key}).to_list(50)
    contexts = []
    for g in grants:
        member = await db.organization_members.find_one({"organization_id": g["organization_id"],
                                                         "user_id": user["_id"], "status": "active"})
        org = await db.organizations.find_one({"_id": g["organization_id"], "status": "active"})
        sub = await db.subscriptions.find_one({"organization_id": g["organization_id"], "product_key": product_key,
                                               "is_current": True})
        if member and org and sub and sub["status"] in {"active", "past_due"}:
            contexts.append({"organization_id": str(org["_id"]), "organization_name": org["name"],
                             "segment": sub["segment"], "segment_name": SEGMENTS.get(sub["segment"], sub["segment"]),
                             "plan_key": sub["plan_key"], "subscription_status": sub["status"], "role": g["role"]})
    return {"product_key": product_key, "contexts": contexts}


@router.get("/subscriptions/mine")
async def my_subscriptions(user: dict = Depends(get_current_user)):
    """Contracted products of the caller, used by the website account area to show each dashboard address."""
    grants = await db.product_permissions.find({"user_id": user["_id"]}).to_list(200)
    items = []
    for g in grants:
        sub = await db.subscriptions.find_one({"organization_id": g["organization_id"],
                                               "product_key": g["product_key"], "is_current": True})
        org = await db.organizations.find_one({"_id": g["organization_id"]})
        product = await db.products.find_one({"key": g["product_key"]})
        if sub and org and product:
            items.append({"product_key": g["product_key"], "product_name": product["name"], "slug": product["slug"],
                          "organization_name": org["name"], "organization_id": str(org["_id"]),
                          "status": sub["status"], "plan_key": sub["plan_key"], "role": g["role"]})
    pending = await db.subscriptions.find({"created_by": user["_id"], "status": "pending"}).to_list(20)
    return {"subscriptions": items, "pending_count": len(pending)}
