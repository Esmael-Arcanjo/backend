import pyotp

from app.core.security.passwords import hash_password, verify_password
from app.database.mongo import db
from tests.fixtures import PASSWORD, new_session


async def test_argon2id_hash():
    h = hash_password("abc12345678")
    assert h.startswith("$argon2id$")
    assert verify_password("abc12345678", h) and not verify_password("x", h)


async def test_register_rejects_weak_password():
    s = await new_session()
    r = await s.post("/api/v1/auth/register", {"name": "X Y", "email": "weak@example.com", "password": "123"})
    assert r.status_code == 422


async def test_csrf_required_for_mutations():
    s = await new_session()
    r = await s.http.patch("/api/v1/users/me", json={"name": "Sem CSRF"})
    assert r.status_code == 403


async def test_nosql_injection_rejected():
    s = await new_session()
    r = await s.http.post("/api/v1/auth/login", json={"email": {"$ne": ""}, "password": "x"},
                          headers={"X-CSRF-Token": s.http.cookies.get("csrf_token")})
    assert r.status_code == 422


async def test_login_logout_and_revocation():
    s = await new_session()
    assert (await s.get("/api/v1/auth/me")).status_code == 200
    assert (await s.post("/api/v1/auth/logout")).status_code == 200
    assert (await s.get("/api/v1/auth/me")).status_code == 401


async def test_lockout_after_failed_logins():
    s = await new_session()
    for _ in range(5):
        await s.post("/api/v1/auth/login", {"email": s.email, "password": "errada12345"})
    r = await s.post("/api/v1/auth/login", {"email": s.email, "password": PASSWORD})
    assert r.status_code == 423


async def test_refresh_rotation_and_reuse_detection():
    s = await new_session()
    old = s.http.cookies.get("refresh_token", path="/api/v1/auth")
    assert (await s.post("/api/v1/auth/refresh")).status_code == 200
    s.http.cookies.set("refresh_token", old, domain="test.local", path="/api/v1/auth")
    r = await s.http.post("https://test/api/v1/auth/refresh", headers={"X-CSRF-Token": s.http.cookies.get("csrf_token")},
                          cookies={"refresh_token": old})
    assert r.status_code == 401


async def test_mfa_flow():
    s = await new_session()
    setup = (await s.post("/api/v1/users/me/mfa/setup")).json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert (await s.post("/api/v1/users/me/mfa/enable", {"code": code})).status_code == 200
    user = await db.users.find_one({"email": s.email})
    assert user["mfa_enabled"] and setup["secret"] not in user["mfa_secret"]
    r = await s.post("/api/v1/auth/login", {"email": s.email, "password": PASSWORD})
    assert r.json()["mfa_required"] is True
    r2 = await s.post("/api/v1/auth/login/mfa", {"mfa_token": r.json()["mfa_token"], "code": "000000"})
    assert r2.status_code == 401


async def test_password_reset_flow():
    s = await new_session()
    await s.post("/api/v1/auth/forgot-password", {"email": s.email})
    from tests.fixtures import SENT_EMAILS
    mail = await db.email_outbox.find_one({"to": s.email, "kind": "reset_password"})
    assert "[REDACTED]" in mail["body"]
    html = next(m["html"] for m in reversed(SENT_EMAILS) if m["to"] == s.email and "senha" in m["subject"])
    token = html.split("token=")[1].split('"')[0]
    assert (await s.post("/api/v1/auth/reset-password", {"token": token, "password": "NovaSenha12345"})).status_code == 200
    assert (await s.get("/api/v1/auth/me")).status_code == 401
    assert (await s.post("/api/v1/auth/reset-password", {"token": token, "password": "NovaSenha12345"})).status_code == 400
