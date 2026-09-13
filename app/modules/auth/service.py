from datetime import timedelta, timezone

from fastapi import HTTPException

from app.core.config import SELECTABLE_SERVICES, SERVICE_MODULES, SERVICE_SCOPES
from app.core.mongo import now_utc, oid
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    random_token,
    sha256,
    verify_password,
)
from app.modules.auth.repository import LoginAttemptRepository, ResetTokenRepository, UserRepository
from app.modules.auth.schema import LoginRequest, RegisterRequest
from app.modules.wallet.service import WalletService

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Services that do NOT expose API keys.
NO_API_SERVICES = {"automation", "linkbio"}


class AuthService:
    def __init__(self) -> None:
        self.users = UserRepository()
        self.attempts = LoginAttemptRepository()
        self.resets = ResetTokenRepository()
        self.wallets = WalletService()

    async def register(self, payload: RegisterRequest) -> dict:
        if await self.users.by_email(payload.email):
            raise HTTPException(status_code=409, detail="Email already registered")
        user = await self.users.insert(
            {
                "email": payload.email.lower(),
                "password_hash": hash_password(payload.password),
                "name": payload.name,
                "role": "owner",
                "locale": "pt",
                "mfa_enabled": False,
                "banned": False,
            }
        )
        org = await self._bootstrap_organization(user["_id"], payload)
        await self.users.update(user["_id"], {"organization_id": org["id"]})
        user["organization_id"] = org["id"]
        return self._public(user)

    async def _bootstrap_organization(self, user_id: str, payload: RegisterRequest) -> dict:
        from app.modules.tenancy.service import TenancyService

        tenancy = TenancyService()
        selected = payload.service if payload.service in SELECTABLE_SERVICES + ["linkbio"] else "payments"
        modules: set[str] = set()
        modules.update(SERVICE_MODULES.get(selected, [selected]))
        # Services under subscription pricing require a paid checkout before dashboard access.
        subscription_services = {"email", "automation", "linkbio"}
        payment_pending = selected in subscription_services
        org = await tenancy.create_organization(
            owner_id=user_id, name=payload.company, country=payload.country,
            currency=payload.currency, services=[selected], locked_service=selected,
            payment_pending=payment_pending,
        )
        project = await tenancy.create_project(org["id"], name="Produção", mode="live", modules=list(modules))
        if selected not in NO_API_SERVICES:
            await tenancy.create_api_key(
                project["id"], name=f"{selected.capitalize()} key",
                scopes=SERVICE_SCOPES.get(selected, []), service=selected,
            )
        await self.wallets.ensure_wallet("organization", org["id"], payload.currency)
        return org

    async def login(self, payload: LoginRequest, ip: str) -> dict:
        identifier = payload.email.lower()
        state = await self.attempts.current(identifier)
        if state and state.get("count", 0) >= MAX_ATTEMPTS:
            last = state.get("last_at")
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if now_utc() - last < timedelta(minutes=LOCKOUT_MINUTES):
                    raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
            await self.attempts.clear(identifier)
        user = await self.users.by_email(payload.email)
        if not user or not verify_password(payload.password, user.get("password_hash", "")):
            await self.attempts.register_failure(identifier)
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if user.get("banned"):
            raise HTTPException(status_code=403, detail="Conta suspensa. Contate o suporte.")
        await self.attempts.clear(identifier)
        return self._public(user)

    def tokens(self, user: dict) -> tuple[str, str]:
        return (
            create_access_token(user["id"], user["email"], user.get("role", "owner")),
            create_refresh_token(user["id"]),
        )

    async def forgot_password(self, email: str) -> str:
        user = await self.users.by_email(email)
        token = random_token()
        if user:
            await self.resets.insert(
                {
                    "user_id": user["id"],
                    "token_hash": sha256(token),
                    "expires_at": now_utc() + timedelta(hours=1),
                    "used": False,
                }
            )
        return token

    async def reset_password(self, token: str, password: str) -> None:
        record = await self.resets.find_one({"token_hash": sha256(token), "used": False})
        if not record:
            raise HTTPException(status_code=400, detail="Invalid or expired token")
        await self.users.update(record["user_id"], {"password_hash": hash_password(password)})
        await self.resets.update(record["id"], {"used": True})

    @staticmethod
    def _public(user: dict) -> dict:
        uid = user.get("id") or user.get("_id")
        return {
            "id": str(uid),
            "email": user["email"],
            "name": user["name"],
            "role": user.get("role", "owner"),
            "organization_id": user.get("organization_id"),
            "locale": user.get("locale", "pt"),
        }

    async def seed_admin(self, email: str, password: str) -> None:
        existing = await self.users.by_email(email)
        if existing is None:
            await self.register(
                RegisterRequest(
                    name="LEAMSE Admin", email=email, password=password, company="LEAMSE HQ",
                    country="BR", currency="BRL", service="payments",
                )
            )
            admin = await self.users.by_email(email)
            await self.users.update(admin["id"], {"role": "admin"})
        else:
            updates = {}
            if not verify_password(password, existing.get("password_hash", "")):
                updates["password_hash"] = hash_password(password)
            if existing.get("role") != "admin":
                updates["role"] = "admin"
            if updates:
                await self.users.update(existing["id"], updates)
        # Migration: admin controls the platform — must not own a service.
        admin = await self.users.by_email(email)
        if admin and admin.get("organization_id"):
            from app.core.database import db as _db
            await _db.organizations.update_one(
                {"_id": oid(admin["organization_id"])},
                {"$set": {"services": [], "locked_service": None, "payment_pending": False}},
            )
            # Drop any API keys tied to the admin's projects.
            projects = await _db.projects.find({"organization_id": admin["organization_id"]}).to_list(50)
            for proj in projects:
                await _db.api_keys.delete_many({"project_id": str(proj["_id"])})
