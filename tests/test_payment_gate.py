"""Payment gate tests: subscription services (email/automation/linkbio) require
Stripe payment before /login returns 200; usage services (payments/marketplace)
allow immediate login.
"""
import os
import sys
import uuid
import asyncio
import requests
import pytest

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://biolinks-pro-3.preview.emergentagent.com",
).rstrip("/")
ORIGIN = BASE_URL
ADMIN_EMAIL = "suportwibaza@hotmail.com"
ADMIN_PASSWORD = "LeamseAdmin2026!"

# Ensure we can import the backend package for direct service calls
sys.path.insert(0, "/app/backend")


def _register(service: str, country="BR", currency="BRL"):
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    password = "TestPass123!"
    payload = {
        "email": email, "password": password, "name": "Test User",
        "company": "TestCo", "country": country, "currency": currency,
        "service": service,
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload,
                      headers={"Origin": ORIGIN}, timeout=20)
    assert r.status_code == 200, f"register({service}) failed: {r.status_code} {r.text}"
    body = r.json()
    assert "access_token" in body
    assert body.get("email") == email
    return email, password, body["access_token"], body.get("organization_id")


def _login(email, password):
    return requests.post(f"{BASE_URL}/api/auth/login",
                         json={"email": email, "password": password},
                         headers={"Origin": ORIGIN}, timeout=15)


def _me(token):
    return requests.get(f"{BASE_URL}/api/auth/me",
                        headers={"Authorization": f"Bearer {token}",
                                 "Origin": ORIGIN}, timeout=15)


# ---------- Subscription services: MUST 402 until subscribe ----------
@pytest.mark.parametrize("service", ["email", "automation", "linkbio"])
def test_subscription_service_blocks_login_until_paid(service):
    email, password, token, org_id = _register(service)

    # /me right after register: payment_required = True
    r_me = _me(token)
    assert r_me.status_code == 200, r_me.text
    assert r_me.json().get("payment_required") is True, r_me.json()

    # /login must return 402
    r_login = _login(email, password)
    assert r_login.status_code == 402, \
        f"expected 402 for {service} before payment, got {r_login.status_code} {r_login.text}"

    # /billing/checkout returns a Stripe URL
    r_ck = requests.post(
        f"{BASE_URL}/api/billing/checkout",
        json={"service": service, "interval": "monthly", "trial": False, "origin_url": ORIGIN},
        headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN}, timeout=25,
    )
    assert r_ck.status_code == 200, f"checkout failed: {r_ck.status_code} {r_ck.text}"
    ck_data = r_ck.json()
    url = ck_data.get("checkout_url") or ck_data.get("url")
    assert url and "stripe.com" in url, f"no stripe url: {ck_data}"

    # Simulate successful subscribe via direct service call to flip payment_pending -> False
    from app.modules.subscriptions.service import SubscriptionService
    asyncio.get_event_loop().run_until_complete(
        SubscriptionService().subscribe(org_id, service, "monthly", "BRL")
    )

    # Now /login must return 200
    r_login2 = _login(email, password)
    assert r_login2.status_code == 200, \
        f"expected 200 after subscribe for {service}, got {r_login2.status_code} {r_login2.text}"
    body2 = r_login2.json()
    assert "access_token" in body2
    assert body2.get("payment_required") is False

    # /me should now show payment_required False
    r_me2 = _me(body2["access_token"])
    assert r_me2.status_code == 200
    assert r_me2.json().get("payment_required") is False


# ---------- Usage services: login works immediately ----------
@pytest.mark.parametrize("service", ["payments", "marketplace"])
def test_usage_service_login_immediate(service):
    email, password, token, org_id = _register(service)

    r_me = _me(token)
    assert r_me.status_code == 200
    assert r_me.json().get("payment_required") is False, r_me.json()

    r_login = _login(email, password)
    assert r_login.status_code == 200, \
        f"usage service {service} should log in immediately: {r_login.status_code} {r_login.text}"
    assert r_login.json().get("payment_required") is False


# ---------- Admin login unaffected ----------
def test_admin_login_unaffected():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("role") == "admin"
    assert body.get("payment_required") is False


# ---------- CORS still works on register ----------
def test_register_cors_headers_same_origin():
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "TestPass123!", "name": "Test",
              "company": "TestCo", "country": "BR", "currency": "BRL", "service": "payments"},
        headers={"Origin": ORIGIN}, timeout=20,
    )
    assert r.status_code == 200, r.text
    # Same-origin means CORS is browser-skipped, but header (if present) must be sane
    acao = r.headers.get("access-control-allow-origin")
    if acao:
        assert acao != "*"
