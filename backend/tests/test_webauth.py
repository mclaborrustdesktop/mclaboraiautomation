"""Web sign-in is independent of the Access password column (tblOfficeStaff.OfficeStaffPassword)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from app import schemas, webauth
from app.config import settings

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _new_user(client, h, initials, password="first-pass-1"):
    r = client.post("/api/users", headers=h, json={"OfficeStaffFirstName": "Web", "OfficeStaffLastName": f"Auth{initials}", "Initials": initials,
                                                   "password": password, "feature_ids": []})
    assert r.status_code == 201, r.text
    return r.json()["OfficeStaffID"]


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_login_does_not_use_the_access_password_column(client, admin_headers, engine):
    uid = _new_user(client, admin_headers, "WA1")
    # whatever is stored in the legacy column is irrelevant to web sign-in
    with engine.begin() as conn:
        legacy = conn.execute(text("SELECT OfficeStaffPassword FROM tblOfficeStaff WHERE OfficeStaffID = :i"), {"i": uid}).scalar_one()
        assert "first-pass-1" not in legacy and not legacy.startswith("pbkdf2$")
        conn.execute(text("UPDATE tblOfficeStaff SET OfficeStaffPassword = 'AccessPlainText' WHERE OfficeStaffID = :i"), {"i": uid})
    assert _login(client, "WA1", "AccessPlainText").status_code == 401
    assert _login(client, "wa1", "first-pass-1").status_code == 200
    assert webauth.has_password(uid)


def test_no_web_password_means_no_sign_in(client, admin_headers, engine):
    uid = _new_user(client, admin_headers, "WA2")
    with webauth._session() as s:
        s.delete(s.get(webauth.WebCredential, uid))
        s.commit()
    r = _login(client, "WA2", "first-pass-1")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password"
    assert _login(client, "nobody-here", "x").json()["detail"] == "Invalid username or password"  # same answer: no user enumeration


def test_change_own_password(client, admin_headers):
    _new_user(client, admin_headers, "WA3")
    tok = _login(client, "WA3", "first-pass-1").json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": "second-pass-2"}).status_code == 400
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "first-pass-1", "new_password": "abc"}).status_code == 422
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "first-pass-1", "new_password": "wa3"}).status_code == 422
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "first-pass-1", "new_password": "first-pass-1"}).status_code == 422
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "first-pass-1", "new_password": "second-pass-2"}).status_code == 204
    assert _login(client, "WA3", "first-pass-1").status_code == 401
    assert _login(client, "WA3", "second-pass-2").status_code == 200
    assert client.post("/api/auth/change-password", json={"current_password": "a", "new_password": "bbbbbbbb"}).status_code == 401


def test_admin_reset_requires_change_at_next_sign_in(client, admin_headers):
    uid = _new_user(client, admin_headers, "WA4")
    assert _login(client, "WA4", "first-pass-1").json()["must_change_password"] is False
    assert client.post(f"/api/users/{uid}/password", headers=admin_headers, json={"password": "temp-pass-9"}).status_code == 204
    r = _login(client, "WA4", "temp-pass-9")
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post(f"/api/users/{uid}/password", headers=h, json={"password": "hacked-pass"}).status_code == 403  # not an admin
    assert client.post("/api/auth/change-password", headers=h, json={"current_password": "temp-pass-9", "new_password": "my-own-pass-3"}).status_code == 204
    assert _login(client, "WA4", "my-own-pass-3").json()["must_change_password"] is False
    # editing a user with a new password also goes to the web sign-in store
    assert client.put(f"/api/users/{uid}", headers=admin_headers, json={"password": "edited-pass-4"}).status_code == 200
    assert _login(client, "WA4", "edited-pass-4").status_code == 200


def test_lockout_after_repeated_failures(client, admin_headers):
    uid = _new_user(client, admin_headers, "WA5")
    for _ in range(webauth.MAX_FAILED_ATTEMPTS):
        assert _login(client, "WA5", "wrong-password").status_code == 401
    r = _login(client, "WA5", "first-pass-1")  # correct password, but locked
    assert r.status_code == 429 and "Too many failed attempts" in r.json()["detail"]
    with webauth._session() as s:  # lock expires
        s.get(webauth.WebCredential, uid).locked_until = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    assert _login(client, "WA5", "first-pass-1").status_code == 200


def test_inactive_user_cannot_sign_in(client, admin_headers):
    uid = _new_user(client, admin_headers, "WA6")
    assert client.delete(f"/api/users/{uid}", headers=admin_headers).status_code == 204
    assert _login(client, "WA6", "first-pass-1").status_code == 403


def test_password_never_returned_by_the_api(client, admin_headers):
    body = client.get("/api/users", headers=admin_headers, params={"page_size": 200}).text + client.get("/api/auth/me", headers=admin_headers).text
    assert "pbkdf2$" not in body and "OfficeStaffPassword" not in body and "password_hash" not in body


def test_production_password_policy(monkeypatch):
    monkeypatch.setattr(settings, "data_source", "production")
    assert webauth.min_password_length() == 12
    assert webauth.password_problem("short-pass") is not None
    assert webauth.password_problem(settings.demo_password + "x" * 12) is None
    assert webauth.password_problem("a-long-enough-password") is None


def test_demo_lookups_expose_no_restricted_fields(client, admin_headers):
    assert client.get("/api/lookups", headers=admin_headers).json()["restricted_fields"] == []


def test_frontend_form_fields_are_accepted_by_the_api():
    """Every field the Add/Edit screens send must exist in the API schemas (updates reject unknown fields)."""
    src = (FRONTEND / "lib" / "forms.ts").read_text(encoding="utf-8")
    blocks = {name: body for name, body in re.findall(r"export const (\w+_SECTIONS)[^=]*=\s*\[(.*?)\n\];", src, re.S)}
    assert {"EMPLOYEE_SECTIONS", "CUSTOMER_SECTIONS"} <= set(blocks), list(blocks)
    pairs = {"EMPLOYEE_SECTIONS": schemas.EmployeeUpdate, "CUSTOMER_SECTIONS": schemas.CustomerUpdate, "PROJECT_SECTIONS": schemas.ProjectUpdate}
    checked = 0
    for name, schema in pairs.items():
        if name not in blocks:
            continue
        fields = set(re.findall(r'name:\s*"(\w+)"', blocks[name]))
        assert fields, name
        unknown = fields - set(schema.model_fields)
        assert not unknown, f"{name}: the form sends fields the API does not accept: {sorted(unknown)}"
        checked += len(fields)
    assert checked > 60
