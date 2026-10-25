"""Focused regression tests for LEAMSE monorepo (SaaS + Marketplace).

Covers only flows requested by main agent:
  - /api/health and /api/ returns operational
  - SaaS admin login (admin@leamse.com / leamse123)
  - SaaS register new user flow
  - Marketplace demo products (expects 30 seeded products with images)
  - Marketplace admin login (admin@wibaza.com / WibazaAdmin2026!)
  - Marketplace demo seller login (demo.seller@wibaza.com / DemoSeller2026!)
"""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SAAS_ADMIN = ("admin@leamse.com", "leamse123")
MP_ADMIN = ("admin@wibaza.com", "WibazaAdmin2026!")
MP_SELLER = ("demo.seller@wibaza.com", "DemoSeller2026!")


# ---- Meta ----
def test_api_root_operational():
    r = requests.get(f"{API}/", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "operational"
    assert body.get("service") == "LEAMSE API"


def test_api_health():
    r = requests.get(f"{API}/health", timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "healthy"


# ---- SaaS Auth ----
def test_saas_admin_login_and_me():
    r = requests.post(f"{API}/auth/login",
                      json={"email": SAAS_ADMIN[0], "password": SAAS_ADMIN[1]},
                      timeout=20)
    assert r.status_code == 200, f"saas admin login failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("access_token")
    assert token and isinstance(token, str) and len(token) > 10
    assert body.get("email") == SAAS_ADMIN[0]

    me = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=15)
    assert me.status_code == 200, me.text
    assert me.json().get("email") == SAAS_ADMIN[0]


def test_saas_register_new_user():
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "name": "Test User",
        "email": email,
        "password": "TestPass123!",
        "company": "TestCo",
        "country": "BR",
        "currency": "BRL",
    }
    # Try both single `service` and list `services` for compatibility
    payload_s = {**payload, "service": "payments"}
    r = requests.post(f"{API}/auth/register", json=payload_s, timeout=20)
    if r.status_code != 200:
        # Fallback shape
        r = requests.post(f"{API}/auth/register",
                          json={**payload, "services": ["payments"]},
                          timeout=20)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("email") == email
    assert body.get("access_token")


# ---- Marketplace Public ----
def test_mp_shop_products_seeded():
    r = requests.get(f"{API}/shop/products", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    items = data if isinstance(data, list) else data.get("data") or data.get("items") or []
    assert isinstance(items, list)
    # Seed should produce exactly 30 demo products
    assert len(items) >= 30, f"expected >=30 seeded products, got {len(items)}"
    # Check images present
    with_images = [p for p in items if p.get("image") or p.get("images") or p.get("image_url")]
    assert len(with_images) >= 20, f"too few products with images: {len(with_images)}/{len(items)}"


def test_mp_shop_categories():
    r = requests.get(f"{API}/shop/categories", timeout=15)
    assert r.status_code == 200, r.text


def test_mp_product_detail():
    r = requests.get(f"{API}/shop/products", timeout=20)
    items = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
    assert items
    pid = items[0].get("id") or items[0].get("_id")
    assert pid
    rd = requests.get(f"{API}/shop/products/{pid}", timeout=15)
    assert rd.status_code == 200, rd.text


# ---- Marketplace Auth ----
def test_mp_admin_login():
    r = requests.post(f"{API}/mp/auth/login",
                      json={"email": MP_ADMIN[0], "password": MP_ADMIN[1]},
                      timeout=20)
    assert r.status_code == 200, f"mp admin login failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("access_token") or body.get("token")
    role = body.get("user_type") or body.get("role") or (body.get("user") or {}).get("role")
    assert role in ("admin", "mp_admin", "superadmin"), f"unexpected role: {role} body={body}"


def test_mp_demo_seller_login():
    r = requests.post(f"{API}/mp/auth/login",
                      json={"email": MP_SELLER[0], "password": MP_SELLER[1]},
                      timeout=20)
    assert r.status_code == 200, f"mp seller login failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("access_token") or body.get("token")
    role = body.get("user_type") or body.get("role") or (body.get("user") or {}).get("role")
    assert role in ("seller", "demo_seller"), f"unexpected role: {role} body={body}"


def test_mp_buyer_register_and_login():
    email = f"buyer_{uuid.uuid4().hex[:8]}@test.com"
    pw = "BuyerPass123!"
    r = requests.post(
        f"{API}/mp/auth/register",
        json={"email": email, "password": pw, "name": "Buyer Test", "role": "buyer"},
        timeout=20,
    )
    assert r.status_code == 200, f"buyer register failed: {r.status_code} {r.text}"
    rl = requests.post(f"{API}/mp/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    assert rl.status_code == 200, rl.text


def test_mp_seller_register():
    email = f"seller_{uuid.uuid4().hex[:8]}@test.com"
    pw = "SellerPass123!"
    r = requests.post(
        f"{API}/mp/auth/register",
        json={
            "email": email, "password": pw, "name": "Seller Test",
            "role": "seller", "store_name": "TEST Store",
        },
        timeout=20,
    )
    assert r.status_code == 200, f"seller register failed: {r.status_code} {r.text}"
