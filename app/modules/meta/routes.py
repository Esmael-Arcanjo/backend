from fastapi import APIRouter

from app.core.config import MODULES, PLANS, SERVICE_CATALOG
from app.modules.meta.data import CURRENCIES, LANGUAGES, RATES

router = APIRouter(tags=["Meta"])


@router.get("/services")
async def services():
    return {"data": SERVICE_CATALOG}


@router.get("/currencies")
async def currencies():
    return {"data": CURRENCIES}


@router.get("/exchange_rates")
async def exchange_rates(base: str = "BRL"):
    base = base.upper()
    base_rate = RATES.get(base, 1.0)
    return {"base": base, "rates": {k: round(v / base_rate, 6) for k, v in RATES.items()}}


@router.get("/languages")
async def languages():
    return {"data": LANGUAGES}


@router.get("/plans")
async def plans():
    return {"data": PLANS, "modules": MODULES}
