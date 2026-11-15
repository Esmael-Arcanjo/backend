from fastapi import APIRouter, HTTPException

from app.core.products_catalog.catalog_data import PLANS, PRODUCTS, SEGMENTS
from app.database.mongo import db
from app.shared.models import utcnow

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


async def seed_catalog() -> None:
    for p in PRODUCTS:
        await db.products.update_one({"key": p["key"]}, {"$set": {**p, "updated_at": utcnow()}}, upsert=True)
    for plan in PLANS:
        await db.plans.update_one({"product_key": plan["product_key"], "plan_key": plan["plan_key"]},
                                  {"$set": {**plan, "active": True, "updated_at": utcnow()}}, upsert=True)


def _product_out(p: dict) -> dict:
    return {k: p[k] for k in ("key", "slug", "name", "status", "tagline", "features", "supported_segments")}


@router.get("/segments")
async def segments():
    return {"segments": [{"key": k, "name": v} for k, v in SEGMENTS.items()]}


@router.get("/products")
async def products():
    docs = await db.products.find({}).to_list(20)
    order = [p["key"] for p in PRODUCTS]
    docs.sort(key=lambda d: order.index(d["key"]) if d["key"] in order else 99)
    return {"products": [_product_out(d) for d in docs]}


@router.get("/pricing")
async def pricing():
    docs = await db.products.find({}).to_list(20)
    order = [p["key"] for p in PRODUCTS]
    docs.sort(key=lambda d: order.index(d["key"]) if d["key"] in order else 99)
    plans = await db.plans.find({"active": True}).sort("price_cents", 1).to_list(200)
    out = []
    for d in docs:
        own = [{k: pl[k] for k in ("plan_key", "name", "price_cents", "currency", "interval", "seats", "highlights")}
               for pl in plans if pl["product_key"] == d["key"]] if d["status"] == "available" else []
        out.append({**_product_out(d), "plans": own})
    return {"products": out}


@router.get("/products/{slug}")
async def product_detail(slug: str):
    doc = await db.products.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    plans = await db.plans.find({"product_key": doc["key"], "active": True}).sort("price_cents", 1).to_list(10)
    return {"product": _product_out(doc),
            "plans": [{k: pl[k] for k in ("plan_key", "name", "price_cents", "currency", "interval", "seats",
                                          "highlights")} for pl in plans],
            "segments": [{"key": s, "name": SEGMENTS[s]} for s in doc["supported_segments"]]}
