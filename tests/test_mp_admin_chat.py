"""Backend tests for Marketplace Admin + Chat features (iteration 4)."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend .env file
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@wibaza.com"
ADMIN_PASSWORD = "WibazaAdmin2026!"
BUYER_EMAIL = "chat.buyer@test.com"
BUYER_PASSWORD = "Test1234!"
SELLER_EMAIL = "chat.seller@test.com"
SELLER_PASSWORD = "Test1234!"
SAAS_ADMIN_EMAIL = "suportwibaza@hotmail.com"
SAAS_ADMIN_PASSWORD = "LeamseAdmin2026!"


def _login(path, email, password):
    r = requests.post(f"{API}{path}", json={"email": email, "password": password}, timeout=15)
    return r


@pytest.fixture(scope="module")
def admin_token():
    r = _login("/mp/auth/login", ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("user_type") == "admin", f"user_type not admin: {data}"
    return data["access_token"]


@pytest.fixture(scope="module")
def buyer_token():
    r = _login("/mp/auth/login", BUYER_EMAIL, BUYER_PASSWORD)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def buyer_info(buyer_token):
    r = requests.get(f"{API}/mp/auth/me", headers={"Authorization": f"Bearer {buyer_token}"})
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def seller_token():
    r = _login("/mp/auth/login", SELLER_EMAIL, SELLER_PASSWORD)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def seller_info(seller_token):
    r = requests.get(f"{API}/mp/auth/me", headers={"Authorization": f"Bearer {seller_token}"})
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def saas_admin_token():
    r = _login("/auth/login", SAAS_ADMIN_EMAIL, SAAS_ADMIN_PASSWORD)
    if r.status_code != 200:
        pytest.skip("SaaS admin login failed")
    return r.json().get("access_token") or r.json().get("token")


def H(t):
    return {"Authorization": f"Bearer {t}"}


# ---------------- MP Admin ----------------
class TestMPAdmin:
    def test_admin_login_returns_admin_type(self, admin_token):
        assert admin_token

    def test_admin_stats(self, admin_token):
        r = requests.get(f"{API}/mp/admin/stats", headers=H(admin_token))
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ["sellers", "buyers", "products_total", "orders_total", "revenue_cents"]:
            assert k in d, f"missing {k}: {d}"

    def test_admin_users_list(self, admin_token):
        r = requests.get(f"{API}/mp/admin/users", headers=H(admin_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_non_admin_forbidden(self, buyer_token):
        r = requests.get(f"{API}/mp/admin/users", headers=H(buyer_token))
        assert r.status_code == 403

    def test_saas_token_isolation(self, saas_admin_token):
        r = requests.get(f"{API}/mp/admin/stats", headers=H(saas_admin_token))
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_saas_token_cannot_access_chat(self, saas_admin_token):
        r = requests.get(f"{API}/mp/chat/threads", headers=H(saas_admin_token))
        assert r.status_code in (401, 403)


# ---------------- Ban/unban and product hide ----------------
class TestBanAndProductHide:
    def test_ban_and_unban_buyer(self, admin_token, buyer_info):
        buyer_id = buyer_info["id"]
        # Ban
        r = requests.post(
            f"{API}/mp/admin/users/{buyer_id}/ban",
            json={"banned": True, "reason": "test"},
            headers=H(admin_token),
        )
        assert r.status_code == 200, r.text
        # Buyer login should fail 403 Conta suspensa
        rb = _login("/mp/auth/login", BUYER_EMAIL, BUYER_PASSWORD)
        assert rb.status_code == 403, f"banned login: {rb.status_code} {rb.text}"
        assert "suspens" in rb.text.lower() or "suspend" in rb.text.lower()
        # Unban
        r = requests.post(
            f"{API}/mp/admin/users/{buyer_id}/ban",
            json={"banned": False},
            headers=H(admin_token),
        )
        assert r.status_code == 200
        rb = _login("/mp/auth/login", BUYER_EMAIL, BUYER_PASSWORD)
        assert rb.status_code == 200, f"unbanned login: {rb.status_code} {rb.text}"

    def test_hide_product_from_shop(self, admin_token, seller_token, seller_info):
        # Create a product as seller (if endpoint available)
        pname = f"TEST_prod_{uuid.uuid4().hex[:6]}"
        pr = requests.post(
            f"{API}/mp/seller/products",
            json={"name": pname, "description": "t", "price_cents": 1000, "currency": "BRL", "stock": 5},
            headers=H(seller_token),
        )
        if pr.status_code not in (200, 201):
            pytest.skip(f"seller product create not available: {pr.status_code} {pr.text[:200]}")
        prod = pr.json()
        pid = prod.get("id") or prod.get("_id")
        # Verify visible in shop
        rs = requests.get(f"{API}/shop/products", params={"search": pname})
        assert rs.status_code == 200
        assert any((p.get("id") or p.get("_id")) == pid for p in rs.json()), "product not in shop"
        # Hide via admin
        r = requests.patch(
            f"{API}/mp/admin/products/{pid}",
            json={"active": False},
            headers=H(admin_token),
        )
        assert r.status_code == 200
        assert r.json().get("active") is False
        # Verify no longer in shop
        rs = requests.get(f"{API}/shop/products", params={"search": pname})
        assert rs.status_code == 200
        assert not any((p.get("id") or p.get("_id")) == pid for p in rs.json()), "hidden product still in shop"
        # Cleanup
        requests.delete(f"{API}/mp/admin/products/{pid}", headers=H(admin_token))


# ---------------- Chat ----------------
class TestChat:
    def test_seller_cannot_start(self, seller_token, seller_info):
        r = requests.post(
            f"{API}/mp/chat/start",
            json={"seller_id": seller_info["id"]},
            headers=H(seller_token),
        )
        assert r.status_code == 403

    def test_buyer_start_nonexistent_seller(self, buyer_token):
        r = requests.post(
            f"{API}/mp/chat/start",
            json={"seller_id": "507f1f77bcf86cd799439011"},
            headers=H(buyer_token),
        )
        assert r.status_code == 404

    def test_start_dedup(self, buyer_token, seller_info):
        seller_id = seller_info["id"]
        r1 = requests.post(f"{API}/mp/chat/start", json={"seller_id": seller_id}, headers=H(buyer_token))
        assert r1.status_code == 200, r1.text
        tid1 = r1.json()["thread_id"]
        r2 = requests.post(f"{API}/mp/chat/start", json={"seller_id": seller_id}, headers=H(buyer_token))
        assert r2.status_code == 200
        tid2 = r2.json()["thread_id"]
        assert tid1 == tid2, f"expected dedup, got {tid1} vs {tid2}"

    def test_threads_list_both_sides(self, buyer_token, seller_token, seller_info):
        # ensure a thread exists
        requests.post(f"{API}/mp/chat/start", json={"seller_id": seller_info["id"]}, headers=H(buyer_token))
        rb = requests.get(f"{API}/mp/chat/threads", headers=H(buyer_token))
        assert rb.status_code == 200 and isinstance(rb.json(), list) and len(rb.json()) >= 1
        rs = requests.get(f"{API}/mp/chat/threads", headers=H(seller_token))
        assert rs.status_code == 200 and isinstance(rs.json(), list) and len(rs.json()) >= 1

    def test_send_and_read_messages_and_unread_reset(self, buyer_token, seller_token, seller_info):
        r = requests.post(f"{API}/mp/chat/start", json={"seller_id": seller_info["id"]}, headers=H(buyer_token))
        tid = r.json()["thread_id"]
        # Buyer sends
        r = requests.post(
            f"{API}/mp/chat/threads/{tid}/messages",
            json={"text": "olá vendedor TEST"},
            headers=H(buyer_token),
        )
        assert r.status_code == 200, r.text
        # Seller replies
        r = requests.post(
            f"{API}/mp/chat/threads/{tid}/messages",
            json={"text": "olá comprador TEST"},
            headers=H(seller_token),
        )
        assert r.status_code == 200
        # Buyer sees history (both) and unread resets
        r = requests.get(f"{API}/mp/chat/threads/{tid}/messages", headers=H(buyer_token))
        assert r.status_code == 200
        msgs = r.json()
        assert len(msgs) >= 2
        texts = [m["text"] for m in msgs]
        assert any("olá vendedor TEST" in t for t in texts)
        assert any("olá comprador TEST" in t for t in texts)
        # after= filter
        last_ts = msgs[-1]["created_at"]
        r = requests.get(f"{API}/mp/chat/threads/{tid}/messages", params={"after": last_ts}, headers=H(buyer_token))
        assert r.status_code == 200
        assert r.json() == [] or len(r.json()) == 0
        # unread reset check via threads
        rb = requests.get(f"{API}/mp/chat/threads", headers=H(buyer_token))
        for t in rb.json():
            if t["id"] == tid:
                assert t.get("unread", 0) == 0

    def test_unrelated_user_cannot_post(self, admin_token, buyer_token, seller_info):
        # admin isn't a participant
        r = requests.post(f"{API}/mp/chat/start", json={"seller_id": seller_info["id"]}, headers=H(buyer_token))
        tid = r.json()["thread_id"]
        r = requests.get(f"{API}/mp/chat/threads/{tid}/messages", headers=H(admin_token))
        assert r.status_code == 403
        r = requests.post(f"{API}/mp/chat/threads/{tid}/messages", json={"text": "x"}, headers=H(admin_token))
        assert r.status_code == 403
