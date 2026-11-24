"""No-login DEMO, and the prepared gateway mode for real data."""
from app.config import Settings, settings

SECRET = "g" * 40


def test_demo_open_mode_needs_no_sign_in(client, monkeypatch):
    monkeypatch.setattr(settings, "access_mode", None)  # the demo default
    assert settings.access == "open"
    assert client.get("/api/health").json()["access_mode"] == "open"
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["Profile"] is True
    for path in ("/api/dashboard", "/api/employees", "/api/customers", "/api/projects", "/api/tracking", "/api/lookups", "/api/search/status"):
        assert client.get(path).status_code == 200, path
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer stale-or-expired-token"}).status_code == 200
    r = client.post("/api/search", json={"entity": "employees", "query": "licensed electricians in MA"})
    assert r.status_code == 200 and "items" in r.json()


def test_demo_login_mode_still_asks_for_sign_in(client, monkeypatch):
    monkeypatch.setattr(settings, "access_mode", "login")
    assert client.get("/api/employees").status_code == 401


def test_real_data_can_never_be_open():
    for env in ("staging", "production"):
        s = Settings(data_source=env, access_mode="open")
        assert s.access == "login"
        assert any("anonymous access is refused" in p for p in s.environment_problems())
        assert Settings(data_source=env).access == "login"  # default with real data: the sign-in page


def test_gateway_mode_needs_a_long_secret():
    assert any("GATEWAY_SECRET" in p for p in Settings(data_source="staging", access_mode="gateway", gateway_secret="short").environment_problems())
    assert not any("GATEWAY" in p for p in Settings(data_source="staging", access_mode="gateway", gateway_secret=SECRET).environment_problems())


def test_gateway_mode_refuses_everything_that_did_not_come_through_the_gateway(client, admin_headers, monkeypatch):
    email = client.get("/api/auth/me", headers=admin_headers).json()["OfficeStaffEmail"]
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "gateway")
    monkeypatch.setattr(settings, "gateway_secret", SECRET)
    monkeypatch.setattr(settings, "gateway_trusted_proxies", "testclient")  # the test client's address; a real gateway is 127.0.0.1
    monkeypatch.setattr(settings, "web_admins", email)
    assert client.get("/api/auth/me").status_code == 401                                   # anonymous
    assert client.get("/api/auth/me", headers=admin_headers).status_code == 401            # a web sign-in token alone
    assert client.get("/api/auth/me", headers={"X-Auth-Request-Email": email}).status_code == 401           # forged e-mail, no secret
    assert client.get("/api/auth/me", headers={"X-Gateway-Secret": "x" * 40, "X-Auth-Request-Email": email}).status_code == 401
    assert client.get("/api/auth/me", headers={"X-Gateway-Secret": SECRET}).status_code == 403              # gateway, but no person
    assert client.get("/api/auth/me", headers={"X-Gateway-Secret": SECRET, "X-Auth-Request-Email": "stranger@example.com"}).status_code == 403
    ok = client.get("/api/auth/me", headers={"X-Gateway-Secret": SECRET, "X-Auth-Request-Email": email.upper()})
    assert ok.status_code == 200 and ok.json()["Profile"] is True
    assert client.post("/api/auth/login", json={"username": "ADMIN", "password": "whatever-it-is"}).status_code == 403


def test_gateway_headers_from_an_untrusted_address_are_refused_even_with_the_secret(client, admin_headers, monkeypatch):
    email = client.get("/api/auth/me", headers=admin_headers).json()["OfficeStaffEmail"]
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "gateway")
    monkeypatch.setattr(settings, "gateway_secret", SECRET)
    monkeypatch.setattr(settings, "web_admins", email)
    monkeypatch.setattr(settings, "gateway_trusted_proxies", "127.0.0.1,::1")  # the default: the test client is not the gateway
    r = client.get("/api/auth/me", headers={"X-Gateway-Secret": SECRET, "X-Auth-Request-Email": email})
    assert r.status_code == 401
    assert any("GATEWAY_TRUSTED_PROXIES" in p for p in Settings(data_source="staging", access_mode="gateway", gateway_secret=SECRET, gateway_trusted_proxies="").environment_problems())


def _staff(client, admin_headers):
    """Two demo accounts: the administrator and one ordinary staff member (initials, e-mail)."""
    users = client.get("/api/users", headers=admin_headers, params={"active": "true", "page_size": 200}).json()["items"]
    admin = next(u for u in users if u["Initials"] == "ADMIN")
    other = next(u for u in users if u["Initials"] != "ADMIN" and u["OfficeStaffEmail"])
    return admin, other


