from fastapi import APIRouter, Depends

from app.core.authorization.deps import ProductContext, require_product
from app.database.mongo import db

P = "erp"
COLLECTIONS = ["erp_products", "erp_inventory", "erp_purchases", "erp_sales", "erp_invoices"]
router = APIRouter(prefix="/api/v1/erp", tags=["erp"])


@router.get("/overview")
async def overview(ctx: ProductContext = Depends(require_product(P, "read"))):
    """Real counts of this product's collections. Business rules are pending (documented in PRD)."""
    counts = {c: await db[c].count_documents({"organization_id": ctx.org_id}) for c in COLLECTIONS}
    return {"product_key": P, "implementation_status": "in_development", "counts": counts}
