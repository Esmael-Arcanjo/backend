import logging

import httpx
from fastapi import HTTPException

from app.core.security.crypto import decrypt

logger = logging.getLogger("evolution")


async def _call(cfg: dict, method: str, path: str, json: dict | None = None) -> dict:
    url = cfg["base_url"].rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.request(method, url, headers={"apikey": decrypt(cfg["api_key_enc"])}, json=json)
    except httpx.HTTPError as e:
        logger.warning("Evolution unreachable: %s", e)
        raise HTTPException(status_code=502, detail="Não foi possível conectar ao servidor Evolution API")
    if r.status_code >= 400:
        logger.warning("Evolution %s %s -> %s %s", method, path, r.status_code, r.text[:200])
        raise HTTPException(status_code=502, detail=f"Evolution API respondeu com erro {r.status_code}")
    return r.json() if r.content else {}


async def create_instance(cfg: dict, webhook_url: str) -> dict:
    return await _call(cfg, "POST", "/instance/create", {
        "instanceName": cfg["instance"], "qrcode": True, "integration": "WHATSAPP-BAILEYS",
        "webhook": {"url": webhook_url, "byEvents": False, "base64": False,
                    "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]}})


async def connect(cfg: dict) -> dict:
    return await _call(cfg, "GET", f"/instance/connect/{cfg['instance']}")


async def state(cfg: dict) -> str:
    data = await _call(cfg, "GET", f"/instance/connectionState/{cfg['instance']}")
    return (data.get("instance") or {}).get("state") or data.get("state") or "close"


async def logout(cfg: dict) -> None:
    await _call(cfg, "DELETE", f"/instance/logout/{cfg['instance']}")


async def send_text(cfg: dict, number: str, text: str) -> dict:
    return await _call(cfg, "POST", f"/message/sendText/{cfg['instance']}", {"number": number, "text": text})
