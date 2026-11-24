"""The PostgreSQL adapter, end to end, on a real PostgreSQL 16 started by the ``pgserver`` package (a PostgreSQL bundled
in a pip wheel, run as a plain user process under the test's temporary folder: nothing is installed on the PC).

Steps: generate the schema from the SQL Server export and apply it (288 tables) -> fill the 33 website tables with
synthetic rows in the production shape -> start the website in a subprocess as STAGING on that database (so settings,
models and the web store load for PostgreSQL) -> create, search, update, relationships, transactions, concurrency,
derived-field mapping, audit log, health. Skipped when pgserver cannot start (then run it where it can).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, inspect, text

from app import pgschema, synthdb

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    try:
        import pgserver
    except ImportError:  # pragma: no cover
        pytest.skip("pgserver not installed")
    import logging

    lg = logging.getLogger("pgserver")  # its shutdown hook logs after pytest closed the capture stream: keep it quiet
    lg.handlers, lg.propagate = [logging.NullHandler()], False
    root = tmp_path_factory.mktemp("pg")
    try:
        server = pgserver.get_server(str(root / "data"))
    except Exception as exc:  # noqa: BLE001 - a PC where the bundled server cannot start
        pytest.skip(f"PostgreSQL could not be started here: {type(exc).__name__}")
    base = server.get_uri()
    with psycopg.connect(base, autocommit=True) as c:
        c.execute("CREATE DATABASE mclabor_test")
    url = base.rsplit("/", 1)[0] + "/mclabor_test"
    yield url.replace("postgresql://", "postgresql+psycopg://", 1)
    server.cleanup()


@pytest.fixture(scope="module")
def built(pg):
    pgschema.apply(pg, indexes=True, constraints=True, quiet=True)
    counts = synthdb.build(pg, scale=0.01, quiet=True, fill_existing=True)
    return counts


def test_schema_applies_with_tables_keys_and_indexes(pg, built):
    engine = create_engine(pg, future=True)
    insp = inspect(engine)
    names = set(insp.get_table_names())
    assert len(names) >= 288 and {"tblEmployee", "tblEmployeeB", "tblTracking", "tblQBOpenInvoices", "tblProjectCertifiedPayroll", "WebEmployeeSearchPreset"} <= names
    fks = insp.get_foreign_keys("tblTracking")
    assert {(f["constrained_columns"][0], f["referred_table"]) for f in fks} >= {("EmployeeID", "tblEmployee"), ("ProjectID", "tblProject"), ("CustomerID", "tblCustomer")}
    cols = {c["name"]: c for c in insp.get_columns("tblEmployee")}
    assert "YearsInTradeID" in cols and "YearsInTrade" not in cols and cols["EmployeeID"]["identity"]
    assert {i["name"] for i in insp.get_indexes("tblTracking")} >= {"ix_tracking_week", "ux_tracking_employee_project_week"}
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM "tblEmployee"')).scalar_one() == built["tblEmployee"] >= 1789
        assert c.execute(text('SELECT count(*) FROM "tblEmployeeB"')).scalar_one() == built["tblEmployee"]
        # business rules live in the database too
        with pytest.raises(Exception, match="ck_tracking_hours"):
            c.execute(text('UPDATE "tblTracking" SET "MonHours" = 30 WHERE "TrackingID" = 1'))
        c.rollback()
        # identity sequences continue after the copied ids
        new_id = c.execute(text('INSERT INTO "tblPullDownGrades" DEFAULT VALUES RETURNING "PullDownGradeID"')).scalar_one() if "tblPullDownGrades" in names else 1
        c.rollback()
        assert new_id >= 1
    engine.dispose()


_SCENARIO = r"""
import json, os, sys, threading
sys.path.insert(0, os.getcwd())
from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from app.main import app
from app import models as m, webauth, audit
from app.config import settings
from app.database import SessionLocal
from app.seed import week_ending

out = {"env": settings.environment, "backend": settings.db_backend, "shape": "production" if settings.production_shape else "demo", "writes": settings.writes_allowed}
with SessionLocal() as s:
    staff = s.execute(select(m.OfficeStaff).where(m.OfficeStaff.Initials == "ARI")).scalar_one()
    webauth.set_password(staff.OfficeStaffID, "Synthetic-Staging-Pass-1")
