"""LEAMSE backend regression tests.

Covers: auth (register/login/me), org bootstrap (single live project + per-service keys),
automation dashboard (overview/appointments/contacts/flows/assistant), linkbio,
service-scoped api keys, automation public API + scope guards.
"""

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://leamse-automation.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@leamse.com"
ADMIN_PASSWORD = "Leamse@2026"


# --------- Fixtures ---------
@pytest.fixture(scope="session")
def admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="session")
def admin_project(admin_session):
    r = admin_session.get(f"{API}/projects")
    assert r.status_code == 200
    projects = r.json()
    assert len(projects) >= 1
    live = [p for p in projects if p["mode"] == "live"]
    assert len(live) >= 1, "no live project"
    return live[0]


@pytest.fixture(scope="session")
def new_user_session():
    """Register a brand-new user selecting only payments+automation to test bootstrap."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    email = f"test.user.{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "name": "Test User",
        "email": email,
        "password": "Test1234!",
        "company": "TEST Co",
        "country": "BR",
        "currency": "BRL",
        "services": ["payments", "automation"],
    }
    r = s.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    token = r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return {"session": s, "email": email}


# --------- Auth ---------
class TestAuth:
    def test_health(self):
        r = requests.get(f"{API}/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_admin_login(self, admin_session):
        r = admin_session.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_admin_has_all_services(self, admin_session):
        r = admin_session.get(f"{API}/organization")
        assert r.status_code == 200
        svc = r.json().get("services", [])
        for s in ["payments", "marketplace", "email", "automation", "linkbio"]:
            assert s in svc, f"missing service {s} in {svc}"


# --------- Bootstrap for new user ---------
class TestRegistrationBootstrap:
    def test_new_user_single_live_project(self, new_user_session):
        s = new_user_session["session"]
        r = s.get(f"{API}/projects")
        assert r.status_code == 200
        projects = r.json()
        assert len(projects) == 1, f"expected exactly 1 project, got {len(projects)}"
        p = projects[0]
        assert p["mode"] == "live"
        # Only modules for payments + automation
        assert "payments" in p["modules"]
        assert "automation" in p["modules"]
        assert "email" not in p["modules"]
        assert "marketplace" not in p["modules"]

    def test_new_user_has_per_service_keys(self, new_user_session):
        s = new_user_session["session"]
        r = s.get(f"{API}/projects")
        pid = r.json()[0]["id"]
        k = s.get(f"{API}/projects/{pid}/api-keys")
        assert k.status_code == 200
        keys = k.json()
        services = sorted([x.get("service") for x in keys if x.get("service")])
        assert "payments" in services
        assert "automation" in services
        assert "email" not in services
        assert "marketplace" not in services


# --------- Automation Dashboard ---------
class TestAutomationDashboard:
    def test_overview(self, admin_session, admin_project):
        r = admin_session.get(f"{API}/dashboard/automation/overview", params={"project_id": admin_project["id"]})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, dict)

    def test_appointment_crud(self, admin_session, admin_project):
        pid = admin_project["id"]
        payload = {
            "customer_name": "TEST John",
            "contact": "+55 11 99999-0000",
            "service_name": "Consulta",
            "scheduled_at": "2026-06-01T10:00:00Z",
            "notes": "TEST",
        }
        r = admin_session.post(f"{API}/dashboard/automation/appointments",
                               params={"project_id": pid}, json=payload)
        assert r.status_code == 200, r.text
        appt = r.json()
        appt_id = appt.get("id") or appt.get("_id")
        assert appt_id

        # list
        rl = admin_session.get(f"{API}/dashboard/automation/appointments", params={"project_id": pid})
        assert rl.status_code == 200
        found = [a for a in rl.json()["data"] if (a.get("id") or a.get("_id")) == appt_id]
        assert found

        # update status
        ru = admin_session.patch(f"{API}/dashboard/automation/appointments/{appt_id}",
                                 params={"project_id": pid}, json={"status": "confirmed"})
        assert ru.status_code == 200
        assert ru.json().get("status") == "confirmed"

        # delete
        rd = admin_session.delete(f"{API}/dashboard/automation/appointments/{appt_id}",
                                  params={"project_id": pid})
        assert rd.status_code == 200

    def test_contact_crud(self, admin_session, admin_project):
        pid = admin_project["id"]
        payload = {"name": "TEST Contact", "email": "test_c@leamse.test", "stage": "lead"}
        r = admin_session.post(f"{API}/dashboard/automation/contacts", params={"project_id": pid}, json=payload)
        assert r.status_code == 200, r.text
        c = r.json()
        cid = c.get("id") or c.get("_id")
        assert cid

        # move stage
        ru = admin_session.patch(f"{API}/dashboard/automation/contacts/{cid}",
                                 params={"project_id": pid}, json={"stage": "qualified"})
        assert ru.status_code == 200
        assert ru.json().get("stage") == "qualified"

        # delete
        rd = admin_session.delete(f"{API}/dashboard/automation/contacts/{cid}", params={"project_id": pid})
        assert rd.status_code == 200

    def test_flow_crud(self, admin_session, admin_project):
        pid = admin_project["id"]
        r = admin_session.post(f"{API}/dashboard/automation/flows",
                               params={"project_id": pid},
                               json={"name": "TEST Flow", "trigger": "manual", "action": "send_email"})
        assert r.status_code == 200, r.text
        f = r.json()
        fid = f.get("id") or f.get("_id")
        # toggle
        ru = admin_session.patch(f"{API}/dashboard/automation/flows/{fid}",
                                 params={"project_id": pid}, json={"active": True})
        assert ru.status_code == 200
        assert ru.json().get("active") is True
        # delete
        rd = admin_session.delete(f"{API}/dashboard/automation/flows/{fid}", params={"project_id": pid})
        assert rd.status_code == 200

    def test_assistant_chat(self, admin_session, admin_project):
        pid = admin_project["id"]
        session_id = f"TEST_sess_{uuid.uuid4().hex[:6]}"
        payload = {"session_id": session_id, "message": "Olá, quais são meus próximos compromissos?"}
        r = admin_session.post(f"{API}/dashboard/automation/assistant/chat",
                               params={"project_id": pid}, json=payload, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        # expect a reply / text field
        assert any(k in data for k in ("reply", "message", "text", "content")), f"no reply in {data}"

        rh = admin_session.get(f"{API}/dashboard/automation/assistant/messages",
                               params={"project_id": pid, "session_id": session_id})
        assert rh.status_code == 200
        msgs = rh.json()["data"]
        assert len(msgs) >= 2  # user + assistant


# --------- Link na Bio ---------
class TestLinkBio:
    def test_get_or_create(self, admin_session):
        r = admin_session.get(f"{API}/dashboard/linkbio")
        assert r.status_code == 200, r.text
        bio = r.json()
        assert "slug" in bio

    def test_update(self, admin_session):
        r = admin_session.patch(f"{API}/dashboard/linkbio",
                                json={"headline": "TEST headline", "slug": "leamse-automation"})
        assert r.status_code == 200, r.text
        assert r.json().get("headline") == "TEST headline"

    def test_public(self, admin_session):
        # ensure a published bio exists
        admin_session.patch(f"{API}/dashboard/linkbio",
                            json={"slug": "leamse-automation", "name": "LEAMSE", "published": True})
        r = requests.get(f"{API}/public/bio/leamse-automation")
        assert r.status_code == 200, r.text


# --------- Per-service API keys & scope guard ---------
class TestApiKeysAndScope:
    def test_create_automation_key_and_call_api(self, admin_session, admin_project):
        pid = admin_project["id"]
        r = admin_session.post(f"{API}/projects/{pid}/api-keys",
                               json={"name": "TEST auto key", "service": "automation"})
        assert r.status_code == 200, r.text
        key_data = r.json()
        secret = key_data["secret_key"]
        assert "automation:read" in key_data["scopes"]

        # Use the key on v1 automation endpoint
        r2 = requests.post(f"{API}/v1/automation/contacts",
                           headers={"X-Api-Key": secret, "Content-Type": "application/json"},
                           json={"name": "TEST APICONTACT", "stage": "lead"})
        assert r2.status_code == 200, r2.text

        r3 = requests.get(f"{API}/v1/automation/appointments",
                          headers={"X-Api-Key": secret})
        assert r3.status_code == 200

    def test_scope_guard_rejects_wrong_service_key(self, admin_session, admin_project):
        pid = admin_project["id"]
        # Create a payments-scoped key (no automation scope)
        r = admin_session.post(f"{API}/projects/{pid}/api-keys",
                               json={"name": "TEST pay key", "service": "payments"})
        assert r.status_code == 200
        secret = r.json()["secret_key"]

        r2 = requests.get(f"{API}/v1/automation/contacts", headers={"X-Api-Key": secret})
        assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"


# --------- No test/sandbox mode ---------
class TestNoSandbox:
    def test_only_live_projects(self, admin_session):
        r = admin_session.get(f"{API}/projects")
        assert r.status_code == 200
        for p in r.json():
            assert p["mode"] == "live", f"non-live project found: {p}"
