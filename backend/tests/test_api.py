from __future__ import annotations

from datetime import date, timedelta

from app.ai import heuristic_interpret
from app.config import settings

VOCAB = {"cities": ["Boston", "Worcester", "Providence"], "industries": ["Healthcare Facilities"], "salesmen": ["Jane Doe"], "customers": []}


# ------------------------------------------------------------------ AI parser
def test_heuristic_employee_query():
    i = heuristic_interpret("employees", "licensed journeyman electricians in Worcester with 5+ years who will travel", VOCAB)
    assert i.filters["trade"] == "Electrician"
    assert i.filters["qualification"] == "Journeyman"
    assert i.filters["city"] == "Worcester"
    assert i.filters["licensed"] is True
    assert i.filters["min_years"] == 5
    assert i.filters["will_travel"] is True
    assert i.mode == "heuristic"


def test_heuristic_customer_query():
    i = heuristic_interpret("customers", "active general contractors in Boston with jobs running", VOCAB)
    assert i.filters["status"] == "Active"
    assert i.filters["customer_type"] == "General Contractor"
    assert i.filters["city"] == "Boston"
    assert i.filters["has_active_projects"] is True


def test_heuristic_project_query():
    i = heuristic_interpret("projects", "active jobs in Massachusetts that are not manned", VOCAB)
    assert i.filters["status"] == "Active"
    assert i.filters["state"] == "MA"
    assert i.filters["manned"] is False


def test_heuristic_keywords_left_over():
    i = heuristic_interpret("employees", "find Garcia the plumber", VOCAB)
    assert i.filters["trade"] == "Plumber"
    assert "garcia" in i.keywords


def test_heuristic_pilot_corrections():
    """Four readings the staging pilot found too loose (docs/production/10, finding 4)."""
    # "active jobs" describes the customer's jobs, not the customer's status
    i = heuristic_interpret("customers", "customers in MA with active jobs", VOCAB)
    assert i.filters["has_active_projects"] is True and "status" not in i.filters and i.filters["state"] == "MA"
    assert heuristic_interpret("customers", "active customers with active jobs", VOCAB).filters["status"] == "Active"
    # a city named in a job question is not also a customer, and "starting this month" is a start window, not a status
    v = {**VOCAB, "cities": ["Hartford", "Boston"], "customers": ["HARTFORD"]}
    i = heuristic_interpret("projects", "jobs in Hartford starting this month", v)
    assert i.filters["city"] == "Hartford" and i.filters["start_window"] == "this_month" and "customer" not in i.filters and "status" not in i.filters
    assert heuristic_interpret("projects", "pending jobs", VOCAB).filters["status"] == "Pending"
    # customer types follow the real lookup labels when they are known, and are dropped when the real list has nothing like them
    i = heuristic_interpret("customers", "general contractors in CT", {**VOCAB, "customer_types": ["General Contractors", "Electrical Contractors"]})
    assert i.filters["customer_type"] == "General Contractors" and i.filters["state"] == "CT"
    i = heuristic_interpret("customers", "general contractors in CT", {**VOCAB, "customer_types": ["Builder", "Electrical"]})
    assert "customer_type" not in i.filters and i.filters["state"] == "CT"
    assert heuristic_interpret("customers", "general contractors in CT", VOCAB).filters["customer_type"] == "General Contractor"  # demo: no real list
    # the words that expressed a number of years are not search words
    i = heuristic_interpret("employees", "available plumbers with 5+ years experience", VOCAB)
    assert i.filters["min_years"] == 5 and i.filters["status"] == "Available" and i.keywords == []


# ------------------------------------------------------------------ auth
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ai_mode"] == "heuristic"


def test_login_bad_password(client):
    r = client.post("/api/auth/login", json={"username": "ADMIN", "password": "nope"})
    assert r.status_code == 401


def test_requires_auth(client):
    assert client.get("/api/employees").status_code == 401


def test_me(client, admin_headers):
    r = client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["Profile"] is True
    assert "users.manage" in r.json()["features"]


# ------------------------------------------------------------------ lookups / dashboard
def test_lookups(client, admin_headers):
    r = client.get("/api/lookups", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["trades"]) >= 10
    assert any(s["label"] == "MA" for s in body["states"])
    assert len(body["features"]) == 12


