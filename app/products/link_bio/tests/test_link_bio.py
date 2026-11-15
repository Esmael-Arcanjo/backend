import base64

from tests.fixtures import new_session, subscribe

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


async def _bio():
    s = await new_session("Maria Bio")
    await subscribe(s, product_key="link_bio", segment="saude")
    return s


async def test_provisioned_page_and_segment_theme():
    s = await _bio()
    page = (await s.get("/api/v1/link_bio/page")).json()
    assert page["profile_type"] == "company" and page["segment"] == "saude"
    assert (await s.get("/api/v1/link_bio/theme")).json()["preset"] == "papel"
    assert (await s.get("/api/v1/crm/overview")).status_code == 403


async def test_profile_socials_and_xss_protection():
    s = await _bio()
    page = (await s.get("/api/v1/link_bio/page")).json()
    body = {"profile_type": "person", "display_name": "Dra. Maria", "title": "Dermatologista",
            "description": "Cuidando da sua pele", "location": "São Paulo, SP",
            "socials": [{"network": "instagram", "value": "instagram.com/maria"},
                        {"network": "whatsapp", "value": "+55 11 99999-0000"}], "version": page["version"]}
    r = await s.put("/api/v1/link_bio/page", body)
    assert r.status_code == 200, r.text
    assert r.json()["socials"][1]["url"] == "https://wa.me/5511999990000"
    bad = await s.post("/api/v1/link_bio/links", {"title": "x", "url": "javascript:alert(1)"})
    assert bad.status_code == 422


async def test_links_public_page_and_analytics():
    s = await _bio()
    link = (await s.post("/api/v1/link_bio/links", {"title": "Agende", "url": "https://agenda.example.com"})).json()
    handle = (await s.put("/api/v1/link_bio/page/handle", {"handle": f"maria{link['id'][-6:]}"})).json()["handle"]
    pub = await s.http.get(f"/api/v1/public/bio/{handle}")
    assert pub.status_code == 200 and any(lk["id"] == link["id"] for lk in pub.json()["links"])
    assert (await s.http.post(f"/api/v1/public/bio/{handle}/click", json={"link_id": link["id"]})).status_code == 200
    stats = (await s.get("/api/v1/link_bio/analytics", params={"days": 7})).json()
    assert stats["views"] >= 1 and stats["clicks"] >= 1
    await s.put("/api/v1/link_bio/page/publish", {"published": False})
    assert (await s.http.get(f"/api/v1/public/bio/{handle}")).status_code == 404


async def test_handle_unique_and_avatar_validation():
    a, b = await _bio(), await _bio()
    h = (await a.get("/api/v1/link_bio/page")).json()["handle"]
    assert (await b.put("/api/v1/link_bio/page/handle", {"handle": h})).status_code == 409
    assert (await a.put("/api/v1/link_bio/page/avatar", {"data_url": PNG})).status_code == 200
    fake = "data:image/png;base64," + base64.b64encode(b"<svg onload=alert(1)>").decode()
    assert (await a.put("/api/v1/link_bio/page/avatar", {"data_url": fake})).status_code == 422


async def test_cross_tenant_link_access_denied():
    a, b = await _bio(), await _bio()
    link = (await a.post("/api/v1/link_bio/links", {"title": "Meu", "url": "https://a.example.com"})).json()
    assert (await b.put(f"/api/v1/link_bio/links/{link['id']}", {"title": "hack", "url": "https://x.com"})).status_code == 404
    assert (await b.delete(f"/api/v1/link_bio/links/{link['id']}")).status_code == 404
