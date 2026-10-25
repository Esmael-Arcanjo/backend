from fastapi import APIRouter, Depends

from app.core.deps import get_current_org
from app.modules.linkbio.schema import BioUpdate
from app.modules.linkbio.service import LinkBioService

router = APIRouter(tags=["Link na Bio"])
service = LinkBioService()


@router.get("/dashboard/linkbio")
async def get_bio(org: dict = Depends(get_current_org)):
    return await service.get_or_create(org)


@router.patch("/dashboard/linkbio")
async def update_bio(payload: BioUpdate, org: dict = Depends(get_current_org)):
    return await service.update(org, payload.model_dump(exclude_none=True))


@router.get("/dashboard/linkbio/analytics")
async def bio_analytics(org: dict = Depends(get_current_org)):
    return await service.analytics(org)


@router.get("/public/bio/{slug}")
async def public_bio(slug: str):
    return await service.public(slug)


@router.post("/public/bio/{slug}/view")
async def public_bio_view(slug: str):
    await service.track_view(slug)
    return {"ok": True}


@router.post("/public/bio/{slug}/click/{index}")
async def public_bio_click(slug: str, index: int):
    await service.track_click(slug, index)
    return {"ok": True}
