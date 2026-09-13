from fastapi import APIRouter, Depends

from app.core.config import MODULES, PLANS, SCOPES
from app.core.deps import get_current_org, get_current_user
from app.modules.tenancy.schema import ApiKeyCreate, OrganizationUpdate, ProjectCreate, ProjectUpdate
from app.modules.tenancy.service import TenancyService

router = APIRouter(tags=["Organizations & Projects"])
service = TenancyService()


@router.get("/organization")
async def get_org(org: dict = Depends(get_current_org)):
    return {**org, "available_modules": MODULES, "plans": PLANS}


@router.patch("/organization")
async def update_org(payload: OrganizationUpdate, org: dict = Depends(get_current_org)):
    return await service.update_organization(org["id"], payload.model_dump(exclude_none=True))


@router.get("/projects")
async def list_projects(org: dict = Depends(get_current_org)):
    return await service.list_projects(org["id"])


@router.post("/projects")
async def create_project(payload: ProjectCreate, org: dict = Depends(get_current_org)):
    project = await service.create_project(org["id"], payload.name, payload.mode, payload.modules)
    await service.create_api_key(project["id"], f"Default {payload.name} key", SCOPES)
    return project


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdate, org: dict = Depends(get_current_org)):
    return await service.update_project(org["id"], project_id, payload.model_dump(exclude_none=True))


@router.get("/projects/{project_id}/api-keys")
async def list_keys(project_id: str, org: dict = Depends(get_current_org)):
    return await service.list_api_keys(project_id, org["id"])


@router.post("/projects/{project_id}/api-keys")
async def create_key(project_id: str, payload: ApiKeyCreate, org: dict = Depends(get_current_org)):
    from app.core.config import SERVICE_SCOPES

    scopes = payload.scopes or (SERVICE_SCOPES.get(payload.service) if payload.service else None)
    return await service.create_api_key(project_id, payload.name, scopes, org["id"], service=payload.service)


@router.post("/api-keys/{key_id}/revoke")
async def revoke_key(key_id: str, org: dict = Depends(get_current_org)):
    return await service.revoke_api_key(key_id, org["id"])


@router.post("/api-keys/{key_id}/rotate")
async def rotate_key(key_id: str, org: dict = Depends(get_current_org)):
    return await service.rotate_api_key(key_id, org["id"])


@router.delete("/api-keys/{key_id}")
async def delete_key(key_id: str, org: dict = Depends(get_current_org)):
    return await service.delete_api_key(key_id, org["id"])


@router.get("/scopes")
async def list_scopes(user: dict = Depends(get_current_user)):
    return {"scopes": SCOPES, "modules": MODULES}
