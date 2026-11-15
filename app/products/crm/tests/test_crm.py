from tests.fixtures import new_session, subscribe


async def test_segment_pipeline_provisioned(owner):
    p = (await owner.get("/api/v1/crm/pipeline")).json()
    assert p["segment"] == "agro" and p["stages"][0]["key"] == "visita"
    cfg = (await owner.get("/api/v1/crm/segment-config")).json()
    assert any(f["key"] == "hectares" for f in cfg["lead_fields"])


async def test_custom_field_validation(owner):
    assert (await owner.post("/api/v1/crm/leads", {"name": "Lead", "custom_fields": {"inexistente": "x"}})).status_code == 422
    assert (await owner.post("/api/v1/crm/leads", {"name": "Lead", "custom_fields": {"hectares": "muito"}})).status_code == 422


async def test_lead_convert_and_overview(owner):
    lead = (await owner.post("/api/v1/crm/leads", {"name": "Fazenda Boa", "value_cents": 500000,
                                                   "custom_fields": {"hectares": 300}})).json()
    conv = (await owner.post(f"/api/v1/crm/leads/{lead['id']}/convert")).json()
    assert conv["contact_id"] and conv["opportunity_id"]
    assert (await owner.post(f"/api/v1/crm/leads/{lead['id']}/convert")).status_code == 409
    ov = (await owner.get("/api/v1/crm/overview")).json()
    assert ov["open_opportunities"] == 1 and ov["open_value_cents"] == 500000 and ov["contacts_total"] == 1


async def test_optimistic_concurrency(owner):
    c = (await owner.post("/api/v1/crm/contacts", {"name": "Carla"})).json()
    assert (await owner.put(f"/api/v1/crm/contacts/{c['id']}", {"name": "Carla 2", "version": 1})).status_code == 200
    assert (await owner.put(f"/api/v1/crm/contacts/{c['id']}", {"name": "Carla 3", "version": 1})).status_code == 409


async def test_opportunity_invalid_stage_and_foreign_contact(owner):
    assert (await owner.post("/api/v1/crm/opportunities", {"title": "Opp", "stage_key": "nao_existe"})).status_code == 422
    other = await new_session()
    await subscribe(other)
    foreign = (await other.post("/api/v1/crm/contacts", {"name": "Externo"})).json()
    r = await owner.post("/api/v1/crm/opportunities", {"title": "Opp", "stage_key": "visita", "contact_id": foreign["id"]})
    assert r.status_code == 422


async def test_activity_and_audit(owner):
    a = (await owner.post("/api/v1/crm/activities", {"type": "call", "subject": "Ligar"})).json()
    assert a["done"] is False
    events = (await owner.get("/api/v1/audit/crm")).json()["events"]
    assert any(e["action"] == "crm.activity_created" for e in events)
