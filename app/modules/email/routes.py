from fastapi import APIRouter, Depends

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.email.schema import SendRequest, TemplateCreate, TemplateUpdate
from app.modules.email.service import EmailService

router = APIRouter(tags=["Email API"])
service = EmailService()

send_guard = scope_guard("email:send", "email")
tpl_guard = scope_guard("email:templates", "email")


@router.post("/v1/emails/send")
async def send_email(payload: SendRequest, ctx: ApiContext = Depends(send_guard)):
    return await service.send(ctx.project_id, payload.to, payload.template, payload.variables)


@router.get("/v1/emails/templates")
async def list_templates(ctx: ApiContext = Depends(tpl_guard)):
    return {"data": await service.list_templates(ctx.project_id)}


@router.post("/v1/emails/templates")
async def create_template(payload: TemplateCreate, ctx: ApiContext = Depends(tpl_guard)):
    return await service.create_template(ctx.project_id, payload)


@router.get("/v1/emails/logs")
async def list_logs(limit: int = 50, skip: int = 0, ctx: ApiContext = Depends(send_guard)):
    return {"data": await service.list_logs(ctx.project_id, limit, skip)}


# ---------- Dashboard ----------

@router.get("/dashboard/emails")
async def dashboard_emails(project_id: str, limit: int = 50, project: dict = Depends(project_scope)):
    return {
        "templates": await service.list_templates(project_id),
        "logs": await service.list_logs(project_id, limit),
        "stats": await service.stats(project_id),
    }


@router.post("/dashboard/emails/send")
async def dashboard_send(project_id: str, payload: SendRequest, project: dict = Depends(project_scope)):
    return await service.send(project_id, payload.to, payload.template, payload.variables)


@router.post("/dashboard/emails/templates")
async def dashboard_create_template(project_id: str, payload: TemplateCreate, project: dict = Depends(project_scope)):
    return await service.create_template(project_id, payload)


@router.patch("/dashboard/emails/templates/{template_id}")
async def dashboard_update_template(project_id: str, template_id: str, payload: TemplateUpdate,
                                    project: dict = Depends(project_scope)):
    return await service.update_template(project_id, template_id, payload.model_dump(exclude_none=True))


@router.delete("/dashboard/emails/templates/{template_id}")
async def dashboard_delete_template(project_id: str, template_id: str, project: dict = Depends(project_scope)):
    return await service.delete_template(project_id, template_id)


@router.post("/dashboard/emails/logs/{log_id}/resend")
async def dashboard_resend(project_id: str, log_id: str, project: dict = Depends(project_scope)):
    return await service.resend(project_id, log_id)
