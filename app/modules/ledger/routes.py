from fastapi import APIRouter, Depends

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.ledger.service import LedgerService

router = APIRouter(tags=["Ledger"])
service = LedgerService()


@router.get("/v1/ledger")
async def list_ledger(limit: int = 50, skip: int = 0,
                      ctx: ApiContext = Depends(scope_guard("payments:read", "payments"))):
    return {"data": await service.list_entries(ctx.project_id, limit, skip)}


@router.get("/dashboard/ledger")
async def dashboard_ledger(project_id: str, limit: int = 50, skip: int = 0, project: dict = Depends(project_scope)):
    return {
        "data": await service.list_entries(project_id, limit, skip),
        "trial_balance": await service.trial_balance(project_id),
    }
