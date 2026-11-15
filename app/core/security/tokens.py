import hashlib
import secrets
from datetime import timedelta

import jwt
from fastapi import HTTPException

from app.core.config.settings import settings
from app.shared.models import utcnow

ALGORITHM = "HS256"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_jwt(sub: str, typ: str, minutes: int, **claims) -> str:
    now = utcnow()
    payload = {"sub": sub, "typ": typ, "iat": now, "exp": now + timedelta(minutes=minutes),
               "jti": secrets.token_hex(8), **claims}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_jwt(token: str, typ: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
    if payload.get("typ") != typ:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
    return payload
