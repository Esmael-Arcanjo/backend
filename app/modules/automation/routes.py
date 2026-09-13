from fastapi import APIRouter, Depends

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.automation.schema import (
    AppointmentCreate,
    AppointmentUpdate,
    ChatRequest,
    ContactCreate,
    ContactUpdate,
    FlowCreate,
    FlowUpdate,
)
from app.modules.automation.service import AutomationService

router = APIRouter(tags=["Automation"])
service = AutomationService()

read_guard = scope_guard("automation:read", "automation")
write_guard = scope_guard("automation:write", "automation")


# ---------- Public API (API key) ----------

@router.get("/v1/automation/appointments")
async def api_list_appointments(limit: int = 100, skip: int = 0, ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_appointments(ctx.project_id, limit, skip)}


@router.post("/v1/automation/appointments")
async def api_create_appointment(payload: AppointmentCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_appointment(ctx.project_id, payload)


@router.get("/v1/automation/contacts")
async def api_list_contacts(limit: int = 100, skip: int = 0, ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_contacts(ctx.project_id, limit, skip)}


@router.post("/v1/automation/contacts")
async def api_create_contact(payload: ContactCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_contact(ctx.project_id, payload)


# ---------- Dashboard (JWT) ----------

@router.get("/dashboard/automation/overview")
async def overview(project_id: str, project: dict = Depends(project_scope)):
    return await service.overview(project_id)


@router.get("/dashboard/automation/appointments")
async def list_appointments(project_id: str, project: dict = Depends(project_scope)):
    return {"data": await service.list_appointments(project_id)}


@router.post("/dashboard/automation/appointments")
async def create_appointment(project_id: str, payload: AppointmentCreate, project: dict = Depends(project_scope)):
    return await service.create_appointment(project_id, payload)


@router.patch("/dashboard/automation/appointments/{appointment_id}")
async def update_appointment(project_id: str, appointment_id: str, payload: AppointmentUpdate,
                             project: dict = Depends(project_scope)):
    return await service.update_appointment(project_id, appointment_id, payload.model_dump(exclude_none=True))


@router.delete("/dashboard/automation/appointments/{appointment_id}")
async def delete_appointment(project_id: str, appointment_id: str, project: dict = Depends(project_scope)):
    return await service.delete_appointment(project_id, appointment_id)


@router.get("/dashboard/automation/contacts")
async def list_contacts(project_id: str, project: dict = Depends(project_scope)):
    return {"data": await service.list_contacts(project_id)}


@router.post("/dashboard/automation/contacts")
async def create_contact(project_id: str, payload: ContactCreate, project: dict = Depends(project_scope)):
    return await service.create_contact(project_id, payload)


@router.patch("/dashboard/automation/contacts/{contact_id}")
async def update_contact(project_id: str, contact_id: str, payload: ContactUpdate,
                         project: dict = Depends(project_scope)):
    return await service.update_contact(project_id, contact_id, payload.model_dump(exclude_none=True))


@router.delete("/dashboard/automation/contacts/{contact_id}")
async def delete_contact(project_id: str, contact_id: str, project: dict = Depends(project_scope)):
    return await service.delete_contact(project_id, contact_id)


@router.get("/dashboard/automation/flows")
async def list_flows(project_id: str, project: dict = Depends(project_scope)):
    return {"data": await service.list_flows(project_id)}


@router.post("/dashboard/automation/flows")
async def create_flow(project_id: str, payload: FlowCreate, project: dict = Depends(project_scope)):
    return await service.create_flow(project_id, payload)


@router.patch("/dashboard/automation/flows/{flow_id}")
async def update_flow(project_id: str, flow_id: str, payload: FlowUpdate, project: dict = Depends(project_scope)):
    return await service.update_flow(project_id, flow_id, payload.model_dump(exclude_none=True))


@router.delete("/dashboard/automation/flows/{flow_id}")
async def delete_flow(project_id: str, flow_id: str, project: dict = Depends(project_scope)):
    return await service.delete_flow(project_id, flow_id)


@router.get("/dashboard/automation/assistant/messages")
async def assistant_messages(project_id: str, session_id: str = "default", project: dict = Depends(project_scope)):
    return {"data": await service.list_messages(project_id, session_id)}


@router.post("/dashboard/automation/assistant/chat")
async def assistant_chat(project_id: str, payload: ChatRequest, project: dict = Depends(project_scope)):
    return await service.chat(project_id, payload.session_id, payload.message)
