from fastapi import APIRouter, Depends

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.wallet.schema import TransferRequest, WalletOperation
from app.modules.wallet.service import WalletService

router = APIRouter(tags=["Wallet"])
service = WalletService()


@router.get("/v1/balance")
async def get_balance(ctx: ApiContext = Depends(scope_guard("payments:read", "wallet"))):
    return {"data": await service.balances("organization", ctx.project["organization_id"])}


@router.get("/v1/wallet/statement")
async def statement(limit: int = 50, skip: int = 0,
                    ctx: ApiContext = Depends(scope_guard("payments:read", "wallet"))):
    return {"data": await service.statement("organization", ctx.project["organization_id"], limit, skip)}


@router.post("/v1/transfers")
async def create_transfer(payload: TransferRequest,
                          ctx: ApiContext = Depends(scope_guard("payments:write", "wallet"))):
    return await service.transfer(
        ctx.project_id, "organization", ctx.project["organization_id"], payload.destination_type,
        payload.destination_id, payload.amount, payload.currency, payload.description
    )


@router.get("/v1/transfers")
async def list_transfers(limit: int = 50, skip: int = 0,
                         ctx: ApiContext = Depends(scope_guard("payments:read", "wallet"))):
    return {"data": await service.list_transfers(ctx.project_id, limit, skip)}


@router.get("/dashboard/wallet")
async def dashboard_wallet(project_id: str, project: dict = Depends(project_scope)):
    return {
        "balances": await service.balances("organization", project["organization_id"]),
        "statement": await service.statement("organization", project["organization_id"], 50),
        "transfers": await service.list_transfers(project_id, 20),
    }


@router.post("/dashboard/wallet/topup")
async def topup(project_id: str, payload: WalletOperation, project: dict = Depends(project_scope)):
    """Sandbox top-up used to fund test wallets."""
    return await service.credit("organization", project["organization_id"], payload.currency, payload.amount,
                                project_id, "topup", project_id, payload.description or "Sandbox top-up")


@router.post("/dashboard/wallet/reserve")
async def reserve(project_id: str, payload: WalletOperation, project: dict = Depends(project_scope)):
    return await service.reserve("organization", project["organization_id"], payload.currency, payload.amount, project_id)


@router.post("/dashboard/wallet/release")
async def release(project_id: str, payload: WalletOperation, project: dict = Depends(project_scope)):
    return await service.release("organization", project["organization_id"], payload.currency, payload.amount, project_id)


@router.post("/dashboard/wallet/transfer")
async def dashboard_transfer(project_id: str, payload: TransferRequest, project: dict = Depends(project_scope)):
    return await service.transfer(project_id, "organization", project["organization_id"], payload.destination_type,
                                  payload.destination_id, payload.amount, payload.currency, payload.description)
