"""ACCESS_MODE=passcode: one site password, lockouts, audit trail, sessions."""
import pytest

from app import sitepass
from app.config import Settings, settings
from app.security import hash_password

SITE_PW = "Correct-Horse-Battery-2026"


@pytest.fixture
def passcode(monkeypatch):
    monkeypatch.setattr(settings, "access_mode", "passcode")
    monkeypatch.setattr(settings, "site_password_hash", hash_password(SITE_PW))
    monkeypatch.setattr(settings, "site_default_user", "ADMIN")
    monkeypatch.setattr(settings, "site_lock_failures", 3)
    monkeypatch.setattr(settings, "site_lock_minutes", 15)
    sitepass.clear()
    yield
    sitepass.clear()


def _unlock(client, pw, ip="203.0.113.7"):
    return client.post("/api/auth/unlock", json={"password": pw}, headers={"X-Forwarded-For": ip, "User-Agent": "pytest"})


def test_password_screen_is_the_only_way_in(client, passcode):
    assert client.get("/api/health").json()["access_mode"] == "passcode"
    assert client.get("/api/employees").status_code == 401                       # nothing without an unlock
    assert client.post("/api/auth/login", json={"username": "ADMIN", "password": settings.demo_password}).status_code == 403  # no user-name sign-in
    assert _unlock(client, "wrong-password").status_code == 401
    ok = _unlock(client, SITE_PW)
    assert ok.status_code == 200 and ok.json()["user"]["Initials"] == "ADMIN" and ok.json()["must_change_password"] is False
    tok = {"Authorization": "Bearer " + ok.json()["access_token"]}
    assert client.get("/api/auth/me", headers=tok).status_code == 200
    assert client.get("/api/employees", headers=tok).status_code == 200
    assert client.post("/api/auth/change-password", headers=tok, json={"current_password": SITE_PW, "new_password": "x" * 20}).status_code == 403
    # a web sign-in token from login mode is not accepted by the password screen's guard
    from app.security import create_access_token
    from app.models import OfficeStaff
    from app.database import SessionLocal
    with SessionLocal() as db:
        admin = db.query(OfficeStaff).filter(OfficeStaff.Initials == "ADMIN").first()
        legacy = create_access_token(admin)
    assert client.get("/api/employees", headers={"Authorization": "Bearer " + legacy}).status_code == 401


def test_lockout_per_address_and_for_everyone(client, passcode, monkeypatch):
    for _ in range(3):
        assert _unlock(client, "nope", ip="198.51.100.1").status_code == 401
    locked = _unlock(client, SITE_PW, ip="198.51.100.1")                           # even the right password is refused while locked
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0
    assert _unlock(client, SITE_PW, ip="198.51.100.2").status_code == 200           # another address is unaffected
    monkeypatch.setattr(settings, "site_global_lock_failures", 6)
    for ip in ("198.51.100.3", "198.51.100.4", "198.51.100.5"):
        _unlock(client, "nope", ip=ip)
    everyone = _unlock(client, SITE_PW, ip="198.51.100.9")
    assert everyone.status_code == 429                                              # an address never seen succeeding waits during a distributed attack
    office = _unlock(client, SITE_PW, ip="198.51.100.2")
    assert office.status_code == 200                                                # an address that unlocked before keeps working: nobody can lock the company out
    log = sitepass.recent(50)
    assert any(r["note"] == "locked:everyone" for r in log) and any(r["note"] == "locked:address" for r in log)
    assert all("nope" not in str(r) and SITE_PW not in str(r) for r in log)         # never the password


def test_audit_trail_for_administrators(client, passcode):
    _unlock(client, "bad")
    ok = _unlock(client, SITE_PW)
    tok = {"Authorization": "Bearer " + ok.json()["access_token"]}
    r = client.get("/api/auth/unlock-log", headers=tok)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["attempts_24h"] >= 2 and body["summary"]["failed_24h"] >= 1
    notes = [a["note"] for a in body["attempts"]]
    assert "ok" in notes and "wrong" in notes
    assert body["attempts"][0]["identity"] == "default:admin"
    st = client.get("/api/system/status", headers=tok).json()
    assert st["site_unlock"]["session_minutes"] == settings.site_session_minutes


def test_settings_rules_for_the_site_password():
    base = dict(data_source="staging", jwt_secret="x" * 40, access_mode="passcode", web_admins="ARI")
    assert any("SITE_PASSWORD_HASH" in p for p in Settings(**base).environment_problems())
    assert any("SITE_PASSWORD_HASH" in p for p in Settings(**base, site_password_hash="plain-text-password").environment_problems())
    good = dict(base, site_password_hash=hash_password("Something-Long-Enough-1"), site_default_user="ARI")
    assert not any("SITE_" in p for p in Settings(**good).environment_problems())
    assert any("SITE_DEFAULT_USER" in p for p in Settings(**dict(good, site_default_user="")).environment_problems())
    cf = dict(good, site_default_user="", gateway_platform="cloudflare-access", cloudflare_access_team_domain="t.cloudflareaccess.com", cloudflare_access_aud="a" * 64)
    assert not any("SITE_DEFAULT_USER" in p for p in Settings(**cf).environment_problems())
    prod = dict(good, data_source="production", production_database_url="postgresql+psycopg://u:p@h/x?sslmode=require")
    assert any("Production needs its own site password" in p for p in Settings(**prod).environment_problems())
    assert not any("Production needs its own site password" in p for p in Settings(**prod, site_password_label="production-2026-12").environment_problems())
    assert any("SITE_SESSION_MINUTES" in p for p in Settings(**good, site_session_minutes=5000).environment_problems())
