"""Duplicate detection, input validation and search behaviour (synthetic data)."""
from __future__ import annotations

from app.ai import heuristic_interpret
from app.duplicates import digits, norm_business


def _lookups(client, h):
    return client.get("/api/lookups", headers=h).json()


def _city(lk, name="Boston"):
    return next(c for c in lk["cities"] if c["label"] == name)


def _trade(lk, name):
    return next(t["id"] for t in lk["trades"] if t["label"] == name)


# ---------------------------------------------------------------- helpers
def test_normalisers():
    assert digits("(617) 555-0199") == "6175550199"
    assert digits("+1 617.555.0199") == "6175550199"
    assert norm_business("Probe Builders, LLC.") == norm_business("probe builders llc") == "probe builders"
    assert norm_business("The Smith & Sons Co") == "smith sons"


# ---------------------------------------------------------------- employees
def test_employee_duplicate_flow(client, admin_headers):
    h = admin_headers
    lk = _lookups(client, h)
    body = {"EmFirstName": "Dana", "EmLastName": "Quillfeather", "EmMobilePhone": "(508) 555-0142", "EmEmail": "dana.q@example.com",
            "EmStateCityID": _city(lk)["id"], "EmTradeID": _trade(lk, "Electrician"), "EmDOB": "1988-03-14"}
    r = client.post("/api/employees", json=body, headers=h)
    assert r.status_code == 201, r.text
    first_id = r.json()["EmployeeID"]

    # same person typed differently -> refused with candidates
    again = {"EmFirstName": " dana ", "EmLastName": "QUILLFEATHER", "EmMobilePhone": "508.555.0142"}
    r = client.post("/api/employees", json=again, headers=h)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["matches"][0]["id"] == first_id
    assert "same phone number" in detail["matches"][0]["reasons"]

    # same e-mail with a different name is still caught
    r = client.post("/api/employees", json={"EmFirstName": "D", "EmLastName": "Other", "EmEmail": "DANA.Q@example.com"}, headers=h)
    assert r.status_code == 409

    # live check while typing (typo in the last name) shows a possible match but does not block
    r = client.post("/api/employees/check-duplicates", json={"EmFirstName": "Dana", "EmLastName": "Quilfeather", "EmCity": "Boston"}, headers=h)
    assert r.status_code == 200
    m = r.json()["matches"]
    assert m and m[0]["id"] == first_id and m[0]["level"] == "possible"

    # user confirms -> created, and the override is audited
    r = client.post("/api/employees", json={**again, "allow_duplicate": True}, headers=h)
    assert r.status_code == 201
    dup_id = r.json()["EmployeeID"]

    # editing an existing record never counts itself as a duplicate
    r = client.post("/api/employees/check-duplicates", json={"EmFirstName": "Unique", "EmLastName": "Person-Zz", "exclude_id": dup_id}, headers=h)
    assert r.json()["matches"] == []


def test_employee_validation(client, admin_headers):
    h = admin_headers
    cases = [
        {"EmFirstName": "", "EmLastName": "X"},
        {"EmFirstName": "   ", "EmLastName": "X"},
        {"EmFirstName": "A", "EmLastName": "B", "EmEmail": "not-an-email"},
        {"EmFirstName": "A", "EmLastName": "B", "YearsInTrade": -3},
        {"EmFirstName": "A", "EmLastName": "B", "BaseSalary": -1},
        {"EmFirstName": "A", "EmLastName": "B", "EmMobilePhone": "12"},
        {"EmFirstName": "A", "EmLastName": "B", "EmState": "Massachusetts"},
        {"EmFirstName": "A", "EmLastName": "B", "EmDOB": "2099-01-01"},
    ]
    for body in cases:
        r = client.post("/api/employees", json=body, headers=h)
        assert r.status_code == 422, (body, r.status_code, r.text)

    r = client.post("/api/employees", json={"EmFirstName": "A", "EmLastName": "Badtrade", "EmTradeID": 987654}, headers=h)
    assert r.status_code == 422 and "Unknown trade" in r.json()["detail"]


def test_employee_update_rules(client, admin_headers):
    h = admin_headers
    r = client.post("/api/employees", json={"EmFirstName": "Upd", "EmLastName": "Rulecheck", "YearsInTrade": 4, "EmEmail": "upd@example.com"}, headers=h)
    eid = r.json()["EmployeeID"]
    assert client.put(f"/api/employees/{eid}", json={"EmFirstName": ""}, headers=h).status_code == 422
    assert client.put(f"/api/employees/{eid}", json={"EmFirstName": None}, headers=h).status_code == 422
    assert client.put(f"/api/employees/{eid}", json={"EmTradeID": 987654}, headers=h).status_code == 422
    assert client.put(f"/api/employees/{eid}", json={"NotAField": 1}, headers=h).status_code == 422
    r = client.put(f"/api/employees/{eid}", json={"YearsInTrade": 6}, headers=h)
    assert r.status_code == 200
    got = client.get(f"/api/employees/{eid}", headers=h).json()
    assert got["YearsInTrade"] == 6 and got["EmEmail"] == "upd@example.com"  # partial update keeps other fields


