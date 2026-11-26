"""Approved devices behind the site password: WebAuthn registration, pending/approve/revoke, bound sessions, bootstrap."""
import pytest

from app import devices, sitepass
from app.config import Settings, settings
from app.security import hash_password
from tests.fake_authenticator import FakeAuthenticator

SITE_PW = "Correct-Horse-Battery-2026"
RP, ORIGIN = "localhost", "http://localhost"
BOOT = "bootstrap-code-for-the-first-device-2026"


@pytest.fixture
def device_mode(monkeypatch):
    monkeypatch.setattr(settings, "access_mode", "passcode")
    monkeypatch.setattr(settings, "site_password_hash", hash_password(SITE_PW))
    monkeypatch.setattr(settings, "site_default_user", "ADMIN")
    monkeypatch.setattr(settings, "site_device_approval", True)
    monkeypatch.setattr(settings, "webauthn_rp_id", RP)
    monkeypatch.setattr(settings, "webauthn_origin", ORIGIN)
    monkeypatch.setattr(settings, "site_device_bootstrap_code", BOOT)
    sitepass.clear()
    devices.clear()
    yield
    sitepass.clear()
    devices.clear()


def _ticket(client, ip="203.0.113.7"):
    r = client.post("/api/auth/unlock", json={"password": SITE_PW}, headers={"X-Forwarded-For": ip})
    assert r.status_code == 200 and r.json()["stage"] == "device" and "access_token" not in r.json()
    return r.json()["ticket"]


def _register(client, auth, ip="203.0.113.7"):
    t = _ticket(client, ip)
    o = client.post("/api/auth/device/register/options", json={"ticket": t}, headers={"X-Forwarded-For": ip}).json()
    cred = auth.create(o["options"])
    r = client.post("/api/auth/device/register/verify", json={"ticket": t, "challenge": o["challenge"], "credential": cred}, headers={"X-Forwarded-For": ip})
    assert r.status_code == 200 and r.json()["stage"] == "pending"
    return r.json()


def _assert(client, auth, ip="203.0.113.7", bootstrap_code=None, tamper=False):
    t = _ticket(client, ip)
    o = client.post("/api/auth/device/options", json={"ticket": t}, headers={"X-Forwarded-For": ip}).json()
    cred = auth.get(o["options"], tamper=tamper)
    body = {"ticket": t, "challenge": o["challenge"], "credential": cred}
    if bootstrap_code:
        body["bootstrap_code"] = bootstrap_code
    return client.post("/api/auth/device/verify", json=body, headers={"X-Forwarded-For": ip})


def test_operator_command_line_approves_and_revokes_with_an_audit_record(client, device_mode):
    """Recovery path: no website session exists (no approved device can sign in), the operator runs the CLI inside the backend."""
    from app import webauth

    auth = FakeAuthenticator(RP, ORIGIN)
    code = _register(client, auth)["pairing_code"]
    assert webauth.main(["x", "devices", "approve", "ZZZZZZ", "ADMIN", "ray"]) == 1          # unknown code: nothing changes
    assert webauth.main(["x", "devices", "approve", code, "NOBODY", "ray"]) == 1             # unknown staff: nothing changes
    assert _assert(client, auth).status_code == 403                                           # still pending
    assert webauth.main(["x", "devices", "approve", code.lower(), "ADMIN", "ray", "owner PC"]) == 0
    assert webauth.main(["x", "devices", "list"]) == 0
    r = _assert(client, auth)
    assert r.status_code == 200 and r.json()["stage"] == "session"
    tok = {"Authorization": "Bearer " + r.json()["access_token"]}
    assert client.get("/api/employees", headers=tok).status_code == 200
    dev = next(d for d in devices.list_devices() if d["label"] == "owner PC")
    assert dev["approved_by"] == "cli:ray"
    assert webauth.main(["x", "devices", "revoke", str(dev["id"]), "ray"]) == 0
    assert client.get("/api/employees", headers=tok).status_code == 401                       # session died with the device
    notes = [a["note"] for a in sitepass.recent()]
    assert "device-approved-by:cli:ray" in notes and "device-revoked-by:cli:ray" in notes


def test_password_alone_opens_nothing_and_a_new_device_waits_for_approval(client, device_mode):
    auth = FakeAuthenticator(RP, ORIGIN)
    t = _ticket(client)
    assert client.get("/api/employees", headers={"Authorization": "Bearer " + t}).status_code == 401   # a ticket is not a session
    unknown = _assert(client, auth)
    assert unknown.status_code == 403 and "not registered" in unknown.json()["detail"]
    reg = _register(client, auth)
    assert len(reg["pairing_code"]) == 6
    pending = _assert(client, auth)
    assert pending.status_code == 403 and pending.json()["detail"]["code"] == "pending" and pending.json()["detail"]["pairing_code"] == reg["pairing_code"]
    assert client.get("/api/auth/device/status", params={"code": reg["pairing_code"]}).json()["status"] == "pending"


def test_bootstrap_code_approves_only_the_first_device(client, device_mode):
    first, second = FakeAuthenticator(RP, ORIGIN), FakeAuthenticator(RP, ORIGIN)
    _register(client, first)
    ok = _assert(client, first, bootstrap_code=BOOT)
    assert ok.status_code == 200 and ok.json()["stage"] == "session" and ok.json()["user"]["Initials"] == "ADMIN"
    tok = {"Authorization": "Bearer " + ok.json()["access_token"]}
    assert client.get("/api/employees", headers=tok).status_code == 200
    _register(client, second, ip="203.0.113.8")
    again = _assert(client, second, ip="203.0.113.8", bootstrap_code=BOOT)                 # an approved device exists now: the code is dead
    assert again.status_code == 403 and again.json()["detail"]["code"] == "pending"
    assert _assert(client, second, ip="203.0.113.8", bootstrap_code="wrong-code-wrong-code").status_code == 403


