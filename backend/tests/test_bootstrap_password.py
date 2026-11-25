"""WEB_BOOTSTRAP_PASSWORD: the first administrator's one-time sign-in on a fresh hosted deployment."""
from app import webauth
from app.config import Settings, settings
from tests.test_access_modes import _staff

BOOT = "Bootstrap-Only-Once-2026-xyz"


def _forget_password(staff_id: int) -> None:
    with webauth._session() as s:
        cred = s.get(webauth.WebCredential, staff_id)
        if cred is not None:
            s.delete(cred)
            s.commit()


def test_bootstrap_password_signs_in_the_first_admin_once(client, admin_headers, monkeypatch):
    admin, other = _staff(client, admin_headers)
    _forget_password(other["OfficeStaffID"])  # a fresh deployment: nobody has a web password yet
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "login")
    monkeypatch.setattr(settings, "web_admins", f"{other['Initials']}, {admin['Initials']}")
    monkeypatch.setattr(settings, "web_users", "")
    monkeypatch.setattr(settings, "web_bootstrap_password", BOOT)
    login = lambda who, pw: client.post("/api/auth/login", json={"username": who, "password": pw})  # noqa: E731

    assert login(other["Initials"], "not-the-bootstrap-value").status_code == 401
    assert login(admin["Initials"], BOOT).status_code == 401            # the second administrator: not the first name, and has a password
    first = login(other["Initials"], BOOT)
    assert first.status_code == 200 and first.json()["must_change_password"] is True
    token = {"Authorization": "Bearer " + first.json()["access_token"]}
    assert client.post("/api/auth/change-password", headers=token, json={"current_password": BOOT, "new_password": "A-real-password-chosen-now-1"}).status_code == 204
    assert login(other["Initials"], BOOT).status_code == 401            # used once; the real password is in place
    assert login(other["Initials"], "A-real-password-chosen-now-1").json()["must_change_password"] is False
    # the setting never overwrites an existing password, even when it is still configured
    assert webauth.bootstrap_first_admin(other["OfficeStaffID"], other["Initials"], other["OfficeStaffEmail"], BOOT) is False


def test_bootstrap_password_is_ignored_in_the_demo_and_checked_in_real_data():
    assert webauth.bootstrap_first_admin(1, "ADMIN", None, BOOT) is False  # demo: everyone has the demo password anyway
    short = Settings(data_source="staging", web_admins="ARI", web_bootstrap_password="short")
    assert any("WEB_BOOTSTRAP_PASSWORD" in p for p in short.environment_problems())
    demo = Settings(data_source="staging", web_admins="ARI", web_bootstrap_password="mclabor2025")
    assert any("WEB_BOOTSTRAP_PASSWORD" in p for p in demo.environment_problems())
    nobody = Settings(data_source="staging", web_admins="", web_bootstrap_password=BOOT)
    assert any("WEB_BOOTSTRAP_PASSWORD" in p for p in nobody.environment_problems())
    ok = Settings(data_source="staging", web_admins="ARI", web_bootstrap_password=BOOT)
    assert not any("WEB_BOOTSTRAP_PASSWORD" in p for p in ok.environment_problems())