with TestClient(app) as c:
    out["health"] = c.get("/api/health").json()
    out["ready"] = c.get("/api/ready").json()
    r = c.post("/api/auth/login", json={"username": "ARI", "password": "Synthetic-Staging-Pass-1"})
    out["login"] = r.status_code
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    look = c.get("/api/lookups", headers=h).json()
    out["restricted"] = look["restricted_fields"]
    city = look["cities"][0]["id"]
    # create: customer -> job -> employee with the derived fields
    r = c.post("/api/customers", json={"CustBusName": "Synthetic Harbor Electric 9001", "StateCityID": city, "Phone": "(617) 555-0001"}, headers=h)
    out["customer_create"] = r.status_code
    cust = r.json()
    r = c.post("/api/projects", json={"CustomerID": cust["CustomerID"], "SiteName": "Pier 9 switchgear", "SiteStateCityID": city, "StartDate": date.today().isoformat()}, headers=h)
    out["project_create"] = r.status_code
    job = r.json()
    out["project_city_from_lookup"] = job["SiteCity"] == look["cities"][0]["label"] and job["SiteState"] == look["cities"][0]["extra"]["state"]
    r = c.post("/api/employees", json={"EmFirstName": "Zed", "EmLastName": "Synthetico", "EmMobilePhone": "(617) 555-0002", "EmStateCityID": city, "YearsInTrade": 5, "WillTravel": "Yes",
                                       "EmTradeID": look["trades"][0]["id"], "BaseSalary": 33, "licenses": [{"EmployeeLicenseNumber": "PG-1", "EmployeeLicenseTypeID": look["license_types"][0]["id"]}]}, headers=h)
    out["employee_create"] = r.status_code
    emp = r.json() if r.status_code == 201 else {"detail": r.text}
    out["employee_derived"] = (emp.get("YearsInTrade"), emp.get("WillTravel"), len(emp.get("licenses", [])))
    r = c.post("/api/employees", json={"EmFirstName": "Bad", "EmLastName": "Years", "YearsInTrade": 4}, headers=h)  # the synthetic list has 1, 2, 3, 5, 7...
    out["years_not_in_list"] = (r.status_code, r.json()["detail"][:60])
    # search on PostgreSQL: keywords (ILIKE), filters through the lookups, facets by GROUPING SETS, AI parser
    out["kw_search"] = [x["EmployeeID"] for x in c.get("/api/employees?q=SYNTHETICO", headers=h).json()["items"]] == [emp["EmployeeID"]]
    ai = c.post("/api/search", json={"entity": "employees", "query": f"{look['trades'][0]['label'].lower()}s in {look['cities'][0]['label']} with 3+ years"}, headers=h).json()
    out["ai_search"] = (ai["total"] >= 1, sorted(f["key"] for f in ai.get("facets") or []), ai["ai"]["filters"].get("city"))
    jobs = c.get(f"/api/projects?q=switchgear&state={look['cities'][0]['extra']['state']}", headers=h).json()
    out["project_search_state"] = [p["ProjectID"] for p in jobs["items"]] == [job["ProjectID"]]
    out["customer_search"] = any(x["CustomerID"] == cust["CustomerID"] for x in c.get("/api/customers?q=harbor", headers=h).json()["items"])
    # update + stale version + audit (the audit log lives in the same PostgreSQL database)
    v = emp["version"]
    r = c.put(f"/api/employees/{emp['EmployeeID']}", json={"YearsInTrade": 10, "WillTravel": "No", "EmZip": "02110", "expected_version": v}, headers=h)
    out["employee_update"] = (r.status_code, r.json().get("YearsInTrade"), r.json().get("WillTravel"))
    out["stale_refused"] = c.put(f"/api/employees/{emp['EmployeeID']}", json={"EmZip": "02111", "expected_version": v}, headers=h).status_code
    hist = c.get(f"/api/audit/employees/{emp['EmployeeID']}", headers=h).json()["items"]
    out["audit"] = ([x["action"] for x in hist], hist[0]["changes"].get("EmZip"), hist[0]["initials"])
    with SessionLocal() as s:
        out["employeeB_row"] = s.execute(text('SELECT "WillTravel" FROM "tblEmployeeB" WHERE "EmployeeID" = :i'), {"i": emp["EmployeeID"]}).scalar_one()
        out["audit_in_postgres"] = s.execute(text("SELECT count(*) FROM web_audit_log")).scalar_one() >= 3
    # relationships: the customer page lists the job, the job page lists the week, the employee page the assignment
    we = week_ending(date.today() + timedelta(weeks=8))
    r = c.post("/api/tracking", json={"EmployeeID": emp["EmployeeID"], "ProjectID": job["ProjectID"], "CustomerID": cust["CustomerID"], "WeekEndingDate": we.isoformat(), "PayRate": 33, "BillRate": 50, "MonHours": 8, "TueHours": 9}, headers=h)
    out["tracking_create"] = (r.status_code, r.json().get("TotalHours"), r.json().get("CustomerID") == cust["CustomerID"])
    trk = r.json()
    out["rel_customer_jobs"] = any(p["ProjectID"] == job["ProjectID"] for p in c.get(f"/api/customers/{cust['CustomerID']}", headers=h).json()["projects"])
    out["rel_job_weeks"] = any(a["TrackingID"] == trk["TrackingID"] for a in c.get(f"/api/projects/{job['ProjectID']}", headers=h).json()["assignments"])
    out["rel_employee_weeks"] = any(a["TrackingID"] == trk["TrackingID"] for a in c.get(f"/api/employees/{emp['EmployeeID']}", headers=h).json()["recent_assignments"])
    out["board"] = any(x["TrackingID"] == trk["TrackingID"] for x in c.get(f"/api/tracking?week_ending_date={we.isoformat()}", headers=h).json()["items"])
    out["dashboard"] = c.get("/api/dashboard", headers=h).status_code
    # transactions: a create whose licence points at an unknown type leaves nothing behind
    with SessionLocal() as s:
        n_before = s.execute(text('SELECT count(*) FROM "tblEmployee"')).scalar_one()
    r = c.post("/api/employees", json={"EmFirstName": "Roll", "EmLastName": "Back", "licenses": [{"EmployeeLicenseTypeID": 999999}]}, headers=h)
    with SessionLocal() as s:
        out["rollback"] = (r.status_code, s.execute(text('SELECT count(*) FROM "tblEmployee"')).scalar_one() == n_before)
    # concurrency: eight people assign the same worker to the same job for the same week at once -> exactly one succeeds
    we2 = (we + timedelta(weeks=1)).isoformat()
    results = []
    def go():
        rr = c.post("/api/tracking", json={"EmployeeID": emp["EmployeeID"], "ProjectID": job["ProjectID"], "CustomerID": cust["CustomerID"], "WeekEndingDate": we2, "PayRate": 33, "BillRate": 50}, headers=h)
        results.append(rr.status_code)
    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    out["concurrent_assign"] = sorted(results)
    # concurrency: two people edit the same employee at once, each with the version they loaded; one is told to reload
    cur = c.get(f"/api/employees/{emp['EmployeeID']}", headers=h).json()["version"]
    codes = []
    def edit(zip_):
        codes.append(c.put(f"/api/employees/{emp['EmployeeID']}", json={"EmZip": zip_, "expected_version": cur}, headers=h).status_code)
    ts = [threading.Thread(target=edit, args=(z,)) for z in ("02201", "02202")]
    [t.start() for t in ts]; [t.join() for t in ts]
    out["concurrent_edit"] = sorted(codes)
    out["status_backend"] = c.get("/api/system/status", headers=h).json()["database"].get("backend")
