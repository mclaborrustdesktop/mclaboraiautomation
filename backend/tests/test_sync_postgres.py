"""The complete one-way synchronization against the real thing on the cloud side: the agent pushes a synthetic
production-shape source through the website's ingest API (sync key) into a PostgreSQL 16 mirror, and the website
(STAGING, search-only, Cloudflare roles) serves it: searches work, every Add/Edit/Delete is refused even for an
administrator, the "last updated" status is shown, a deletion in the office arrives on the next run."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from test_postgres import pg  # noqa: F401 - the bundled PostgreSQL fixture

BACKEND = Path(__file__).resolve().parent.parent

_SCENARIO = r"""
import json, os, sys
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from app.main import app
from app import models as m, webauth, syncagent, synthdb
from app.config import settings
from app.database import SessionLocal

out = {"search_only": settings.search_only, "sync_enabled": settings.sync_enabled, "writes_allowed": settings.writes_allowed}
src_path = os.environ["SYNC_TEST_SOURCE"]
src_url = f"sqlite:///{src_path}"
synthdb.build(src_url, scale=0.01, quiet=True)
key = os.environ["SYNC_API_KEY"]
with TestClient(app) as c:
    out["bootstrap_no_key"] = c.post("/api/sync/bootstrap").status_code
    out["bootstrap_wrong_key"] = c.post("/api/sync/bootstrap", headers={"X-Sync-Key": "x" * 40}).status_code
    target = syncagent.ApiTarget("http://testserver", key, client=c)
    out["tables"] = len(target.bootstrap())
    state = syncagent.State(os.environ["SYNC_TEST_STATE"])
    source = syncagent.Source(src_url)
    rep = syncagent.run(source, target, state)
    out["run1"] = {k: v for k, v in rep.items() if k != "per_table"}
    n_emp = rep["per_table"]["tblEmployee"]["source_rows"]
    # an unapproved column is refused by the cloud itself, whatever an agent sends
    run_id = target.begin_run("incremental", "test")
    r = c.post(f"/api/sync/runs/{run_id}/upsert", headers={"X-Sync-Key": key}, json={"table": "tblEmployee", "rows": [{"EmployeeID": 1, "SSNum": "x"}]})
    out["ssn_refused"] = (r.status_code, r.json()["detail"][:60])
    r = c.post(f"/api/sync/runs/{run_id}/upsert", headers={"X-Sync-Key": key}, json={"table": "tblEmployeeAdvances", "rows": [{"EmployeeAdvanceID": 1}]})
    out["table_refused"] = r.status_code
    target.finish_run(run_id, "failed", error="test")
    out["finished_twice"] = c.post(f"/api/sync/runs/{run_id}/finish", headers={"X-Sync-Key": key}, json={"status": "success"}).status_code
    # the website on the mirror
    with SessionLocal() as s:
        staff = s.execute(text('SELECT "OfficeStaffID" FROM "tblOfficeStaff" WHERE "Initials" = \'ARI\'')).scalar_one()
        cols = {c_["name"] for c_ in inspect(s.get_bind()).get_columns("tblEmployee")}
        out["mirror_has_no_sensitive_columns"] = not ({"SSNum", "EmDOB", "BankAccountNumber", "USCitizen"} & cols)
        n_visible = s.execute(text('SELECT count(*) FROM "tblEmployee" WHERE "EmployeeDuplicate" IS NOT TRUE')).scalar_one()  # the list hides workers the office flagged as duplicates
    webauth.set_password(staff, "Synthetic-Staging-Pass-1")
    r = c.post("/api/auth/login", json={"username": "ARI", "password": "Synthetic-Staging-Pass-1"})
    out["login"] = r.status_code
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = r.json()["user"]
    out["me"] = (me["Profile"], me["search_only"], me["web_access"])
    look = c.get("/api/lookups", headers=h).json()
    out["site_mode"] = look["site_mode"]
    out["employees_total"] = c.get("/api/employees?page_size=1", headers=h).json()["total"] == n_visible
    emp1 = c.get("/api/employees?page_size=1", headers=h).json()["items"][0]
    out["record"] = c.get(f"/api/employees/{emp1['EmployeeID']}", headers=h).status_code
    out["kw_search"] = c.get(f"/api/employees?q={emp1['EmLastName'].lower()}", headers=h).json()["total"] >= 1
    ai = c.post("/api/search", json={"entity": "employees", "query": f"{look['trades'][0]['label'].lower()}s in {look['cities'][0]['label']}"}, headers=h).json()
    out["ai_search"] = ai["total"] >= 1 and ai["ai"]["filters"].get("city") == look["cities"][0]["label"]
    out["customers"] = c.get("/api/customers?page_size=5", headers=h).json()["total"] >= 1000
    out["tracking_board"] = c.get("/api/tracking?page_size=5", headers=h).status_code
    out["dashboard"] = c.get("/api/dashboard", headers=h).status_code
    # search-only: every write refused, administrator included, at the API level
    out["writes"] = [c.post("/api/employees", json={"EmFirstName": "a", "EmLastName": "b"}, headers=h).status_code,
                     c.put(f"/api/employees/{emp1['EmployeeID']}", json={"EmZip": "1"}, headers=h).status_code,
                     c.delete(f"/api/employees/{emp1['EmployeeID']}", headers=h).status_code,
                     c.post(f"/api/employees/{emp1['EmployeeID']}/notes", json={"EmployeeNote": "x"}, headers=h).status_code,
                     c.post("/api/tracking", json={"EmployeeID": 1, "ProjectID": 1, "CustomerID": 1, "WeekEndingDate": "2026-12-04"}, headers=h).status_code,
                     c.post("/api/customers", json={"CustBusName": "x"}, headers=h).status_code]
    out["edit_features_hidden"] = all(not f.endswith(".edit") for f in me["features"])
    # user management (the website's own store) still works for the administrator
    other = c.get("/api/users?active=true&page_size=50", headers=h).json()["items"][1]
    out["grant_access"] = c.put(f"/api/users/{other['OfficeStaffID']}/web-access", json={"role": "user"}, headers=h).status_code
    st = c.get("/api/sync/status", headers=h).json()
    out["status"] = (st["applies"], st["level"], st["stale"], st["search_only"])
    out["runs_admin"] = c.get("/api/sync/runs", headers=h).json()["counts"]["tblEmployee"] == n_emp
    # the office deletes a worker and changes a customer; the next run carries both
    e = create_engine(src_url, future=True)
    with e.begin() as cx:
        cx.execute(text('DELETE FROM "tblEmployeeNotes" WHERE "EmployeeID" = :i'), {"i": emp1["EmployeeID"]})
        cx.execute(text('DELETE FROM "tblEmployeeLicenses" WHERE "EmployeeID" = :i'), {"i": emp1["EmployeeID"]})
        cx.execute(text('DELETE FROM "tblTracking" WHERE "EmployeeID" = :i'), {"i": emp1["EmployeeID"]})
        cx.execute(text('DELETE FROM "tblEmployeeB" WHERE "EmployeeID" = :i'), {"i": emp1["EmployeeID"]})
        cx.execute(text('DELETE FROM "tblEmployee" WHERE "EmployeeID" = :i'), {"i": emp1["EmployeeID"]})
        cx.execute(text('UPDATE "tblCustomer" SET "CustBusName" = \'Renamed By Office 1\' WHERE "CustomerID" = 1'))
    e.dispose()
    rep2 = syncagent.run(source, target, state)
    out["run2"] = (rep2["mode"], rep2["per_table"]["tblEmployee"]["to_delete"], rep2["per_table"]["tblCustomer"]["upserted"], rep2["deleted"] >= 2)
    out["gone"] = c.get(f"/api/employees/{emp1['EmployeeID']}", headers=h).status_code
    out["renamed"] = c.get("/api/customers/1", headers=h).json()["CustBusName"]
    out["total_after"] = c.get("/api/employees?page_size=1", headers=h).json()["total"] == n_visible - 1
    source.close(); state.close()