def test_dashboard(client, admin_headers):
    r = client.get("/api/dashboard", headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["employees_total"] >= 150
    assert d["users_total"] >= 30
    assert d["projects_total"] >= 80
    assert len(d["weekly_hours"]) > 0


# ------------------------------------------------------------------ employees
def test_employee_list_and_filters(client, admin_headers):
    r = client.get("/api/employees", headers=admin_headers, params={"page_size": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 150 and len(body["items"]) == 10
    r = client.get("/api/employees", headers=admin_headers, params={"state": "MA", "licensed": "true", "page_size": 200})
    assert all(i["EmState"] == "MA" and i["license_count"] >= 1 for i in r.json()["items"])


def test_employee_crud(client, admin_headers):
    lk = client.get("/api/lookups", headers=admin_headers).json()
    trade = next(t for t in lk["trades"] if t["label"] == "Electrician")
    city = next(c for c in lk["cities"] if c["label"] == "Worcester")
    payload = {
        "EmFirstName": "Testy", "EmLastName": "McTestface", "EmMobilePhone": "(508) 555-0100",
        "EmTradeID": trade["id"], "EmStateCityID": city["id"], "YearsInTrade": 7, "BaseSalary": 36.5,
        "licenses": [{"EmployeeLicenseNumber": "JE-12345", "EmployeeLicenseExpDate": str(date.today() + timedelta(days=30))}],
    }
    r = client.post("/api/employees", headers=admin_headers, json=payload)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["EmCity"] == "Worcester" and e["EmState"] == "MA"
    assert e["trade_name"] == "Electrician"
    assert len(e["licenses"]) == 1
    eid = e["EmployeeID"]

    r = client.put(f"/api/employees/{eid}", headers=admin_headers, json={"YearsInTrade": 8, "EmAdminNotes": "Updated in test"})
    assert r.status_code == 200 and r.json()["YearsInTrade"] == 8

    r = client.post(f"/api/employees/{eid}/notes", headers=admin_headers, json={"EmployeeNote": "Called back"})
    assert r.status_code == 201 and r.json()["EmployeeNoteUserName"] == "ADMIN"

    r = client.get("/api/employees", headers=admin_headers, params={"q": "mctestface"})
    assert r.json()["total"] == 1

    # AI search on the heuristic engine should find the licensed electrician in Worcester
    r = client.post("/api/search", headers=admin_headers, json={"entity": "employees", "query": "licensed electricians in Worcester expiring in 60 days"})
    assert r.status_code == 200
    body = r.json()
    assert body["ai"]["mode"] == "heuristic"
    assert body["ai"]["filters"]["license_expiring_days"] == 60
    assert any(i["EmployeeID"] == eid for i in body["items"])

    r = client.put(f"/api/employees/{eid}", headers=admin_headers, json={"BogusField": 1})
    assert r.status_code == 422

    r = client.delete(f"/api/employees/{eid}", headers=admin_headers)
    assert r.status_code == 204
    assert client.get(f"/api/employees/{eid}", headers=admin_headers).status_code == 404


# ------------------------------------------------------------------ customers / projects / tracking
def test_customer_project_tracking_flow(client, admin_headers):
    lk = client.get("/api/lookups", headers=admin_headers).json()
    city = next(c for c in lk["cities"] if c["label"] == "Boston")
    status_active = next(s for s in lk["customer_statuses"] if s["label"] == "Active")
    gc = next(t for t in lk["customer_types"] if t["label"] == "General Contractor")
    r = client.post("/api/customers", headers=admin_headers, json={
        "CustBusName": "Test Build Co", "StateCityID": city["id"], "Phone": "(617) 555-0199", "CustStatusID": status_active["id"],
        "CustomerTypeID": gc["id"], "ContractOnFile": True, "RevenuePerYear": 250000,
        "contacts": [{"CustomerContactFName": "Pat", "CustomerContactLName": "Jones", "CustomerContactEmail": "pat@test.example"}],
    })
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["City"] == "Boston" and len(c["contacts"]) == 1
    cid = c["CustomerID"]

    proj_active = next(s for s in lk["project_statuses"] if s["label"] == "Active")
    r = client.post("/api/projects", headers=admin_headers, json={
        "CustomerID": cid, "SiteName": "Test Tower", "SiteStateCityID": city["id"], "StartDate": str(date.today()),
        "ProjStatusID": proj_active["id"], "NumberOfEmployees": 5, "JobBeingManned": False,
    })
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["customer_name"] == "Test Build Co"
    pid = p["ProjectID"]

    r = client.post("/api/search", headers=admin_headers, json={"entity": "projects", "query": "active jobs in Boston that are not manned"})
    assert any(i["ProjectID"] == pid for i in r.json()["items"])

    r = client.post("/api/search", headers=admin_headers, json={"entity": "customers", "query": "general contractors in Boston with contract and revenue over 100000"})
    body = r.json()
    assert body["ai"]["filters"]["min_revenue"] == 100000
    assert any(i["CustomerID"] == cid for i in body["items"])

    emp = client.get("/api/employees", headers=admin_headers, params={"page_size": 1}).json()["items"][0]
    r = client.post("/api/tracking", headers=admin_headers, json={
        "CustomerID": cid, "EmployeeID": emp["EmployeeID"], "ProjectID": pid, "WeekEndingDate": str(date.today()),
        "PayRate": 30, "BillRate": 45, "MonHours": 8, "TueHours": 8, "WedHours": 8, "ThuHours": 8, "FriHours": 10, "SatHours": 4,
    })
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["TotalHours"] == 46 and t["OvertimeHours"] == 6
    assert t["EmGrossPayroll"] == 40 * 30 + 6 * 45
    assert t["InvoiceAmount"] == 40 * 45 + 6 * 67.5
    assert t["WeekEndingDate"] >= str(date.today())
    # duplicate guard
    r = client.post("/api/tracking", headers=admin_headers, json={"CustomerID": cid, "EmployeeID": emp["EmployeeID"], "ProjectID": pid, "WeekEndingDate": str(date.today()), "PayRate": 30, "BillRate": 45})
    assert r.status_code == 409

    r = client.put(f"/api/tracking/{t['TrackingID']}", headers=admin_headers, json={"FriHours": 0})
    assert r.json()["TotalHours"] == 36

    r = client.get(f"/api/projects/{pid}", headers=admin_headers)
    assert len(r.json()["assignments"]) == 1

    assert client.delete(f"/api/projects/{pid}", headers=admin_headers).status_code == 409  # has tracking
    assert client.delete(f"/api/tracking/{t['TrackingID']}", headers=admin_headers).status_code == 204
    assert client.delete(f"/api/projects/{pid}", headers=admin_headers).status_code == 204
    assert client.delete(f"/api/customers/{cid}", headers=admin_headers).status_code == 204


# ------------------------------------------------------------------ users & permissions
def test_user_management_and_permissions(client, admin_headers):
    lk = client.get("/api/lookups", headers=admin_headers).json()
    view_emp = next(f for f in lk["features"] if f["extra"]["object"] == "employees.view")
    r = client.post("/api/users", headers=admin_headers, json={
        "OfficeStaffFirstName": "Limited", "OfficeStaffLastName": "User", "Initials": "LU1", "OfficeStaffTitle": "Recruiter",
        "password": "secret123", "feature_ids": [view_emp["id"]],
    })
    assert r.status_code == 201, r.text
    uid = r.json()["OfficeStaffID"]

    r = client.post("/api/auth/login", json={"username": "lu1", "password": "secret123"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/employees", headers=h).status_code == 200
    assert client.get("/api/customers", headers=h).status_code == 403
    assert client.post("/api/employees", headers=h, json={"EmFirstName": "a", "EmLastName": "b"}).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403

    r = client.put(f"/api/users/{uid}", headers=admin_headers, json={"feature_ids": [], "password": "newpass123"})
    assert r.status_code == 200 and r.json()["feature_ids"] == []
    assert client.post("/api/auth/login", json={"username": "LU1", "password": "newpass123"}).status_code == 200

    r = client.get("/api/users", headers=admin_headers, params={"page_size": 200})
    assert r.json()["total"] >= 32

    assert client.delete(f"/api/users/{uid}", headers=admin_headers).status_code == 204
    assert client.post("/api/auth/login", json={"username": "LU1", "password": "newpass123"}).status_code == 403


def test_demo_password_default():
    assert settings.demo_password


# ------------------------------------------------------------------ interactive AI search
def test_ai_search_facets_reasons_and_refinement(client, admin_headers):
    r = client.post("/api/search", headers=admin_headers, json={"entity": "employees", "query": "electricians in Massachusetts"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] > 0
    assert body["ai"]["summary"].startswith(str(body["total"]))
    keys = {f["key"] for f in body["facets"]}
    assert "city" in keys and "qualification" in keys
    assert all("MA" in " ".join(i["reasons"]) for i in body["items"])
    assert any(s["label"] == "Licensed only" for s in body["ai"]["suggestions"])

    # follow-up query refines the previous filters
    r = client.post("/api/search", headers=admin_headers, json={
        "entity": "employees", "query": "only licensed ones", "refine": True, "base_filters": body["ai"]["filters"],
    })
    ref = r.json()
    assert ref["ai"]["filters"]["trade"] == "Electrician" and ref["ai"]["filters"]["licensed"] is True
    assert ref["ai"]["interpretation"].startswith("Refined")
    assert ref["total"] <= body["total"]

    # manual filter override (chip removed) - no query needed
    r = client.post("/api/search", headers=admin_headers, json={"entity": "employees", "filters": {"trade": "Electrician"}, "keywords": []})
    man = r.json()
    assert man["ai"]["mode"] == "manual" and man["total"] >= body["total"]

    # empty query without filters is rejected
    assert client.post("/api/search", headers=admin_headers, json={"entity": "employees", "query": "  "}).status_code == 422


def test_bulk_assign(client, admin_headers):
    proj = client.get("/api/projects", headers=admin_headers, params={"page_size": 1}).json()["items"][0]
    emps = client.get("/api/employees", headers=admin_headers, params={"page_size": 3, "page": 3}).json()["items"]
    ids = [e["EmployeeID"] for e in emps]
    r = client.post("/api/tracking/bulk", headers=admin_headers, json={"ProjectID": proj["ProjectID"], "EmployeeIDs": ids + [ids[0]], "WeekEndingDate": "2031-01-06"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["created"]) == 3 and body["skipped"] == []
    assert body["week_ending"] == "2031-01-10"  # snapped to Friday
    r = client.post("/api/tracking/bulk", headers=admin_headers, json={"ProjectID": proj["ProjectID"], "EmployeeIDs": ids[:1], "WeekEndingDate": "2031-01-06"})
    assert r.json()["created"] == [] and r.json()["skipped"][0]["reason"] == "already assigned that week"
    for t in body["created"]:
        assert client.delete(f"/api/tracking/{t['TrackingID']}", headers=admin_headers).status_code == 204