print(json.dumps(out, default=str))
"""


def test_website_runs_on_postgres_create_search_update_relationships_transactions_concurrency(pg, built, tmp_path):
    env = {**os.environ, "DATA_SOURCE": "staging", "STAGING_DATABASE_URL": pg, "WEB_AUTH_DATABASE_URL": pg, "JWT_SECRET": "postgres-test-secret-not-the-demo-value",
           "WEB_ADMINS": "ARI", "ACCESS_MODE": "login", "ANTHROPIC_API_KEY": "", "MCLABOR_ENV_FILE": "none", "SEED_ON_STARTUP": "false", "SITE_MODE": "full"}  # the future editing release; the first release is search-only (test_sync_postgres.py)
    for k in ("DATABASE_URL", "STAGING_DB_SERVER", "DB_SHAPE"):
        env.pop(k, None)
    script = tmp_path / "pg_scenario.py"
    script.write_text(_SCENARIO, encoding="utf-8")
    p = subprocess.run([sys.executable, str(script)], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-3000:]
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["env"] == "staging" and out["backend"] == "postgres" and out["shape"] == "production" and out["writes"] is True
    assert out["health"]["database"] == "postgres" and out["ready"]["status"] == "ready" and out["login"] == 200
    assert out["restricted"] == ["EmDOB", "USCitizen", "I9Complete"]
    assert out["customer_create"] == 201 and out["project_create"] == 201 and out["project_city_from_lookup"]
    assert out["employee_create"] == 201 and out["employee_derived"] == [5, "Yes", 1]
    assert out["years_not_in_list"][0] == 422 and "Years in trade" in out["years_not_in_list"][1]
    assert out["kw_search"] and out["ai_search"][0] and out["ai_search"][1] and out["project_search_state"] and out["customer_search"]  # facets came from one GROUPING SETS pass
    assert out["employee_update"] == [200, 10, "No"] and out["stale_refused"] == 409 and out["employeeB_row"] == "No"
    assert out["audit"][0][:2] == ["employee.update", "employee.create"] and out["audit"][1] == {"from": None, "to": "02110"} and out["audit"][2] == "ARI"
    assert out["audit_in_postgres"]
    assert out["tracking_create"] == [201, 17.0, True] and out["rel_customer_jobs"] and out["rel_job_weeks"] and out["rel_employee_weeks"] and out["board"]
    assert out["dashboard"] == 200
    assert out["rollback"] == [422, True]
    assert out["concurrent_assign"] == [201] + [409] * 7, out["concurrent_assign"]
    assert out["concurrent_edit"] == [200, 409]
    assert out["status_backend"] == "postgres"
