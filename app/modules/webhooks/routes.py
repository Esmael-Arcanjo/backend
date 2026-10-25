from fastapi import APIRouter, Depends

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.webhooks.schema import EVENTS, WebhookCreate, WebhookUpdate
from app.modules.webhooks.service import WebhookService

router = APIRouter(tags=["Webhooks"])
service = WebhookService()


@router.get("/v1/webhooks")
async def list_webhooks(ctx: ApiContext = Depends(scope_guard("webhooks:read", "payments"))):
    return {"data": await service.list_all(ctx.project_id)}


@router.get("/dashboard/webhooks")
async def dashboard_webhooks(project_id: str, project: dict = Depends(project_scope)):
    return {
        "data": await service.list_all(project_id),
        "deliveries": await service.deliveries_for(project_id),
        "events": EVENTS,
    }


@router.post("/dashboard/webhooks")
async def create_webhook(project_id: str, payload: WebhookCreate, project: dict = Depends(project_scope)):
    return await service.create(project_id, payload.url, payload.events, payload.description)


@router.patch("/dashboard/webhooks/{webhook_id}")
async def update_webhook(project_id: str, webhook_id: str, payload: WebhookUpdate,
                         project: dict = Depends(project_scope)):
    return await service.update(webhook_id, project_id, payload.model_dump(exclude_none=True))


@router.delete("/dashboard/webhooks/{webhook_id}")
async def delete_webhook(project_id: str, webhook_id: str, project: dict = Depends(project_scope)):
    return await service.delete(webhook_id, project_id)