# ---------------------------------------------------------------- customers
def test_customer_duplicate_and_validation(client, admin_headers):
    h = admin_headers
    r = client.post("/api/customers", json={"CustBusName": "Harborline Mechanical, Inc.", "Phone": "617-555-0177", "CustWebSiteHLink": "https://www.harborline-mech.example"}, headers=h)
    assert r.status_code == 201, r.text
    cid = r.json()["CustomerID"]

    for body in ({"CustBusName": "harborline mechanical"}, {"CustBusName": "HL Mech", "Phone": "(617) 555-0177"},
                 {"CustBusName": "Another Name", "CustWebSiteHLink": "harborline-mech.example/contact"}):
        r = client.post("/api/customers", json=body, headers=h)
        assert r.status_code == 409, (body, r.text)
        assert r.json()["detail"]["matches"][0]["id"] == cid

    r = client.post("/api/customers", json={"CustBusName": "harborline mechanical", "allow_duplicate": True}, headers=h)
    assert r.status_code == 201

    assert client.post("/api/customers", json={"CustBusName": "  "}, headers=h).status_code == 422
    assert client.post("/api/customers", json={"CustBusName": "Okay Co", "CustEmail": "bad@"}, headers=h).status_code == 422
    assert client.post("/api/customers", json={"CustBusName": "Okay Co", "CustomerTypeID": 999999}, headers=h).status_code == 422

    r = client.put(f"/api/customers/{cid}", json={"CreditLimit": 25000, "OnHold": True}, headers=h)
    assert r.status_code == 200
    got = client.get(f"/api/customers/{cid}", headers=h).json()
    assert got["CreditLimit"] == 25000 and got["OnHold"] is True and got["Phone"] == "617-555-0177"
    assert client.put(f"/api/customers/{cid}", json={"CustBusName": ""}, headers=h).status_code == 422


def test_project_validation(client, admin_headers):
    h = admin_headers
    cust = client.get("/api/customers", params={"page_size": 1}, headers=h).json()["items"][0]["CustomerID"]
    assert client.post("/api/projects", json={"CustomerID": cust, "SiteName": " "}, headers=h).status_code == 422
    assert client.post("/api/projects", json={"CustomerID": cust, "SiteName": "X", "StartDate": "2026-05-10", "EndDate": "2026-05-01"}, headers=h).status_code == 422
    assert client.post("/api/projects", json={"CustomerID": cust, "SiteName": "X", "NumberOfEmployees": -1}, headers=h).status_code == 422
    assert client.post("/api/projects", json={"CustomerID": cust, "SiteName": "X", "ProjectWCCID": 999999}, headers=h).status_code == 422


# ---------------------------------------------------------------- search
def test_plain_search_no_match_returns_nothing(client, admin_headers):
    r = client.get("/api/employees", params={"q": "zzqxnotaname"}, headers=admin_headers).json()
    assert r["total"] == 0


def test_phone_search_any_format(client, admin_headers):
    h = admin_headers
    e = next(x for x in client.get("/api/employees", params={"page_size": 50}, headers=h).json()["items"] if x["EmMobilePhone"])
    d = digits(e["EmMobilePhone"])
    for q in (d, e["EmMobilePhone"], f"{d[:3]}-{d[3:6]}-{d[6:]}", d[-7:]):
        r = client.get("/api/employees", params={"q": q, "page_size": 200}, headers=h).json()
        ids = [x["EmployeeID"] for x in r["items"]]
        assert e["EmployeeID"] in ids, q
        assert r["total"] < 20, (q, r["total"])  # specific, not "everything"


def test_trade_and_location_filters(client, admin_headers):
    h = admin_headers
    lk = _lookups(client, h)
    elec = _trade(lk, "Electrician")
    r = client.get("/api/employees", params={"trade_id": elec, "state": "ma", "page_size": 200}, headers=h).json()
    assert all(i["trade_name"] == "Electrician" and i["EmState"] == "MA" for i in r["items"])
    r = client.get("/api/employees", params={"city": "boston", "page_size": 200}, headers=h).json()
    assert r["total"] > 0 and all(i["EmCity"] == "Boston" for i in r["items"])


def test_ai_parser_plural_trades():
    v = {"cities": ["Providence", "Boston"], "industries": [], "salesmen": [], "customers": []}
    i = heuristic_interpret("employees", "pipe fitters in Providence", v)
    assert i.filters == {"city": "Providence", "trade": "Pipefitter"} and i.keywords == []
    assert heuristic_interpret("employees", "sheet metal workers", v).filters["trade"] == "Sheet Metal Worker"
    assert heuristic_interpret("employees", "electricians", v).filters["trade"] == "Electrician"


def test_ai_search_trade_city(client, admin_headers):
    r = client.post("/api/search", json={"entity": "employees", "query": "electricians in Boston"}, headers=admin_headers).json()
    assert r["ai"]["filters"]["trade"] == "Electrician" and r["ai"]["filters"]["city"] == "Boston"
    assert all(i["EmCity"] == "Boston" for i in r["items"])
