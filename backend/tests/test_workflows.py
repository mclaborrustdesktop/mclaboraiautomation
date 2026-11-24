"""End-to-end office workflows through the API, the way the Access screens are used day to day (synthetic data)."""
from __future__ import annotations

from datetime import date, timedelta

from app.seed import week_ending


def test_new_customer_job_worker_week_hours_and_history(client, admin_headers):
    h = admin_headers
    look = client.get("/api/lookups", headers=h).json()
    city = next(c for c in look["cities"] if c["label"] == "Worcester")
    trade = next(t for t in look["trades"] if t["label"] == "Electrician")
    status_active = next(s for s in look["customer_statuses"] if s["label"] == "Active")

    # 1. a new customer, with one contact; the duplicate check runs while typing
    assert client.post("/api/customers/check-duplicates", json={"CustBusName": "Blackstone Valley Electric Co"}, headers=h).json()["matches"] == []
    r = client.post("/api/customers", json={"CustBusName": "Blackstone Valley Electric Co", "StateCityID": city["id"], "Phone": "(508) 555-0142",
                                            "CustStatusID": status_active["id"], "contacts": [{"CustomerContactFName": "Dana", "CustomerContactLName": "Reyes", "CustomerContactEmail": "dana@example.com"}]}, headers=h)
    assert r.status_code == 201, r.text
    cust = r.json()
    assert cust["City"] == "Worcester" and cust["State"] == "MA" and cust["contacts"][0]["CustomerContactLName"] == "Reyes"
    # the same company typed again is caught, and can be confirmed on purpose
    r = client.post("/api/customers", json={"CustBusName": "Blackstone Valley Electric Company", "Phone": "508-555-0142"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["matches"][0]["id"] == cust["CustomerID"]

    # 2. a job for that customer
    r = client.post("/api/projects", json={"CustomerID": cust["CustomerID"], "SiteName": "Main St substation", "SiteStateCityID": city["id"], "StartDate": date.today().isoformat(),
                                           "NumberOfEmployees": 3, "ProjStatusID": next(s["id"] for s in look["project_statuses"] if s["label"] == "Active")}, headers=h)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["customer_name"] == "Blackstone Valley Electric Co" and job["SiteCity"] == "Worcester"

    # 3. a worker: the duplicate warning, then a confirmed create
    r = client.post("/api/employees", json={"EmFirstName": "Luis", "EmLastName": "Ferreira", "EmMobilePhone": "(508) 555-0177", "EmTradeID": trade["id"], "EmStateCityID": city["id"], "YearsInTrade": 7, "BaseSalary": 38}, headers=h)
    assert r.status_code == 201, r.text
    worker = r.json()
    r = client.post("/api/employees", json={"EmFirstName": "Luis", "EmLastName": "Ferreira", "EmMobilePhone": "508 555 0177"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["matches"][0]["reasons"]
    r = client.post("/api/employees", json={"EmFirstName": "Luis", "EmLastName": "Ferreira", "EmMobilePhone": "508 555 0177", "allow_duplicate": True}, headers=h)
    assert r.status_code == 201
    twin = r.json()

    # 4. the worker is found by the searches the office uses
    found = client.get("/api/employees?q=ferreira", headers=h).json()
    assert {x["EmployeeID"] for x in found["items"]} >= {worker["EmployeeID"], twin["EmployeeID"]}
    ai = client.post("/api/search", json={"entity": "employees", "query": "electricians in Worcester with 5+ years"}, headers=h).json()
    assert any(x["EmployeeID"] == worker["EmployeeID"] for x in ai["items"]) and ai["ai"]["filters"]["city"] == "Worcester"
    assert any(x["ProjectID"] == job["ProjectID"] for x in client.get("/api/projects?q=substation", headers=h).json()["items"])

    # 5. assign the worker to the job for a week, then enter the hours; the week's totals follow
    we = week_ending(date.today() + timedelta(weeks=20))
    r = client.post("/api/tracking", json={"EmployeeID": worker["EmployeeID"], "ProjectID": job["ProjectID"], "CustomerID": cust["CustomerID"], "WeekEndingDate": we.isoformat(), "PayRate": 38, "BillRate": 57}, headers=h)
    assert r.status_code == 201, r.text
    week = r.json()
    r = client.put(f"/api/tracking/{week['TrackingID']}", json={"MonHours": 8, "TueHours": 8, "WedHours": 8, "ThuHours": 8, "FriHours": 8, "SatHours": 4, "expected_version": week["version"]}, headers=h)
    assert r.status_code == 200, r.text
    week = r.json()
    assert week["TotalHours"] == 44 and week["OvertimeHours"] == 4 and week["InvoiceAmount"] == 40 * 57 + 4 * 57 * 1.5
    board = client.get(f"/api/tracking?week_ending_date={we.isoformat()}", headers=h).json()
    assert any(x["TrackingID"] == week["TrackingID"] and x["site_name"] == "Main St substation" for x in board["items"])
    bulk = client.post("/api/tracking/bulk", json={"ProjectID": job["ProjectID"], "EmployeeIDs": [worker["EmployeeID"], twin["EmployeeID"]], "WeekEndingDate": (we + timedelta(weeks=1)).isoformat()}, headers=h).json()
    assert len(bulk["created"]) == 2 and bulk["created"][0]["PayRate"] == 38  # the worker's base rate

    # 6. the record pages show who did what
    hist = client.get(f"/api/audit/employees/{worker['EmployeeID']}", headers=h).json()["items"]
    created = next(x for x in hist if x["action"] == "employee.create")  # newest first; SQLite may re-use an id of an earlier test's deleted row
    assert created["initials"] == "ADMIN" and created["changes"]["EmLastName"]["to"] == "Ferreira"
    assert client.get(f"/api/audit/tracking/{week['TrackingID']}", headers=h).json()["items"][0]["changes"]["TotalHours"] == {"from": 0.0, "to": 44.0}
    assert client.get(f"/api/audit/customers/{cust['CustomerID']}", headers=h).json()["items"][0]["action"] == "customer.create"

    # 7. the job's page lists the assignments; the customer's page lists the job; the worker's page the week
    assert any(a["TrackingID"] == week["TrackingID"] for a in client.get(f"/api/projects/{job['ProjectID']}", headers=h).json()["assignments"])
    assert any(p["ProjectID"] == job["ProjectID"] for p in client.get(f"/api/customers/{cust['CustomerID']}", headers=h).json()["projects"])
    assert any(a["TrackingID"] == week["TrackingID"] for a in client.get(f"/api/employees/{worker['EmployeeID']}", headers=h).json()["recent_assignments"])

    # 8. a record with history is not deleted but deactivated; the week with hours needs delete rights (the admin has them)
    r = client.delete(f"/api/employees/{worker['EmployeeID']}", headers=h)
    assert r.status_code == 409 and "Inactive" in r.json()["detail"]
    inactive = next(s["id"] for s in look["employee_statuses"] if s["label"] == "Inactive")
    assert client.put(f"/api/employees/{worker['EmployeeID']}", json={"EmEmployeeStatusID": inactive}, headers=h).json()["status_name"] == "Inactive"
    assert client.delete(f"/api/tracking/{week['TrackingID']}", headers=h).status_code == 204
    assert client.get(f"/api/audit/tracking/{week['TrackingID']}", headers=h).json()["items"][0]["action"] == "tracking.delete"
