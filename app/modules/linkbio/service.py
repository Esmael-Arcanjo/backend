"""Link na Bio — persistence + analytics."""
import re
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.database import db
from app.modules.linkbio.repository import BioPageRepository


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:40]


def _clean_domain(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = text.split("/")[0].strip()
    if text and not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", text):
        raise HTTPException(status_code=400, detail="Domínio inválido (ex: meusite.com)")
    return text


class LinkBioService:
    def __init__(self) -> None:
        self.pages = BioPageRepository()

    async def get_or_create(self, org: dict) -> dict:
        page = await self.pages.find_one({"organization_id": org["id"]})
        if page:
            return page
        base = slugify(org.get("name", "leamse")) or "leamse"
        slug = f"{base}-{secrets.token_hex(3)}"
        page = await self.pages.insert(
            {
                "organization_id": org["id"],
                "slug": slug,
                "display_name": org.get("name", ""),
                "headline": "",
                "bio": "",
                "avatar_url": "",
                "cover_url": "",
                "custom_domain": "",
                "accent": "#F97316",
                "theme": "light",
                "whatsapp": "",
                "links": [],
                "products": [],
                "published": True,
                "views": 0,
            }
        )
        page["id"] = page.pop("_id")
        return page

    async def update(self, org: dict, changes: dict) -> dict:
        page = await self.get_or_create(org)
        if changes.get("slug"):
            new_slug = slugify(changes["slug"])
            if not new_slug:
                raise HTTPException(status_code=400, detail="Slug inválido")
            existing = await self.pages.find_one({"slug": new_slug})
            if existing and existing["id"] != page["id"]:
                raise HTTPException(status_code=409, detail="Slug já em uso")
            changes["slug"] = new_slug
        if "custom_domain" in changes:
            domain = _clean_domain(changes["custom_domain"])
            if domain:
                clash = await self.pages.find_one({"custom_domain": domain})
                if clash and clash["id"] != page["id"]:
                    raise HTTPException(status_code=409, detail="Domínio já em uso")
            changes["custom_domain"] = domain
        return await self.pages.update(page["id"], changes, extra={"organization_id": org["id"]})

    async def public(self, slug: str) -> dict:
        page = await self.pages.find_one({"slug": slug, "published": True})
        if not page:
            page = await self.pages.find_one({"custom_domain": slug, "published": True})
        if not page:
            raise HTTPException(status_code=404, detail="Página não encontrada")
        page.pop("organization_id", None)
        return page

    async def track_view(self, slug: str) -> None:
        """Increment page view counter and record daily aggregate."""
        page = await self.pages.find_one({"slug": slug, "published": True})
        if not page:
            page = await self.pages.find_one({"custom_domain": slug, "published": True})
        if not page:
            return
        await db.bio_pages.update_one({"_id": page["id"] if "_id" not in page else page["_id"],
                                       "slug": page["slug"]},
                                      {"$inc": {"views": 1}})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await db.bio_events.update_one(
            {"page_id": page["id"], "day": today, "kind": "view"},
            {"$inc": {"count": 1}}, upsert=True,
        )

    async def track_click(self, slug: str, index: int) -> None:
        page = await self.pages.find_one({"slug": slug, "published": True})
        if not page:
            page = await self.pages.find_one({"custom_domain": slug, "published": True})
        if not page:
            return
        links = page.get("links") or []
        if index < 0 or index >= len(links):
            return
        label = links[index].get("label", f"link-{index}")
        await db.bio_events.update_one(
            {"page_id": page["id"], "kind": "click", "link_index": index},
            {"$inc": {"count": 1}, "$set": {"label": label}}, upsert=True,
        )

    async def analytics(self, org: dict) -> dict:
        page = await self.get_or_create(org)
        clicks_cursor = db.bio_events.find({"page_id": page["id"], "kind": "click"})
        clicks: list[dict] = []
        async for e in clicks_cursor:
            clicks.append({"index": e.get("link_index", 0),
                           "label": e.get("label") or f"link-{e.get('link_index', 0)}",
                           "count": e.get("count", 0)})
        clicks.sort(key=lambda x: x["count"], reverse=True)
        # Last 14-day view series.
        from datetime import timedelta
        today = datetime.now(timezone.utc).date()
        days = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
        events = await db.bio_events.find({
            "page_id": page["id"], "kind": "view", "day": {"$in": days},
        }).to_list(50)
        by_day = {e["day"]: e.get("count", 0) for e in events}
        series = [{"day": d[5:], "views": by_day.get(d, 0)} for d in days]
        return {
            "total_views": page.get("views", 0),
            "total_clicks": sum(c["count"] for c in clicks),
            "series": series,
            "top_links": clicks[:10],
        }
