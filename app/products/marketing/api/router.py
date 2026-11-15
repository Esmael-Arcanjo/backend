from fastapi import APIRouter, Depends

from app.core.authorization.deps import ProductContext, require_product
from app.database.mongo import db

P = "marketing"
COLLECTIONS = ["marketing_campaigns", "marketing_contacts", "marketing_automations", "marketing_metrics"]
router = APIRouter(prefix="/api/v1/marketing", tags=["marketing"])


@router.get("/overview")
async def overview(ctx: ProductContext = Depends(require_product(P, "read"))):
    """Real counts of this product's collections. Business rules are pending (documented in PRD)."""
    counts = {c: await db[c].count_documents({"organization_id": ctx.org_id}) for c in COLLECTIONS}
    return {"product_key": P, "implementation_status": "in_development", "counts": counts}
