from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request

from app.core.security.rate_limit import client_ip, limiter, rate_limit
from app.database.mongo import db
from app.products.link_bio.schemas.inputs import ClickIn
from app.products.link_bio.services import bio_service as svc

router = APIRouter(prefix="/api/v1/public/bio", tags=["link_bio_public"])


async def _published(handle: str) -> dict:
    page = await db.bio_pages.find_one({"handle": handle.lower()[:30], "published": True})
    if not page:
        raise HTTPException(status_code=404, detail="Página não encontrada")
    sub = await db.subscriptions.find_one({"organization_id": page["organization_id"], "product_key": "link_bio",
                                           "is_current": True, "status": {"$in": ["active", "past_due"]}})
    if not sub:
        raise HTTPException(status_code=404, detail="Página não encontrada")
    return page


@router.get("/{handle}", dependencies=[rate_limit("bio-view", 120, 60)])
async def public_page(handle: str, request: Request):
    page = await _published(handle)
    links = await db.bio_links.find({"organization_id": page["organization_id"], "active": True}) \
        .sort("position", 1).to_list(100)
    theme = await db.bio_themes.find_one({"organization_id": page["organization_id"]})
    if await limiter.hit(f"bio-uniq:{page['_id']}:{client_ip(request)}", 1, 1800):
        await svc.track(page["organization_id"], "views")
    t = svc.theme_out(None) if not theme else {**svc.PRESETS.get(theme["preset"], svc.PRESETS["grafite"]),
                                               "preset": theme["preset"], "accent": theme["accent"],
                                               "button_style": theme["button_style"]}
    return {"handle": page["handle"], "profile_type": page["profile_type"], "display_name": page["display_name"],
            "title": page.get("title"), "description": page.get("description"), "location": page.get("location"),
            "show_map": page.get("show_map", True), "avatar": page.get("avatar"), "socials": page.get("socials", []),
            "links": [{"id": str(lk["_id"]), "title": lk["title"], "url": lk["url"]} for lk in links], "theme": t}


@router.post("/{handle}/click", dependencies=[rate_limit("bio-click", 60, 60)])
async def public_click(handle: str, body: ClickIn):
    page = await _published(handle)
    org_id = page["organization_id"]
    if body.link_id:
        if not ObjectId.is_valid(body.link_id):
            raise HTTPException(status_code=404, detail="Link não encontrado")
        result = await db.bio_links.update_one({"_id": ObjectId(body.link_id), "organization_id": org_id,
                                                "active": True}, {"$inc": {"clicks": 1}})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Link não encontrado")
        await svc.track(org_id, f"link_clicks.{body.link_id}")
    elif body.network and body.network in {s["network"] for s in page.get("socials", [])}:
        await svc.track(org_id, f"social_clicks.{body.network}")
    else:
        raise HTTPException(status_code=422, detail="Clique inválido")
    return {"ok": True}
