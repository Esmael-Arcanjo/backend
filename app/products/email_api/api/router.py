from fastapi import APIRouter, Depends

from app.core.authorization.deps import ProductContext, require_product
from app.database.mongo import db

P = "email_api"
COLLECTIONS = ["email_domains", "email_messages", "email_templates", "email_api_keys", "email_events"]
router = APIRouter(prefix="/api/v1/email_api", tags=["email_api"])


@router.get("/overview")
async def overview(ctx: ProductContext = Depends(require_product(P, "read"))):
    """Real counts of this product's collections. Business rules are pending (documented in PRD)."""
    counts = {c: await db[c].count_documents({"organization_id": ctx.org_id}) for c in COLLECTIONS}
    return {"product_key": P, "implementation_status": "in_development", "counts": counts}
