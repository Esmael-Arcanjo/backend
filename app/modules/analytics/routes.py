from fastapi import APIRouter, Depends

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.analytics.service import AnalyticsService

router = APIRouter(tags=["Analytics"])
service = AnalyticsService()


@router.get("/v1/analytics/overview")
async def api_overview(days: int = 30, ctx: ApiContext = Depends(scope_guard("analytics:read", "analytics"))):
    return await service.overview(ctx.project_id, ctx.project["organization_id"], days)


@router.get("/dashboard/analytics")
async def dashboard_analytics(project_id: str, days: int = 30, project: dict = Depends(project_scope)):
    data = await service.overview(project_id, project["organization_id"], days)
    data["activity"] = await service.recent_activity(project_id)
    return data


@router.get("/dashboard/search")
async def dashboard_search(project_id: str, q: str, project: dict = Depends(project_scope)):
    if len(q.strip()) < 1:
        return {"customers": [], "products": [], "sellers": [], "orders": [], "emails": []}
    return await service.global_search(project_id, q.strip())
