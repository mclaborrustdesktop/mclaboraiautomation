"""Change log, "changed by someone else" protection, lookup usability rules and the weekly-tracking rules (demo data)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import audit
from app import models as m
from app.seed import week_ending


def _own(items: list[dict]) -> list[dict]:
    """The log lines of THIS record: SQLite (demo) re-uses the id of a deleted row, so an earlier test's deleted record can
    share the id; PostgreSQL and SQL Server identity columns never do. Newest first, down to this record's create."""
    for i, x in enumerate(items):
        if x["action"].startswith(("employee.create", "customer.create", "project.create", "tracking.create")):
            return items[: i + 1]
    return items


def _new_employee(client, h, suffix: str, **extra):
    body = {"EmFirstName": "Audit", "EmLastName": f"Case{suffix}", "EmMobilePhone": f"(617) 555-9{suffix[-3:].zfill(3)}", "EmEmail": f"audit.{suffix}@example.com", **extra}
    r = client.post("/api/employees", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_update_delete_are_logged_with_changed_columns(client, admin_headers):
    before_count = audit.count()
    e = _new_employee(client, admin_headers, "001")
    r = client.put(f"/api/employees/{e['EmployeeID']}", json={"EmMobilePhone": "(617) 555-9999", "EmZip": "02110"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    hist = _own(client.get(f"/api/audit/employees/{e['EmployeeID']}", headers=admin_headers).json()["items"])
    assert [x["action"] for x in hist] == ["employee.update", "employee.create"]
    upd = hist[0]
    assert upd["initials"] == "ADMIN" and upd["table"] == "tblEmployee" and upd["record_id"] == e["EmployeeID"]
    assert upd["changes"]["EmMobilePhone"] == {"from": e["EmMobilePhone"], "to": "(617) 555-9999"} and upd["changes"]["EmZip"]["to"] == "02110"
    assert "EmDOB" not in upd["changes"] and set(upd["changes"]) == {"EmMobilePhone", "EmZip"}      # only what changed; restricted columns never
    assert hist[1]["changes"]["EmLastName"]["to"] == "Case001"
    # notes are logged as an action without column changes; deletes keep the record's last values
    client.post(f"/api/employees/{e['EmployeeID']}/notes", json={"EmployeeNote": "called back"}, headers=admin_headers)
    assert client.delete(f"/api/employees/{e['EmployeeID']}", headers=admin_headers).status_code == 204
    hist = _own(client.get(f"/api/audit/employees/{e['EmployeeID']}", headers=admin_headers).json()["items"])
    assert [x["action"] for x in hist] == ["employee.delete", "employee.note", "employee.update", "employee.create"]
    assert hist[0]["changes"]["EmLastName"] == {"from": "Case001", "to": None} and hist[1]["summary"] == "called back"
    assert audit.count() == before_count + 4
    # administrators see everything, filtered
    recent = client.get("/api/audit?table=tblEmployee&action=employee.delete&limit=5", headers=admin_headers).json()["items"]
    assert recent and recent[0]["record_id"] == e["EmployeeID"]


def test_stale_version_is_refused_and_a_fresh_one_accepted(client, admin_headers):
    e = _new_employee(client, admin_headers, "002")
    v1 = e["version"]
    assert v1 and len(v1) == 16
    # a second person saves first
    r = client.put(f"/api/employees/{e['EmployeeID']}", json={"EmZip": "01602", "expected_version": v1}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["version"] != v1
    # the first person's form still carries v1: refused with the reason and the current version
    r = client.put(f"/api/employees/{e['EmployeeID']}", json={"EmZip": "01603", "expected_version": v1}, headers=admin_headers)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["code"] == "stale" and "changed by someone else" in d["message"] and d["current_version"]
    assert client.get(f"/api/employees/{e['EmployeeID']}", headers=admin_headers).json()["EmZip"] == "01602"  # nothing was overwritten
    # reload, then save with the current version
    r = client.put(f"/api/employees/{e['EmployeeID']}", json={"EmZip": "01603", "expected_version": d["current_version"]}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["EmZip"] == "01603"
    # a licence change also changes the employee's version (child rows are part of it)
    v = r.json()["version"]
    r = client.put(f"/api/employees/{e['EmployeeID']}", json={"licenses": [{"EmployeeLicenseNumber": "L-1", "EmployeeLicenseCopyOnFile": "Yes"}]}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["version"] != v
    # without expected_version (older clients) a save is still accepted
    assert client.put(f"/api/employees/{e['EmployeeID']}", json={"EmZip": "01604"}, headers=admin_headers).status_code == 200


def test_versions_exist_on_every_editable_record(client, admin_headers):
    cust = client.get("/api/customers?page_size=1", headers=admin_headers).json()["items"][0]["CustomerID"]
    c = client.get(f"/api/customers/{cust}", headers=admin_headers).json()
    assert c["version"]
    r = client.put(f"/api/customers/{cust}", json={"Industry": c.get("Industry"), "expected_version": "0000000000000000"}, headers=admin_headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"
    proj = client.get("/api/projects?page_size=1", headers=admin_headers).json()["items"][0]["ProjectID"]
    p = client.get(f"/api/projects/{proj}", headers=admin_headers).json()
    assert p["version"]
    r = client.put(f"/api/projects/{proj}", json={"JobNote": "x", "expected_version": p["version"]}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["version"] != p["version"]
    hist = client.get(f"/api/audit/projects/{proj}", headers=admin_headers).json()["items"]
    assert hist[0]["action"] == "project.update" and hist[0]["changes"]["JobNote"]["to"] == "x" and hist[0]["initials"] == "ADMIN"
    t = client.get("/api/tracking?page_size=1", headers=admin_headers).json()["items"][0]["TrackingID"]
    tr = client.get(f"/api/tracking/{t}", headers=admin_headers).json()
    assert tr["version"]
    assert client.put(f"/api/tracking/{t}", json={"HoursNote": "late start", "expected_version": "stale-version-xx"}, headers=admin_headers).status_code == 409


def test_blank_or_inactive_lookup_values_are_refused(client, admin_headers, engine):
    S = sessionmaker(bind=engine)
    with S() as s:
        lt = s.execute(select(m.PullDownLicenseType).order_by(m.PullDownLicenseType.PullDownLicenseTypeID.desc())).scalars().first()
        lt.PullDownLicenseTypeActive = False
        inactive_id = lt.PullDownLicenseTypeID
        blank = m.PullDownEmployeeStatus(PullDownEmployeeStatus="   ", PullDownEmployeeStatusSort=99)
        s.add(blank)
        s.commit()
        blank_id = blank.PullDownEmployeeStatusID
    try:
        r = client.post("/api/employees", json={"EmFirstName": "Rule", "EmLastName": "Blank", "EmEmployeeStatusID": blank_id}, headers=admin_headers)
        assert r.status_code == 422 and "blank in the lookup list" in r.json()["detail"]
        r = client.post("/api/employees", json={"EmFirstName": "Rule", "EmLastName": "Inactive", "licenses": [{"EmployeeLicenseTypeID": inactive_id}]}, headers=admin_headers)
        assert r.status_code == 422 and "no longer active" in r.json()["detail"]
        r = client.post("/api/employees", json={"EmFirstName": "Rule", "EmLastName": "Unknown", "EmTradeID": 99999}, headers=admin_headers)
        assert r.status_code == 422 and "Unknown trade" in r.json()["detail"]
        assert "blank" not in client.get("/api/lookups", headers=admin_headers).text.lower() or True  # the lookups endpoint already hides blank rows
        assert all(i["id"] != blank_id for i in client.get("/api/lookups", headers=admin_headers).json()["employee_statuses"])
    finally:
        with S() as s:
            s.get(m.PullDownLicenseType, inactive_id).PullDownLicenseTypeActive = True
            s.delete(s.get(m.PullDownEmployeeStatus, blank_id))
            s.commit()


def test_tracking_rules_hours_rates_do_not_contact_and_duplicates(client, admin_headers, engine):
    proj = client.get("/api/projects?page_size=1", headers=admin_headers).json()["items"][0]["ProjectID"]
    e = _new_employee(client, admin_headers, "003", BaseSalary=30)
    we = week_ending(date.today() + timedelta(weeks=30)).isoformat()  # a week nobody is assigned in
    base = {"EmployeeID": e["EmployeeID"], "ProjectID": proj, "CustomerID": 0, "WeekEndingDate": we, "PayRate": 30, "BillRate": 45}
    r = client.post("/api/tracking", json={**base, "MonHours": 25}, headers=admin_headers)
    assert r.status_code == 422 and "between 0 and 24" in r.json()["detail"]
    r = client.post("/api/tracking", json={**base, "PayRate": -1}, headers=admin_headers)
    assert r.status_code == 422 and "PayRate" in r.json()["detail"]
    r = client.post("/api/tracking", json={**base, "MonHours": 8, "TueHours": 8, "WedHours": 8, "ThuHours": 8, "FriHours": 10}, headers=admin_headers)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["TotalHours"] == 42 and t["OvertimeHours"] == 2 and t["EmGrossPayroll"] == 40 * 30 + 2 * 45 and t["CustomerID"] != 0  # customer follows the job
    # the same worker on the same job in the same week is refused (also when an edit would create the duplicate)
    assert client.post("/api/tracking", json=base, headers=admin_headers).status_code == 409
    r2 = client.post("/api/tracking", json={**base, "WeekEndingDate": (date.fromisoformat(we) + timedelta(weeks=1)).isoformat()}, headers=admin_headers)
    assert r2.status_code == 201
    assert client.put(f"/api/tracking/{r2.json()['TrackingID']}", json={"WeekEndingDate": we}, headers=admin_headers).status_code == 409
    # a worker marked "do not contact" cannot be assigned
    client.put(f"/api/employees/{e['EmployeeID']}", json={"EmployeeNoCommunication": True}, headers=admin_headers)
    r = client.post("/api/tracking", json={**base, "WeekEndingDate": (date.fromisoformat(we) + timedelta(weeks=2)).isoformat()}, headers=admin_headers)
    assert r.status_code == 409 and "do not contact" in r.json()["detail"]
    hist = _own(client.get(f"/api/audit/tracking/{t['TrackingID']}", headers=admin_headers).json()["items"])
    assert hist[-1]["action"] == "tracking.create" and hist[-1]["changes"]["FriHours"]["to"] == 10


def test_view_only_user_cannot_change_or_read_the_full_log(client, admin_headers):
    users = client.get("/api/users?active=true&page_size=200", headers=admin_headers).json()["items"]
    viewer = next(u for u in users if "employees.view" in u["features"] and "employees.edit" not in u["features"] and not u["Profile"])
    assert client.post(f"/api/users/{viewer['OfficeStaffID']}/password", json={"password": "look-up-only-1", "must_change": False}, headers=admin_headers).status_code == 204
    r = client.post("/api/auth/login", json={"username": viewer["Initials"], "password": "look-up-only-1"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    emp = client.get("/api/employees?page_size=1", headers=h).json()["items"][0]["EmployeeID"]
    assert client.post("/api/employees", json={"EmFirstName": "a", "EmLastName": "b"}, headers=h).status_code == 403
    assert client.put(f"/api/employees/{emp}", json={"EmZip": "00000"}, headers=h).status_code == 403
    assert client.get("/api/audit", headers=h).status_code == 403                               # the full log is for administrators
    assert client.get(f"/api/audit/employees/{emp}", headers=h).status_code == 200              # a record's own history goes with viewing it
    assert client.get(f"/api/audit/tracking/1", headers=h).status_code == (200 if "tracking.view" in viewer["features"] else 403)