def _staging_token(staff_id: int) -> dict[str, str]:
    """A valid sign-in for the staging environment (a demo token is rejected there by design)."""
    import jwt
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return {"Authorization": "Bearer " + jwt.encode({"sub": str(staff_id), "env": "staging", "iat": now, "exp": now + timedelta(minutes=5)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)}


def test_real_data_refuses_people_on_neither_access_list(client, admin_headers, monkeypatch):
    admin, other = _staff(client, admin_headers)
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "login")
    monkeypatch.setattr(settings, "web_admins", "")
    monkeypatch.setattr(settings, "web_users", "")
    headers = _staging_token(admin["OfficeStaffID"])
    # the sign-in is valid, but with real data the name must be on a list
    assert client.get("/api/auth/me", headers=headers).status_code == 403
    assert client.get("/api/employees", headers=headers).status_code == 403
    # a web password alone does not get anyone in either
    r = client.post("/api/auth/login", json={"username": "ADMIN", "password": settings.demo_password})
    assert r.status_code == 403 and "not been given access" in r.json()["detail"]
    monkeypatch.setattr(settings, "web_admins", admin["Initials"])
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/login", json={"username": "ADMIN", "password": settings.demo_password}).status_code == 200


def test_web_users_get_the_view_only_pages_and_nothing_else(client, admin_headers, monkeypatch):
    admin, other = _staff(client, admin_headers)
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "login")
    monkeypatch.setattr(settings, "web_admins", admin["Initials"])
    monkeypatch.setattr(settings, "web_users", other["OfficeStaffEmail"].upper())  # e-mail, any case
    admin_headers = _staging_token(admin["OfficeStaffID"])
    other_headers = _staging_token(other["OfficeStaffID"])
    me = client.get("/api/auth/me", headers=other_headers).json()
    assert me["Profile"] is False and set(me["features"]) == {"employees.view", "customers.view", "projects.view", "tracking.view", "ai.search"}
    for path in ("/api/employees", "/api/customers", "/api/projects", "/api/tracking", "/api/search/status"):
        assert client.get(path, headers=other_headers).status_code == 200, path
    assert client.get("/api/users", headers=other_headers).status_code == 403            # user management: administrators only
    assert client.get("/api/system/status", headers=other_headers).status_code == 403    # system status: administrators only
    # changes are refused by the read-only middleware before any permission check (423), never allowed
    assert client.post("/api/employees", headers=other_headers, json={"EmFirstName": "A", "EmLastName": "B"}).status_code == 423
    # the administrator keeps everything
    assert client.get("/api/auth/me", headers=admin_headers).json()["Profile"] is True
    assert client.get("/api/users", headers=admin_headers).status_code == 200


def test_outside_ai_service_needs_the_owners_approval_with_real_data(client, admin_headers, monkeypatch):
    from app.ai import ai_mode, claude_interpret

    # demo: a key is enough
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    assert settings.claude_allowed and ai_mode() == "claude"
    # real data: the key alone is refused at start-up, and never used without the approval reference
    s = Settings(data_source="staging", anthropic_api_key="sk-ant-test")
    assert any("CLAUDE_REAL_DATA_APPROVAL" in p for p in s.environment_problems()) and not s.claude_allowed
    assert Settings(data_source="staging", anthropic_api_key="sk-ant-test", claude_real_data_approval="owner e-mail 2026-12-01").claude_allowed
    assert not any("CLAUDE" in p for p in Settings(data_source="staging", anthropic_api_key="sk-ant-test", claude_real_data_approval="owner e-mail 2026-12-01").environment_problems())
    monkeypatch.setattr(settings, "data_source", "staging")
    assert not settings.claude_allowed and ai_mode() == "heuristic"
    assert claude_interpret("employees", "electricians in boston", {"cities": ["Boston"]}) is None  # no call is attempted
    monkeypatch.setattr(settings, "web_admins", "ADMIN")
    admin_id = client.get("/api/auth/me", headers=_staging_token(1)).json()["OfficeStaffID"]
    body = client.get("/api/system/status", headers=_staging_token(admin_id)).json()
    assert body["outside_ai_service"] == {"api_key_present": True, "used": False, "approval_recorded": False, "sent_when_used": "the typed question, fixed vocabulary and city names"}
    assert body["access"]["administrators_listed"] == 1 and body["access"]["mode"] == "login"


