import os
import random
import uuid

os.environ["DB_NAME"] = os.environ.get("DB_NAME", "test_database").strip('"') + "_pytest"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402
from app.core.products_catalog.router import seed_catalog  # noqa: E402
from app.core.subscriptions.service import activate_subscription, register_provisioner  # noqa: E402
from app.database.indexes import ensure_indexes  # noqa: E402
from app.database.mongo import client as mongo_client, db  # noqa: E402
from app.products.crm.services.crm_service import provision_crm  # noqa: E402
from app.products.link_bio.services.bio_service import provision_link_bio  # noqa: E402
from app.shared.models import utcnow  # noqa: E402

PASSWORD = "SenhaForte123"


@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    await mongo_client.drop_database(db.name)
    await ensure_indexes()
    await seed_catalog()
    register_provisioner("crm", provision_crm)
    register_provisioner("link_bio", provision_link_bio)
    yield
    await mongo_client.drop_database(db.name)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    from app.core.security.rate_limit import limiter
    limiter._mem.clear()


SENT_EMAILS: list[dict] = []


@pytest.fixture(autouse=True)
def stub_email(monkeypatch):
    from app.integrations.email import sender

    async def fake_send(to, subject, html):
        SENT_EMAILS.append({"to": to, "subject": subject, "html": html})
        return "test-id"
    monkeypatch.setattr(sender, "_send_resend", fake_send)


class Session:
    def __init__(self, http: AsyncClient):
        self.http = http
        self.org_id = None

    def _headers(self):
        h = {"X-CSRF-Token": self.http.cookies.get("csrf_token", "")}
        if self.org_id:
            h["X-Organization-Id"] = self.org_id
        return h

    async def get(self, url, **kw):
        return await self.http.get(url, headers=self._headers(), **kw)

    async def post(self, url, json=None):
        return await self.http.post(url, json=json, headers=self._headers())

    async def put(self, url, json=None):
        return await self.http.put(url, json=json, headers=self._headers())

    async def delete(self, url):
        return await self.http.delete(url, headers=self._headers())


def gen_cpf() -> str:
    base = [random.randint(0, 9) for _ in range(9)]
    for n in (9, 10):
        s = sum(base[i] * (n + 1 - i) for i in range(n))
        base.append((s * 10 % 11) % 10)
    return "".join(map(str, base))


async def new_session(name="Tester") -> Session:
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    s = Session(http)
    email = f"t_{uuid.uuid4().hex[:8]}@example.com"
    r = await s.post("/api/v1/auth/register", {"name": name, "email": email, "document": gen_cpf(),
                                               "password": PASSWORD})
    assert r.status_code == 200, r.text
    s.email = email
    return s


async def subscribe(s: Session, product_key="crm", segment="agro") -> str:
    """Creates an organization + subscription for the session user and activates it server-side."""
    me = (await s.get("/api/v1/auth/me")).json()["user"]
    from bson import ObjectId
    uid = ObjectId(me["id"])
    now = utcnow()
    org_id = (await db.organizations.insert_one({"name": f"Org {me['name']}", "owner_id": uid, "status": "active",
                                                 "country": "BR", "created_at": now})).inserted_id
    await db.organization_members.insert_one({"organization_id": org_id, "user_id": uid, "role": "owner",
                                              "status": "active", "created_at": now})
    sub_id = (await db.subscriptions.insert_one({
        "organization_id": org_id, "product_key": product_key, "plan_key": "starter", "segment": segment,
        "status": "pending", "is_current": False, "created_by": uid, "price_cents": 9900, "currency": "brl",
        "created_at": now, "updated_at": now})).inserted_id
    assert await activate_subscription(sub_id, None, None, "test")
    s.org_id = str(org_id)
    return str(org_id)


@pytest.fixture
async def owner():
    s = await new_session("Ana Dona")
    await subscribe(s)
    yield s
    await s.http.aclose()
