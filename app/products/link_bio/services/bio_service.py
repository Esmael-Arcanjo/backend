import base64
import re
import secrets
import unicodedata
from datetime import timedelta

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.database.mongo import db
from app.products.link_bio.repositories import repos
from app.shared.models import utcnow

PRESETS = {
    "grafite": {"name": "Grafite", "background": "#0B0F14", "text": "#F8FAFC", "card": "#1F2937"},
    "papel": {"name": "Papel", "background": "#F7F5EF", "text": "#111827", "card": "#FFFFFF"},
    "oceano": {"name": "Oceano", "background": "#0C4A6E", "text": "#F0F9FF", "card": "#075985"},
    "floresta": {"name": "Floresta", "background": "#14532D", "text": "#F0FDF4", "card": "#166534"},
    "areia": {"name": "Areia", "background": "#FDF6E3", "text": "#3F2D20", "card": "#F3E5C8"},
    "rubi": {"name": "Rubi", "background": "#4C0519", "text": "#FFF1F2", "card": "#881337"},
}

SEGMENT_DEFAULTS = {
    "agro": ("floresta", "#65A30D", ["Catálogo de produtos", "Fale com um consultor"]),
    "educacao": ("oceano", "#0EA5E9", ["Matrículas abertas", "Conheça nossos cursos"]),
    "hotelaria": ("areia", "#B45309", ["Reserve agora", "Fotos das acomodações"]),
    "juridico": ("grafite", "#C9A227", ["Agende uma consulta", "Áreas de atuação"]),
    "logistica": ("oceano", "#F97316", ["Solicite uma cotação", "Rastreie sua carga"]),
    "servicos": ("papel", "#0F766E", ["Solicite um orçamento", "Portfólio"]),
    "saude": ("papel", "#0891B2", ["Agende sua consulta", "Convênios atendidos"]),
    "comercio": ("rubi", "#F43F5E", ["Loja online", "Promoções da semana"]),
}

AVATAR_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
MAGIC = {"png": b"\x89PNG", "jpeg": b"\xff\xd8\xff", "webp": b"RIFF"}
MAX_AVATAR_BYTES = 500_000


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:20] or "perfil"


def validate_avatar(data_url: str) -> str:
    match = AVATAR_RE.match(data_url)
    if not match:
        raise HTTPException(status_code=422, detail="Envie uma imagem PNG, JPEG ou WEBP")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError:
        raise HTTPException(status_code=422, detail="Imagem inválida")
    if len(raw) > MAX_AVATAR_BYTES or not raw.startswith(MAGIC[match.group(1)]):
        raise HTTPException(status_code=422, detail="Imagem inválida ou maior que 500 KB")
    return data_url


async def provision_link_bio(subscription: dict) -> None:
    org_id = subscription["organization_id"]
    if await db.bio_pages.count_documents({"organization_id": org_id}, limit=1):
        return
    org = await db.organizations.find_one({"_id": org_id})
    preset, accent, _ = SEGMENT_DEFAULTS[subscription["segment"]]
    now = utcnow()
    base = {"organization_id": org_id, "created_at": now, "updated_at": now, "version": 1}
    for _ in range(5):
        handle = f"{_slug(org['name'])}-{secrets.token_hex(2)}"
        try:
            await db.bio_pages.insert_one({
                **base, "handle": handle, "profile_type": "company", "display_name": org["name"], "title": None,
                "description": None, "location": None, "show_map": True, "avatar": None, "socials": [],
                "published": True, "segment": subscription["segment"]})
            break
        except DuplicateKeyError:
            if await db.bio_pages.count_documents({"organization_id": org_id}, limit=1):
                return
    else:
        raise RuntimeError("Could not allocate bio handle")
    await db.bio_themes.update_one({"organization_id": org_id}, {"$setOnInsert": {
        **base, "preset": preset, "accent": accent, "button_style": "rounded"}}, upsert=True)


def suggestions(segment: str) -> list:
    return SEGMENT_DEFAULTS.get(segment, SEGMENT_DEFAULTS["servicos"])[2]


async def get_page(org_id: ObjectId):
    found = await repos.pages.list(org_id, limit=1)
    if not found:
        raise HTTPException(status_code=404, detail="Página não provisionada")
    return found[0]


async def get_theme(org_id: ObjectId):
    found = await repos.themes.list(org_id, limit=1)
    return found[0] if found else None


def theme_out(theme) -> dict:
    data = {"preset": "grafite", "accent": "#111827", "button_style": "rounded"}
    if theme:
        data = {"preset": theme.preset, "accent": theme.accent, "button_style": theme.button_style}
    return {**data, **PRESETS.get(data["preset"], PRESETS["grafite"])}


def today() -> str:
    return utcnow().strftime("%Y-%m-%d")


async def track(org_id: ObjectId, field: str) -> None:
    await db.bio_analytics.update_one({"organization_id": org_id, "date": today()}, {"$inc": {field: 1}}, upsert=True)


async def analytics(org_id: ObjectId, days: int) -> dict:
    start = (utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    docs = await db.bio_analytics.find({"organization_id": org_id, "date": {"$gte": start}}).sort("date", 1).to_list(400)
    by_date = {d["date"]: d for d in docs}
    series = []
    for i in range(days):
        day = (utcnow() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        d = by_date.get(day, {})
        series.append({"date": day, "views": d.get("views", 0),
                       "clicks": sum(d.get("link_clicks", {}).values()) + sum(d.get("social_clicks", {}).values())})
    link_totals: dict = {}
    social_totals: dict = {}
    for d in docs:
        for k, v in d.get("link_clicks", {}).items():
            link_totals[k] = link_totals.get(k, 0) + v
        for k, v in d.get("social_clicks", {}).items():
            social_totals[k] = social_totals.get(k, 0) + v
    titles = {str(lk.id): lk.title for lk in await repos.links.list(org_id, limit=200)}
    views = sum(s["views"] for s in series)
    clicks = sum(s["clicks"] for s in series)
    return {
        "days": days, "views": views, "clicks": clicks, "ctr": round(clicks / views, 2) if views else 0,
        "series": series,
        "top_links": sorted([{"id": k, "title": titles.get(k, "Link removido"), "clicks": v}
                             for k, v in link_totals.items()], key=lambda x: -x["clicks"])[:10],
        "socials": sorted([{"network": k, "clicks": v} for k, v in social_totals.items()], key=lambda x: -x["clicks"]),
    }
