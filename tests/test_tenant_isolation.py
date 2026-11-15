from tests.fixtures import new_session, subscribe


async def test_no_subscription_no_access():
    s = await new_session()
    await subscribe(s, product_key="crm")
    assert (await s.get("/api/v1/crm/overview")).status_code == 200
    r = await s.get("/api/v1/erp/overview")
    assert r.status_code == 403  # CRM subscription does not unlock ERP


async def test_missing_org_header():
    s = await new_session()
    await subscribe(s)
    r = await s.http.get("/api/v1/crm/overview")
    assert r.status_code == 400


async def test_tenant_isolation_idor(owner):
    lead = (await owner.post("/api/v1/crm/leads", {"name": "Lead Secreto", "custom_fields": {"hectares": 120}})).json()
    other = await new_session("Bruno Outro")
    await subscribe(other)
    assert (await other.get("/api/v1/crm/leads")).json()["items"] == []
    assert (await other.put(f"/api/v1/crm/leads/{lead['id']}", {"name": "Hack"})).status_code == 404
    assert (await other.delete(f"/api/v1/crm/leads/{lead['id']}")).status_code == 404
    other.org_id = owner.org_id  # forging another organization header
    assert (await other.get("/api/v1/crm/leads")).status_code == 403


async def test_canceled_subscription_blocks(owner):
    from bson import ObjectId
    from app.database.mongo import db
    await db.subscriptions.update_one({"organization_id": ObjectId(owner.org_id)}, {"$set": {"status": "canceled", "is_current": False}})
    assert (await owner.get("/api/v1/crm/overview")).status_code == 402


async def test_past_due_is_read_only(owner):
    from bson import ObjectId
    from app.database.mongo import db
    await db.subscriptions.update_one({"organization_id": ObjectId(owner.org_id)}, {"$set": {"status": "past_due"}})
    assert (await owner.get("/api/v1/crm/leads")).status_code == 200
    assert (await owner.post("/api/v1/crm/leads", {"name": "Novo"})).status_code == 402


async def test_admin_actions_require_mfa(owner):
    r = await owner.post("/api/v1/organizations/crm/invites", {"email": "x@example.com", "role": "member"})
    assert r.status_code == 403 and "MFA" in r.json()["detail"]


async def test_checkout_rejects_unavailable_product_and_bad_origin():
    s = await new_session()
    base = {"plan_key": "starter", "segment": "agro", "organization": {"name": "Fazenda"}, "origin_url": "https://evil.com"}
    assert (await s.post("/api/v1/billing/checkout", {**base, "product_key": "crm"})).status_code == 422
    r = await s.post("/api/v1/billing/checkout", {**base, "product_key": "erp", "origin_url": "http://localhost:3000"})
    assert r.status_code == 400


async def test_webhook_requires_signature():
    s = await new_session()
    r = await s.http.post("/api/stripe/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=bad"})
    assert r.status_code == 400
