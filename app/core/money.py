"""Monetary helpers. All amounts are integers in the currency's minor unit (cents)."""

from app.core.config import settings

ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK"}


def minor_units(currency: str) -> int:
    return 0 if currency.upper() in ZERO_DECIMAL else 2


def platform_fee(amount: int) -> int:
    """Basis-point fee + fixed fee, integer math only."""
    if amount <= 0:
        return 0
    return (amount * settings.PLATFORM_FEE_BPS) // 10000 + settings.PLATFORM_FEE_FIXED


def split_amounts(amount: int, splits: list[dict]) -> list[dict]:
    """Distribute `amount` across recipients by basis points; remainder to the first."""
    if not splits:
        return []
    out = []
    allocated = 0
    for s in splits:
        part = (amount * int(s.get("bps", 0))) // 10000
        allocated += part
        out.append({"destination": s["destination"], "amount": part, "bps": int(s.get("bps", 0))})
    remainder = amount - allocated
    if remainder:
        out[0]["amount"] += remainder
    return out


def format_amount(amount: int, currency: str) -> str:
    d = minor_units(currency)
    if d == 0:
        return f"{amount} {currency.upper()}"
    return f"{amount / (10 ** d):.{d}f} {currency.upper()}"