def test_administrators_grant_and_remove_access_without_a_restart(client, admin_headers, monkeypatch):
    from app import webauth

    admin, other = _staff(client, admin_headers)
    users = client.get("/api/users", headers=admin_headers, params={"active": "true", "page_size": 200}).json()["items"]
    third = next(u for u in users if u["OfficeStaffID"] not in (admin["OfficeStaffID"], other["OfficeStaffID"]))
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "login")
    monkeypatch.setattr(settings, "web_admins", admin["Initials"])   # the bootstrap administrator from the settings file
    monkeypatch.setattr(settings, "web_users", "")
    webauth.set_access(other["OfficeStaffID"], None, by="test"); webauth.set_access(third["OfficeStaffID"], None, by="test")
    admin_h, other_h, third_h = _staging_token(admin["OfficeStaffID"]), _staging_token(other["OfficeStaffID"]), _staging_token(third["OfficeStaffID"])
    try:
        assert client.get("/api/employees", headers=other_h).status_code == 403                                   # nobody but the bootstrap admin
        # grant look-up access on the Users page: effective at once, stored in the website's own file, not in the McLabor database
        r = client.put(f"/api/users/{other['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "user"})
        assert r.status_code == 200 and r.json()["web_access"] == "user" and r.json()["web_access_source"] == "store"
        assert client.get("/api/employees", headers=other_h).status_code == 200
        assert client.get("/api/users", headers=other_h).status_code == 403                                       # look-up only
        # promote to administrator, then remove: each change takes effect on the next request
        assert client.put(f"/api/users/{other['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "admin"}).json()["Profile"] is True
        assert client.get("/api/users", headers=other_h).status_code == 200
        assert client.put(f"/api/users/{other['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "none"}).json()["web_access"] == "none"
        assert client.get("/api/employees", headers=other_h).status_code == 403
        # guards: nobody removes their own administrator access; the settings-file people are changed in the file, not here
        assert client.put(f"/api/users/{admin['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "user"}).status_code == 400
        monkeypatch.setattr(settings, "web_users", third["Initials"])
        assert client.put(f"/api/users/{third['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "none"}).status_code == 409
        assert client.get("/api/users", headers=admin_h).json()["items"] and any(u["web_access_source"] == "settings" for u in client.get("/api/users", headers=admin_h).json()["items"])
        # a look-up user cannot grant access
        monkeypatch.setattr(settings, "web_users", "")
        webauth.set_access(other["OfficeStaffID"], "user", by="test")
        assert client.put(f"/api/users/{third['OfficeStaffID']}/web-access", headers=other_h, json={"role": "user"}).status_code == 403
        # the command line does the same (for an administrator at the server)
        from app.webauth import main as webauth_main

        assert webauth_main(["webauth", "access-set", third["Initials"], "user"]) == 0 and webauth.access_roles()[third["OfficeStaffID"]] == "user"
        assert webauth_main(["webauth", "access-list"]) == 0
    finally:
        for sid in (other["OfficeStaffID"], third["OfficeStaffID"]):
            webauth.set_access(sid, None, by="test")


def test_seat_limit_counts_unique_users_warns_and_refuses_the_51st(client, admin_headers, monkeypatch):
    from app import webauth

    admin, other = _staff(client, admin_headers)
    users = [u for u in client.get("/api/users", headers=admin_headers, params={"active": "true", "page_size": 200}).json()["items"] if u["OfficeStaffID"] != admin["OfficeStaffID"]]
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "login")
    monkeypatch.setattr(settings, "web_admins", admin["Initials"])
    monkeypatch.setattr(settings, "web_users", "")
    monkeypatch.setattr(settings, "access_seat_limit", 4)   # 1 bootstrap administrator + 3 granted
    monkeypatch.setattr(settings, "access_seat_warn", 3)
    admin_h = _staging_token(admin["OfficeStaffID"])
    for u in users[:5]:
        webauth.set_access(u["OfficeStaffID"], None, by="test")
    try:
        s = client.get("/api/users/access-summary", headers=admin_h).json()
        assert s["authorized"] == 1 and s["seats_left"] == 3 and s["warning"] is False and s["used_this_month"] == 0
        assert client.put(f"/api/users/{users[0]['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "user"}).status_code == 200
        assert client.put(f"/api/users/{users[1]['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "user"}).status_code == 200
        s = client.get("/api/users/access-summary", headers=admin_h).json()
        assert s["authorized"] == 3 and s["warning"] is True and "3 of 4 authorized website users" in s["message"]   # warning from the warn threshold on
        assert s["service_seats_used"] == 3 + settings.access_other_seats and s["service_seat_limit"] == 50       # website users + the Access PCs' WARP users
        assert client.put(f"/api/users/{users[2]['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "user"}).status_code == 200   # the 4th seat
        r = client.put(f"/api/users/{users[3]['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "user"})
        assert r.status_code == 409 and "seat limit" in r.json()["detail"]                                        # the 5th is refused
        assert client.put(f"/api/users/{users[0]['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "admin"}).status_code == 200  # changing a role needs no new seat
        # unique users: someone who used the website this month counts once, however many requests they make
        user_h = _staging_token(users[1]["OfficeStaffID"])
        for _ in range(3):
            assert client.get("/api/employees", headers=user_h).status_code == 200
        assert client.get("/api/users/access-summary", headers=admin_h).json()["used_this_month"] == 1
        st = client.get("/api/system/status", headers=admin_h).json()["access"]
        assert st["authorized"] == 4 and st["seat_limit"] == 4 and st["warning"] is True
        monkeypatch.setattr(settings, "access_seat_limit", 0)                                                      # no limit configured
        assert client.put(f"/api/users/{users[3]['OfficeStaffID']}/web-access", headers=admin_h, json={"role": "user"}).status_code == 200
        # the sign-in service's own limit warns on its own: 5 website users + 44 other users = 49 of 50
        monkeypatch.setattr(settings, "access_other_seats", 44)
        s = client.get("/api/users/access-summary", headers=admin_h).json()
        assert s["service_seats_used"] == 49 and s["warning"] is True and "49 of 50 seats of the sign-in service" in s["message"]
        assert Settings(data_source="demo").access_seat_limit == 20 and Settings(data_source="demo").access_seat_warn == 16  # the company maximum
    finally:
        for u in users[:5]:
            webauth.set_access(u["OfficeStaffID"], None, by="test")


def test_users_list_shows_website_access_with_real_data(client, admin_headers, monkeypatch):
    admin, other = _staff(client, admin_headers)
    assert all(u["web_access"] in ("admin", "features") for u in client.get("/api/users", headers=admin_headers, params={"page_size": 200}).json()["items"])
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "web_admins", admin["Initials"])
    monkeypatch.setattr(settings, "web_users", other["Initials"])
    by_id = {u["OfficeStaffID"]: u["web_access"] for u in client.get("/api/users", headers=_staging_token(admin["OfficeStaffID"]), params={"page_size": 200}).json()["items"]}
    assert by_id[admin["OfficeStaffID"]] == "admin" and by_id[other["OfficeStaffID"]] == "user"
    assert "none" in by_id.values()  # everyone else


def test_search_memory_never_bypasses_authorization_and_forgets_after_a_change(client, admin_headers, monkeypatch):
    """The 30-second memory of counts and result ids is shared by all users of one environment: it may be, because every
    request is authorized BEFORE the memory is consulted, and it holds ids and labels only, never records."""
    from app import search

    users = client.get("/api/users", headers=admin_headers, params={"page_size": 200}).json()["items"]
    limited = next(u for u in users if not u["Profile"] and "employees.view" not in u["features"] and u["OfficeStaffActive"])
    r = client.post("/api/auth/login", json={"username": limited["Initials"], "password": settings.demo_password})
    limited_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    monkeypatch.setattr(settings, "search_cache_seconds", 30)
    search.clear_result_cache()
    try:
        first = client.get("/api/employees", headers=admin_headers, params={"q": "smith"})
        assert first.status_code == 200 and search._ids_cache  # the administrator's search is remembered
        remembered = next(iter(search._ids_cache.values()))[1]
        assert all(isinstance(i, int) for i in remembered[0]) and isinstance(remembered[1], int)  # ids and a total, nothing else
        assert client.get("/api/employees", headers=limited_headers, params={"q": "smith"}).status_code == 403  # no permission: no results, memory or not
        assert client.get("/api/employees", headers=admin_headers, params={"q": "smith"}).json()["total"] == first.json()["total"]
        # a change to a record empties the memory so the next search is exact
        note = client.post("/api/customers/1/notes", headers=admin_headers, json={"CustomerNote": "cache test"})
        assert note.status_code == 201
        assert not search._ids_cache and not search._result_cache
    finally:
        search.clear_result_cache()


def test_real_data_prompt_never_includes_staff_names_or_customer_text(monkeypatch):
    from app.ai import _system_prompt

    vocab = {"cities": ["Boston"], "industries": ["Secret Customer Industry"], "salesmen": ["Pat Staffname"]}
    demo = _system_prompt("customers", vocab)
    assert "Pat Staffname" in demo and "Secret Customer Industry" in demo
    monkeypatch.setattr(settings, "data_source", "staging")
    real = _system_prompt("customers", vocab)
    assert "Boston" in real and "Pat Staffname" not in real and "Secret Customer Industry" not in real