print(json.dumps(out, default=str))
"""


def test_agent_feeds_the_search_only_website_through_the_api(pg, tmp_path):  # noqa: F811
    env = {**os.environ, "DATA_SOURCE": "staging", "STAGING_DATABASE_URL": pg, "WEB_AUTH_DATABASE_URL": pg, "JWT_SECRET": "postgres-sync-secret-not-the-demo-value",
           "WEB_ADMINS": "ARI", "ACCESS_MODE": "login", "ANTHROPIC_API_KEY": "", "MCLABOR_ENV_FILE": "none", "SEED_ON_STARTUP": "false",
           "SYNC_API_KEY": "s" * 48, "SYNC_TEST_SOURCE": (tmp_path / "source.db").as_posix(), "SYNC_TEST_STATE": (tmp_path / "state.db").as_posix()}
    for k in ("DATABASE_URL", "STAGING_DB_SERVER", "DB_SHAPE", "SITE_MODE"):
        env.pop(k, None)
    script = tmp_path / "sync_scenario.py"
    script.write_text(_SCENARIO, encoding="utf-8")
    p = subprocess.run([sys.executable, str(script)], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr[-3000:]
    out = json.loads(p.stdout.strip().splitlines()[-1])
    print("SCENARIO", json.dumps(out, default=str))
    assert out["search_only"] is True and out["sync_enabled"] is True and out["writes_allowed"] is False
    assert out["bootstrap_no_key"] == 401 and out["bootstrap_wrong_key"] == 401 and out["tables"] == 33
    assert out["run1"]["mode"] == "full" and out["run1"]["tables"] == 33 and out["run1"]["deleted"] == 0 and out["run1"]["upserted"] >= 5000
    assert out["ssn_refused"][0] == 422 and "not approved" in out["ssn_refused"][1] and out["table_refused"] == 422 and out["finished_twice"] == 409
    assert out["mirror_has_no_sensitive_columns"] and out["login"] == 200 and out["me"] == [True, True, "admin"] and out["site_mode"] == "search-only"
    assert out["employees_total"] and out["record"] == 200 and out["kw_search"] and out["ai_search"] and out["customers"] and out["tracking_board"] == 200 and out["dashboard"] == 200
    assert out["writes"] == [423] * 6 and out["edit_features_hidden"] and out["grant_access"] == 200
    assert out["status"] == [True, "fresh", False, True] and out["runs_admin"]
    assert out["run2"][0] == "incremental" and out["run2"][1] == 1 and out["run2"][2] == 1 and out["run2"][3]
    assert out["gone"] == 404 and out["renamed"] == "Renamed By Office 1" and out["total_after"]
