from fastapi import APIRouter, Depends, Request

from app.core.deps import get_current_org
from app.modules.subscriptions.schema import SubscriptionCreate
from app.modules.subscriptions.service import SubscriptionService, get_pricing

router = APIRouter(prefix="/dashboard/subscription", tags=["Subscriptions"])
service = SubscriptionService()


@router.get("")
async def get_subscription(org: dict = Depends(get_current_org)):
    return {
        "subscription": await service.current(org["id"]),
        "invoices": await service.list_invoices(org["id"]),
        "pricing": await get_pricing(),
    }


@router.post("")
async def subscribe(payload: SubscriptionCreate, org: dict = Depends(get_current_org)):
    return await service.subscribe(org["id"], payload.service, payload.interval, payload.currency)


@router.post("/renew")
async def renew(org: dict = Depends(get_current_org)):
    return await service.renew(org["id"])


@router.post("/cancel")
async def cancel(org: dict = Depends(get_current_org)):
    return await service.cancel(org["id"])


# Public pricing (no auth) so signup can show prices before account exists.
public_router = APIRouter(prefix="/public", tags=["Public"])


@public_router.get("/pricing")
async def public_pricing():
    return await get_pricing()


@public_router.get("/geo")
async def public_geo(request: Request):
    """Detect country + suggested currency from client IP (best-effort)."""
    import urllib.request, json as _json

    # Emergent proxy forwards real IP in x-forwarded-for.
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    country = "BR"
    currency = "BRL"
    try:
        if ip and not ip.startswith(("127.", "10.", "192.168.")):
            req = urllib.request.Request(f"https://ipapi.co/{ip}/json/",
                                         headers={"User-Agent": "leamse/1.0"})
            with urllib.request.urlopen(req, timeout=3) as r:
                data = _json.load(r)
                country = data.get("country_code") or country
                currency = data.get("currency") or currency
    except Exception:
        pass
    return {"ip": ip, "country": country, "currency": currency}