def test_administrator_approves_names_and_revokes_devices_and_sessions_follow(client, device_mode):
    admin_dev, staff_dev = FakeAuthenticator(RP, ORIGIN), FakeAuthenticator(RP, ORIGIN)
    _register(client, admin_dev)
    admin_tok = {"Authorization": "Bearer " + _assert(client, admin_dev, bootstrap_code=BOOT).json()["access_token"]}
    reg = _register(client, staff_dev, ip="203.0.113.9")
    listing = client.get("/api/auth/devices", headers=admin_tok).json()
    pending = [d for d in listing["devices"] if d["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["pairing_code"] == reg["pairing_code"] and pending[0]["created_ip"] == "203.0.113.9"
    users = client.get("/api/users", headers=admin_tok, params={"active": "true", "page_size": 200}).json()["items"]
    other = next(u for u in users if u["Initials"] != "ADMIN")
    assert client.post(f"/api/auth/devices/{pending[0]['id']}/approve", headers=admin_tok, json={"staff": other["Initials"], "label": f"{other['OfficeStaffFullName']} - laptop"}).status_code == 200
    assert client.get("/api/auth/device/status", params={"code": reg["pairing_code"]}).json()["status"] == "approved"
    sess = _assert(client, staff_dev, ip="203.0.113.9")
    assert sess.status_code == 200 and sess.json()["user"]["Initials"] == other["Initials"]
    staff_tok = {"Authorization": "Bearer " + sess.json()["access_token"]}
    assert client.get("/api/employees", headers=staff_tok).status_code == 200
    assert client.get("/api/auth/devices", headers=staff_tok).status_code == 403                 # not an administrator
    # the audit trail names the device
    log = client.get("/api/auth/unlock-log", headers=admin_tok).json()["attempts"]
    assert any(a["note"].startswith("device-approved-by:") for a in log) and any(a["identity"] and a["identity"].startswith("device:") and a["note"] == "ok" for a in log)
    # revoke: the open session dies at once, and the device cannot sign in again
    assert client.post(f"/api/auth/devices/{pending[0]['id']}/revoke", headers=admin_tok).status_code == 200
    assert client.get("/api/employees", headers=staff_tok).status_code == 401
    assert _assert(client, staff_dev, ip="203.0.113.9").json()["detail"]["code"] == "revoked"
    assert client.post(f"/api/auth/devices/{pending[0]['id']}/approve", headers=admin_tok, json={"staff": other["Initials"]}).status_code == 409


def test_forged_or_replayed_signatures_and_copied_tickets_are_refused(client, device_mode):
    auth = FakeAuthenticator(RP, ORIGIN)
    _register(client, auth)
    _assert(client, auth, bootstrap_code=BOOT)
    bad = _assert(client, auth, tamper=True)
    assert bad.status_code == 401 and "Device check failed" in bad.json()["detail"]
    # a challenge cannot be reused with a fresh signature from another device, and a ticket is bound to the address
    other = FakeAuthenticator(RP, ORIGIN)
    t = _ticket(client)
    o = client.post("/api/auth/device/options", json={"ticket": t}, headers={"X-Forwarded-For": "203.0.113.7"}).json()
    r = client.post("/api/auth/device/verify", json={"ticket": t, "challenge": o["challenge"], "credential": other.get(o["options"])}, headers={"X-Forwarded-For": "203.0.113.7"})
    assert r.status_code == 403                                                                   # unknown credential: no session
    stolen = client.post("/api/auth/device/options", json={"ticket": t}, headers={"X-Forwarded-For": "198.51.100.200"})
    assert stolen.status_code == 401                                                              # ticket used from another address
    wrong_challenge = client.post("/api/auth/device/verify", json={"ticket": t, "challenge": "not-a-token", "credential": auth.get(o["options"])}, headers={"X-Forwarded-For": "203.0.113.7"})
    assert wrong_challenge.status_code == 401


def test_settings_rules_for_device_approval():
    base = dict(data_source="staging", jwt_secret="x" * 40, access_mode="passcode", web_admins="ARI", site_password_hash=hash_password("Something-Long-Enough-1"), site_default_user="ARI")
    assert any("WEBAUTHN_RP_ID" in p for p in Settings(**base, site_device_approval=True).environment_problems())
    assert any("WEBAUTHN_RP_ID" in p for p in Settings(**base, site_device_approval=True, webauthn_rp_id="a.example", webauthn_origin="https://b.example").environment_problems())
    assert not any("WEBAUTHN" in p for p in Settings(**base, site_device_approval=True, webauthn_rp_id="a.example", webauthn_origin="https://a.example").environment_problems())
    assert any("SITE_DEVICE_BOOTSTRAP_CODE" in p for p in Settings(**base, site_device_approval=True, webauthn_rp_id="a.example", webauthn_origin="https://a.example", site_device_bootstrap_code="short").environment_problems())
    assert any("only applies" in p for p in Settings(**dict(base, access_mode="login"), site_device_approval=True).environment_problems())
