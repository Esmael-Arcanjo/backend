from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pymongo.errors import DuplicateKeyError

from app.core.audit.service import audit
from app.core.authorization.deps import ProductContext, require_product
from app.database.mongo import db
from app.products.link_bio.repositories import repos
from app.products.link_bio.schemas.inputs import AvatarIn, HandleIn, LinkIn, ProfileIn, PublishIn, ReorderIn, ThemeIn
from app.products.link_bio.services import bio_service as svc
from app.products.link_bio.services.socials import NETWORKS, normalize_url
from app.shared.models import to_oid

P = "link_bio"
router = APIRouter(prefix="/api/v1/link_bio", tags=["link_bio"])
read, write, delete = (require_product(P, p) for p in ("read", "write", "delete"))


async def _log(ctx: ProductContext, action: str, request: Request, target_id=None):
    await audit(f"link_bio.{action}", user_id=ctx.user_id, organization_id=ctx.org_id, product_key=P,
                target_type="bio", target_id=target_id, request=request)


@router.get("/meta")
async def meta(ctx: ProductContext = Depends(read)):
    return {"networks": NETWORKS, "presets": svc.PRESETS,
            "suggestions": svc.suggestions(ctx.subscription["segment"])}


@router.get("/overview")
async def overview(ctx: ProductContext = Depends(read)):
    page = await svc.get_page(ctx.org_id)
    stats7 = await svc.analytics(ctx.org_id, 7)
    return {"handle": page.handle, "published": page.published, "display_name": page.display_name,
            "links_total": await repos.links.count(ctx.org_id),
            "links_active": await repos.links.count(ctx.org_id, {"active": True}),
            "socials_total": len(page.socials), "views_7d": stats7["views"], "clicks_7d": stats7["clicks"],
            "ctr_7d": stats7["ctr"], "series": stats7["series"], "top_links": stats7["top_links"][:5]}


@router.get("/page")
async def get_page(ctx: ProductContext = Depends(read)):
    return (await svc.get_page(ctx.org_id)).out()


@router.put("/page")
async def update_profile(body: ProfileIn, request: Request, ctx: ProductContext = Depends(write)):
    page = await svc.get_page(ctx.org_id)
    data = body.model_dump(exclude={"version", "socials"})
    try:
        data["socials"] = [{"network": s.network, "url": normalize_url(s.network, s.value)} for s in body.socials]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if len({s["network"] for s in data["socials"]}) != len(data["socials"]):
        raise HTTPException(status_code=422, detail="Cada rede social pode ser adicionada uma vez")
    updated = await repos.pages.update(ctx.org_id, page.id, data, body.version)
    await _log(ctx, "profile_updated", request, page.id)
    return updated.out()


@router.put("/page/handle")
async def update_handle(body: HandleIn, request: Request, ctx: ProductContext = Depends(write)):
    page = await svc.get_page(ctx.org_id)
    try:
        updated = await repos.pages.update(ctx.org_id, page.id, {"handle": body.handle})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Este endereço já está em uso")
    await _log(ctx, "handle_changed", request, page.id)
    return updated.out()


@router.put("/page/publish")
async def publish(body: PublishIn, request: Request, ctx: ProductContext = Depends(write)):
    page = await svc.get_page(ctx.org_id)
    updated = await repos.pages.update(ctx.org_id, page.id, {"published": body.published})
    await _log(ctx, "published" if body.published else "unpublished", request, page.id)
    return updated.out()


@router.put("/page/avatar")
async def set_avatar(body: AvatarIn, request: Request, ctx: ProductContext = Depends(write)):
    page = await svc.get_page(ctx.org_id)
    updated = await repos.pages.update(ctx.org_id, page.id, {"avatar": svc.validate_avatar(body.data_url)})
    await _log(ctx, "avatar_updated", request, page.id)
    return updated.out()


@router.delete("/page/avatar")
async def remove_avatar(request: Request, ctx: ProductContext = Depends(write)):
    page = await svc.get_page(ctx.org_id)
    updated = await repos.pages.update(ctx.org_id, page.id, {"avatar": None})
    await _log(ctx, "avatar_removed", request, page.id)
    return updated.out()


@router.get("/links")
async def list_links(ctx: ProductContext = Depends(read)):
    return {"items": [x.out() for x in await repos.links.list(ctx.org_id, sort=("position", 1))]}


@router.post("/links", status_code=201)
async def create_link(body: LinkIn, request: Request, ctx: ProductContext = Depends(write)):
    page = await svc.get_page(ctx.org_id)
    if await repos.links.count(ctx.org_id) >= 100:
        raise HTTPException(status_code=409, detail="Limite de 100 links atingido")
    last = await repos.links.list(ctx.org_id, sort=("position", -1), limit=1)
    link = await repos.links.create(ctx.org_id, {**body.model_dump(exclude={"version"}), "page_id": ObjectId(page.id),
                                                 "position": (last[0].position + 1) if last else 0, "clicks": 0},
                                    ctx.user_id)
    await _log(ctx, "link_created", request, link.id)
    return link.out()


@router.put("/links/reorder")
async def reorder(body: ReorderIn, request: Request, ctx: ProductContext = Depends(write)):
    current = {x.id for x in await repos.links.list(ctx.org_id, limit=200)}
    if set(body.ids) != current:
        raise HTTPException(status_code=422, detail="Lista de links inconsistente")
    for i, link_id in enumerate(body.ids):
        await db.bio_links.update_one({"_id": to_oid(link_id), "organization_id": ctx.org_id}, {"$set": {"position": i}})
    await _log(ctx, "links_reordered", request)
    return {"ok": True}


@router.put("/links/{link_id}")
async def update_link(link_id: str, body: LinkIn, request: Request, ctx: ProductContext = Depends(write)):
    link = await repos.links.update(ctx.org_id, link_id, body.model_dump(exclude={"version"}), body.version)
    await _log(ctx, "link_updated", request, link_id)
    return link.out()


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(link_id: str, request: Request, ctx: ProductContext = Depends(delete)):
    await repos.links.delete(ctx.org_id, link_id)
    await _log(ctx, "link_deleted", request, link_id)


@router.get("/theme")
async def get_theme(ctx: ProductContext = Depends(read)):
    return svc.theme_out(await svc.get_theme(ctx.org_id))


@router.put("/theme")
async def update_theme(body: ThemeIn, request: Request, ctx: ProductContext = Depends(write)):
    if body.preset not in svc.PRESETS:
        raise HTTPException(status_code=422, detail="Tema inexistente")
    theme = await svc.get_theme(ctx.org_id)
    if theme:
        await repos.themes.update(ctx.org_id, theme.id, body.model_dump())
    else:
        await repos.themes.create(ctx.org_id, body.model_dump(), ctx.user_id)
    await _log(ctx, "theme_updated", request)
    return svc.theme_out(await svc.get_theme(ctx.org_id))


@router.get("/analytics")
async def get_analytics(days: int = Query(30, ge=7, le=365), ctx: ProductContext = Depends(read)):
    return await svc.analytics(ctx.org_id, days)
