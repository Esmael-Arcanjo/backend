from fastapi import APIRouter, Depends

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.payments.schema import (
    CaptureRequest,
    ChargeCreate,
    PaymentIntentCreate,
    PaymentLinkCreate,
    RefundCreate,
)
from app.modules.payments.service import PaymentService

router = APIRouter(tags=["Payments"])
service = PaymentService()

read_guard = scope_guard("payments:read", "payments")
write_guard = scope_guard("payments:write", "payments")


@router.post("/v1/payment_intents")
async def create_payment_intent(payload: PaymentIntentCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_intent(ctx.project_id, payload)


@router.get("/v1/payment_intents")
async def list_payment_intents(limit: int = 50, skip: int = 0, status: str | None = None,
                               ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_intents(ctx.project_id, limit, skip, status)}


@router.get("/v1/payment_intents/{intent_id}")
async def get_payment_intent(intent_id: str, ctx: ApiContext = Depends(read_guard)):
    return await service.get_intent(ctx.project_id, intent_id)


@router.post("/v1/payment_intents/{intent_id}/cancel")
async def cancel_payment_intent(intent_id: str, ctx: ApiContext = Depends(write_guard)):
    return await service.cancel_intent(ctx.project_id, intent_id)


@router.post("/v1/charges")
async def create_charge(payload: ChargeCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_charge(ctx.project_id, ctx.project["organization_id"],
                                       payload.payment_intent_id, payload.payment_method)


@router.get("/v1/charges")
async def list_charges(limit: int = 50, skip: int = 0, status: str | None = None,
                       ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_charges(ctx.project_id, limit, skip, status)}


@router.post("/v1/charges/{charge_id}/capture")
async def capture_charge(charge_id: str, payload: CaptureRequest, ctx: ApiContext = Depends(write_guard)):
    return await service.capture(ctx.project_id, ctx.project["organization_id"], charge_id, payload.amount)


@router.post("/v1/refunds")
async def create_refund(payload: RefundCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.refund(ctx.project_id, ctx.project["organization_id"], payload.charge_id,
                                payload.amount, payload.reason)


@router.get("/v1/refunds")
async def list_refunds(limit: int = 50, skip: int = 0, ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_refunds(ctx.project_id, limit, skip)}


@router.get("/v1/transactions")
async def list_transactions(limit: int = 50, skip: int = 0, ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_transactions(ctx.project_id, limit, skip)}


@router.post("/v1/payment_links")
async def create_payment_link(payload: PaymentLinkCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_payment_link(ctx.project_id, payload.model_dump())


@router.get("/v1/payment_links")
async def list_payment_links(ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_payment_links(ctx.project_id)}


# ---------- Dashboard (JWT) ----------

@router.get("/dashboard/payments")
async def dashboard_payments(project_id: str, limit: int = 50, skip: int = 0, project: dict = Depends(project_scope)):
    return {
        "intents": await service.list_intents(project_id, limit, skip),
        "charges": await service.list_charges(project_id, limit, skip),
        "refunds": await service.list_refunds(project_id, 20),
    }


@router.post("/dashboard/payments/intents")
async def dashboard_create_intent(project_id: str, payload: PaymentIntentCreate,
                                  project: dict = Depends(project_scope)):
    return await service.create_intent(project_id, payload)


@router.post("/dashboard/payments/charges")
async def dashboard_create_charge(project_id: str, payload: ChargeCreate, project: dict = Depends(project_scope)):
    return await service.create_charge(project_id, project["organization_id"], payload.payment_intent_id, payload.payment_method)


@router.post("/dashboard/payments/refunds")
async def dashboard_refund(project_id: str, payload: RefundCreate, project: dict = Depends(project_scope)):
    return await service.refund(project_id, project["organization_id"], payload.charge_id, payload.amount, payload.reason)


@router.post("/dashboard/payments/settle")
async def dashboard_settle(project_id: str, currency: str = "BRL", project: dict = Depends(project_scope)):
    return await service.settle(project_id, currency)


@router.get("/dashboard/payment_links")
async def dashboard_links(project_id: str, project: dict = Depends(project_scope)):
    return {"data": await service.list_payment_links(project_id)}


@router.post("/dashboard/payment_links")
async def dashboard_create_link(project_id: str, payload: PaymentLinkCreate, project: dict = Depends(project_scope)):
    return await service.create_payment_link(project_id, payload.model_dump())


@router.get("/checkout/{token}")
async def public_checkout(token: str):
    return await service.get_payment_link(token)
