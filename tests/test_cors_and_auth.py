"""Tests for LEAMSE API on same-origin URL (biolinks-pro-3.preview.emergentagent.com).

Iteration 2: frontend .env aligned to same host as backend, so requests are same-origin.
We now hit the SAME URL that the browser hits and validate all critical flows end-to-end.
"""
import os
import uuid
import requests
import pytest

# Same-origin URL that the browser now uses
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://biolinks-pro-3.preview.emergentagent.com",
).rstrip("/")
ORIGIN = "https://biolinks-pro-3.preview.emergentagent.com"
ADMIN_EMAIL = "suportwibaza@hotmail.com"
ADMIN_PASSWORD = "LeamseAdmin2026!"


# ---------- Health ----------
def test_health():
    r = requests.get(f"{BASE_URL}/api/health", headers={"Origin": ORIGIN}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "healthy", data


# ---------- CORS preflight (same-origin — edge may still respond, but not required) ----------
@pytest.mark.parametrize("path,method", [
    ("/api/auth/register", "POST"),
    ("/api/auth/login", "POST"),
    ("/api/auth/me", "GET"),
    ("/api/public/pricing", "GET"),
    ("/api/public/geo", "GET"),
])
def test_cors_preflight_same_origin(path, method):
    r = requests.options(
        f"{BASE_URL}{path}",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
        timeout=15,
    )
    assert r.status_code in (200, 204), f"{path} preflight status {r.status_code}"
    acao = r.headers.get("access-control-allow-origin")
    # For same-origin, browser skips CORS entirely. But if the edge/backend returns ACAO,
    # it must NOT be wildcard when credentials=include, and should match Origin.
    if acao:
        assert acao != "*", f"{path} ACAO is wildcard with credentials"
        assert acao == ORIGIN, f"{path} ACAO={acao!r} != Origin {ORIGIN!r}"


# ---------- Public endpoints ----------
def test_public_pricing():
    r = requests.get(f"{BASE_URL}/api/public/pricing", headers={"Origin": ORIGIN}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("payments", "marketplace", "email", "automation", "linkbio"):
        assert k in data, f"pricing missing key {k}: {list(data.keys())}"


def test_public_geo():
    r = requests.get(f"{BASE_URL}/api/public/geo", headers={"Origin": ORIGIN}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "country" in data and "currency" in data, data


def test_public_coupon_welcome20():
    r = requests.get(f"{BASE_URL}/api/public/coupons/WELCOME20", headers={"Origin": ORIGIN}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    # Expect coupon info fields
    assert data, f"empty coupon body: {data}"


# ---------- Auth flows ----------
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Origin": ORIGIN},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    assert "access_token" in body, body
    s.headers.update({"Authorization": f"Bearer {body['access_token']}", "Origin": ORIGIN})
    return s, body


def test_admin_login_flat_shape(admin_session):
    _, body = admin_session
    # Login shape is FLAT: access_token + user fields siblings
    assert body["email"] == ADMIN_EMAIL
    assert body.get("role") == "admin"
    assert isinstance(body.get("access_token"), str) and len(body["access_token"]) > 10


def test_admin_me(admin_session):
    s, _ = admin_session
    r = s.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["email"] == ADMIN_EMAIL


def test_register_email_service_br_and_me():
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    payload = {
        "email": email,
        "password": "TestPass123!",
        "name": "Test User",
        "company": "TestCo",
        "country": "BR",
        "currency": "BRL",
        "service": "email",
    }
    r = requests.post(
        f"{BASE_URL}/api/auth/register", json=payload,
        headers={"Origin": ORIGIN}, timeout=20,
    )
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    body = r.json()
    assert "access_token" in body, body
    assert body.get("email") == email
    token = body["access_token"]

    r2 = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["email"] == email
    return token, email


# ---------- Billing ----------
def test_billing_checkout_email_monthly_trial_fresh_user():
    # Create fresh user
    email = f"test_{uuid.uuid4().hex[:10]}@example.com"
    payload = {
        "email": email, "password": "TestPass123!", "name": "Checkout User",
        "company": "TestCo", "country": "BR", "currency": "BRL", "service": "email",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload,
                      headers={"Origin": ORIGIN}, timeout=20)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r2 = requests.post(
        f"{BASE_URL}/api/billing/checkout",
        json={"service": "email", "interval": "monthly", "trial": True, "origin_url": ORIGIN},
        headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN},
        timeout=25,
    )
    assert r2.status_code == 200, f"checkout failed: {r2.status_code} {r2.text}"
    data = r2.json()
    url = data.get("checkout_url") or data.get("url")
    assert url and "stripe.com" in url, f"no stripe url in {data}"


# ---------- Admin endpoints ----------
def test_admin_stats(admin_session):
    s, _ = admin_session
    r = s.get(f"{BASE_URL}/api/admin/stats", timeout=15)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), dict)


def test_admin_users(admin_session):
    s, _ = admin_session
    r = s.get(f"{BASE_URL}/api/admin/users", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, (list, dict))


def test_admin_metrics_timeseries_12_months(admin_session):
    s, _ = admin_session
    r = s.get(f"{BASE_URL}/api/admin/metrics/timeseries", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    series = data.get("series") if isinstance(data, dict) else data
    assert isinstance(series, list), f"series not list: {data}"
    assert len(series) == 12, f"expected 12 months, got {len(series)}: {series}"
