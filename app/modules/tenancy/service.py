from fastapi import HTTPException

from app.core.config import MODULES, PLANS, SCOPES
from app.core.security import generate_api_key_pair, sha256
from app.modules.tenancy.repository import ApiKeyRepository, OrganizationRepository, ProjectRepository


class TenancyService:
    def __init__(self) -> None:
        self.orgs = OrganizationRepository()
        self.projects = ProjectRepository()
        self.keys = ApiKeyRepository()

    async def create_organization(self, owner_id: str, name: str, country: str, currency: str,
                                  services: list[str] | None = None,
                                  locked_service: str | None = None,
                                  payment_pending: bool = False) -> dict:
        doc = await self.orgs.insert(
            {"name": name, "owner_id": owner_id, "country": country, "default_currency": currency.upper(),
             "plan": "business", "services": services or [],
             "locked_service": locked_service or (services[0] if services else None),
             "payment_pending": payment_pending}
        )
        doc["id"] = doc.pop("_id")
        return doc

    async def get_organization(self, org_id: str) -> dict:
        org = await self.orgs.get(org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        return org

    async def update_organization(self, org_id: str, changes: dict) -> dict:
        if changes.get("plan"):
            plan = PLANS[changes["plan"]]
            projects = await self.projects.find_many({"organization_id": org_id}, limit=100)
            for p in projects:
                if p["mode"] == "live" and not plan["live_mode"]:
                    continue
                await self.projects.update(p["id"], {"modules": plan["modules"]})
        return await self.orgs.update(org_id, changes)

    async def create_project(self, org_id: str, name: str, mode: str, modules: list[str]) -> dict:
        clean = [m for m in modules if m in MODULES]
        doc = await self.projects.insert(
            {"organization_id": org_id, "name": name, "mode": mode, "modules": clean}
        )
        doc["id"] = doc.pop("_id")
        return doc

    async def list_projects(self, org_id: str) -> list[dict]:
        return await self.projects.find_many({"organization_id": org_id}, limit=100)

    async def update_project(self, org_id: str, project_id: str, changes: dict) -> dict:
        if "modules" in changes and changes["modules"] is not None:
            changes["modules"] = [m for m in changes["modules"] if m in MODULES]
        project = await self.projects.update(project_id, changes, extra={"organization_id": org_id})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    async def create_api_key(self, project_id: str, name: str, scopes: list[str] | None = None,
                             org_id: str | None = None, service: str | None = None) -> dict:
        query: dict = {"organization_id": org_id} if org_id else {}
        project = await self.projects.get(project_id, extra=query or None)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        pair = generate_api_key_pair(project["mode"])
        allowed = [s for s in (scopes or SCOPES) if s in SCOPES]
        doc = await self.keys.insert(
            {
                "project_id": project_id,
                "name": name,
                "service": service,
                "publishable_key": pair["publishable_key"],
                "secret_hash": sha256(pair["secret_key"]),
                "secret_preview": pair["secret_key"][:14] + "..." + pair["secret_key"][-4:],
                "scopes": allowed,
                "revoked": False,
            }
        )
        return {
            "id": doc["_id"],
            "project_id": project_id,
            "name": name,
            "service": service,
            "publishable_key": pair["publishable_key"],
            "secret_key": pair["secret_key"],
            "secret_preview": doc["secret_preview"],
            "scopes": allowed,
            "revoked": False,
        }

    async def list_api_keys(self, project_id: str, org_id: str | None = None) -> list[dict]:
        if org_id:
            await self._owned_project(project_id, org_id)
        keys = await self.keys.find_many({"project_id": project_id}, limit=100)
        for k in keys:
            k.pop("secret_hash", None)
        return keys

    async def _owned_project(self, project_id: str, org_id: str) -> dict:
        project = await self.projects.get(project_id, extra={"organization_id": org_id})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    async def _owned_key(self, key_id: str, org_id: str) -> dict:
        key = await self.keys.get(key_id)
        if not key:
            raise HTTPException(status_code=404, detail="API key not found")
        await self._owned_project(key["project_id"], org_id)
        return key

    async def revoke_api_key(self, key_id: str, org_id: str) -> dict:
        await self._owned_key(key_id, org_id)
        key = await self.keys.update(key_id, {"revoked": True})
        key.pop("secret_hash", None)
        return key

    async def rotate_api_key(self, key_id: str, org_id: str) -> dict:
        key = await self._owned_key(key_id, org_id)
        await self.keys.update(key_id, {"revoked": True})
        return await self.create_api_key(key["project_id"], key["name"], key.get("scopes"), org_id)

    async def delete_api_key(self, key_id: str, org_id: str) -> dict:
        key = await self._owned_key(key_id, org_id)
        await self.keys.delete(key_id)
        return {"status": "deleted", "id": key_id}

