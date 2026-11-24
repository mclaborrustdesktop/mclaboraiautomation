"""Production SQL Server adapter: safety guards and schema mapping.

No real SQL Server is contacted.  Production-mode behaviour is exercised in a
subprocess with DATA_SOURCE=production pointed at a non-existent server, so the
test proves requests are refused *before* any connection is attempted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import production
from app.production import ProductionWriteBlocked, check_statement

BACKEND = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("sql", [
    "SELECT * FROM tblEmployee",
    "  select 1",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "/* comment */ SELECT 1",
    "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
])
def test_guard_allows_reads(sql):
    check_statement(sql, writes_allowed=False)


@pytest.mark.parametrize("sql", [
    "INSERT INTO tblEmployee (EmFirstName) VALUES (?)",
    "UPDATE tblCustomer SET OnHold = 1",
    "DELETE FROM tblTracking",
    "MERGE tblEmployee AS t USING x ON 1=1 WHEN MATCHED THEN DELETE;",
    "-- sneaky\nUPDATE tblEmployee SET EmLastName = 'x'",
])
def test_guard_blocks_writes_until_approved(sql):
    with pytest.raises(ProductionWriteBlocked):
        check_statement(sql, writes_allowed=False)
    check_statement(sql, writes_allowed=True)


@pytest.mark.parametrize("sql", ["DROP TABLE tblEmployee", "ALTER TABLE tblEmployee ADD x int", "CREATE TABLE t (id int)",
                                 "TRUNCATE TABLE tblTracking", "EXEC sp_who", "/* x */ drop table t"])
def test_guard_always_blocks_ddl(sql):
    for allowed in (False, True):
        with pytest.raises(ProductionWriteBlocked):
            check_statement(sql, writes_allowed=allowed)


def test_schema_matches_client_export():
    rep = production.validate_against_csv()
    assert rep.tables_checked >= 30 and rep.columns_checked >= 250
    assert rep.ok, rep.as_dict()
    assert {"tblEmployee.YearsInTrade", "tblEmployee.WillTravel", "tblProject.SiteCity", "tblProject.SiteState"} == {
        m.split(" ")[0] for m in rep.mapped_columns
    }


def test_system_status_admin_only(client, admin_headers):
    r = client.get("/api/system/status", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["database"]["data_source"] == "demo"
    assert body["schema_check"]["ok"] is True
    assert "password" not in json.dumps(body["database"]).lower().replace("password_set", "")


_PROD_SCRIPT = r"""
import json, os, sys
sys.path.insert(0, os.getcwd())
from fastapi.testclient import TestClient
from sqlalchemy.dialects import mssql
from sqlalchemy import select
from app.main import app
from app import models as m, production
from app.database import engine

out = {}
url = production.build_production_url()
out["url_has_readonly_intent"] = url.query.get("ApplicationIntent") == "ReadOnly"
out["password_not_in_str"] = "s3cret-Pa55" not in str(url) and "s3cret-Pa55" not in repr(url)
out["describe_has_no_password"] = "s3cret-Pa55" not in json.dumps(production.describe())
out["engine_dialect"] = engine.dialect.name
with TestClient(app) as c:
    for method, path in [("post", "/api/employees"), ("put", "/api/employees/1"), ("delete", "/api/customers/1"), ("post", "/api/tracking")]:
        r = c.request(method.upper(), path, json={})
        out[f"{method} {path}"] = r.status_code
sql = str(select(m.Employee.EmployeeID, m.Employee.YearsInTrade, m.Employee.WillTravel).where(m.Employee.YearsInTrade >= 5)
          .compile(dialect=mssql.dialect()))
out["years_from_lookup"] = "tblPullDownYearsInTrade" in sql and "YearsInTradeID" in sql
out["travel_from_employeeB"] = "tblEmployeeB" in sql
esql = str(select(m.Employee).compile(dialect=mssql.dialect())) + str(select(m.OfficeStaff).compile(dialect=mssql.dialect()))
out["restricted_not_in_sql"] = not any(c in esql for c in ("EmDOB", "USCitizen", "I9Complete", "OfficeStaffPassword", "SSNum", "Bank"))
out["restricted_not_mapped"] = m.Employee.EmDOB is None and m.Employee.USCitizen is None and not hasattr(m.OfficeStaff, "OfficeStaffPassword")
from app.config import settings as _s
out["restricted_fields"] = _s.restricted_field_names
psql = str(select(m.Project.SiteCity, m.Project.SiteState).compile(dialect=mssql.dialect()))
out["site_city_from_lookup"] = "tblPullDownStateCities" in psql and "tblPullDownStates" in psql
print(json.dumps(out))
"""


def test_production_mode_is_read_only_and_mapped(tmp_path):
    env = {**os.environ, "DATA_SOURCE": "production", "PRODUCTION_DB_SERVER": "nonexistent-host.invalid", "PRODUCTION_DB_USER": "readonly_probe",
           "PRODUCTION_DB_PASSWORD": "s3cret-Pa55", "PRODUCTION_WRITES_ENABLED": "false", "PRODUCTION_DB_EXPECTED_SERVER_NAME": "NONEXISTENT-HOST", "SEED_ON_STARTUP": "true", "ANTHROPIC_API_KEY": "", "JWT_SECRET": "unit-test-secret-not-the-demo-value",
           "WEB_AUTH_DATABASE_URL": f"sqlite:///{(tmp_path / 'auth.db').as_posix()}"}
    env.pop("DATABASE_URL", None)
    script = tmp_path / "prod_probe.py"
    script.write_text(_PROD_SCRIPT)
    p = subprocess.run([sys.executable, str(script)], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["engine_dialect"] == "mssql"
    assert out["url_has_readonly_intent"] and out["password_not_in_str"] and out["describe_has_no_password"]
    for k, v in out.items():
        if k.startswith(("post ", "put ", "delete ")):
            assert v == 423, (k, v)
    assert out["years_from_lookup"] and out["travel_from_employeeB"] and out["site_city_from_lookup"]
    assert out["restricted_not_in_sql"] and out["restricted_not_mapped"]
    assert out["restricted_fields"] == ["EmDOB", "USCitizen", "I9Complete"]
    assert "s3cret-Pa55" not in p.stderr and "s3cret-Pa55" not in p.stdout


def test_mssql_url_refused_outside_production():
    from app.database import make_engine

    with pytest.raises(RuntimeError):
        make_engine("mssql+pyodbc://u:p@host/McLabor?driver=ODBC+Driver+17+for+SQL+Server")


def _run(code: str, env_extra: dict, tmp_path) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATA_SOURCE": "production", "PRODUCTION_DB_SERVER": "nonexistent-host.invalid", "PRODUCTION_DB_TRUSTED_CONNECTION": "true",
           "PRODUCTION_DB_EXPECTED_SERVER_NAME": "NONEXISTENT-HOST",
           "ANTHROPIC_API_KEY": "", "WEB_AUTH_DATABASE_URL": f"sqlite:///{(tmp_path / 'auth.db').as_posix()}", **env_extra}
    for k in [k for k in env if k.startswith(("STAGING_", "PRODUCTION_")) and env_extra.get(k, "x") is None]:
        env.pop(k)
    env = {k: v for k, v in env.items() if v is not None}
    env.pop("DATABASE_URL", None)
    env.pop("JWT_SECRET", None) if "JWT_SECRET" not in env_extra else None
    script = tmp_path / "s.py"
    script.write_text("import os, sys\nsys.path.insert(0, os.getcwd())\n" + code)
    return subprocess.run([sys.executable, str(script)], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("extra,expected", [
    ({}, "JWT_SECRET"),
    ({"JWT_SECRET": "a-real-secret-value", "PRODUCTION_DB_TRUST_SERVER_CERTIFICATE": "true"}, "TRUST_SERVER_CERTIFICATE"),
    ({"JWT_SECRET": "a-real-secret-value", "PRODUCTION_DB_ENCRYPT": "false"}, "ENCRYPT"),
])
def test_production_refuses_unsafe_start(tmp_path, extra, expected):
    code = "from fastapi.testclient import TestClient\nfrom app.main import app\ntry:\n    TestClient(app).__enter__()\n    print('STARTED')\nexcept RuntimeError as e:\n    print('REFUSED', e)\n"
    p = _run(code, extra, tmp_path)
    assert "REFUSED" in p.stdout and expected in p.stdout, p.stdout + p.stderr[-800:]


def test_production_connection_settings_for_local_instance(tmp_path):
    code = ("from app import production\nfrom sqlalchemy.dialects.mssql.pyodbc import dialect\n"
            "u = production.build_production_url()\nargs, _ = dialect().create_connect_args(u)\nprint(args[0])\n")
    p = _run(code, {"JWT_SECRET": "a-real-secret-value", "PRODUCTION_DB_SERVER": "COPY-HOST\\SQLEXPRESS", "PRODUCTION_DB_DRIVER": "ODBC Driver 17 for SQL Server"}, tmp_path)
    s = p.stdout.strip().splitlines()[-1]
    assert "Server=COPY-HOST\\SQLEXPRESS" in s and "Database=McLabor" in s and "Trusted_Connection=yes" in s, p.stdout + p.stderr[-800:]
    assert "Encrypt=yes" in s and "TrustServerCertificate=no" in s and "ApplicationIntent=ReadOnly" in s
    assert "UID=" not in s and "PWD=" not in s


def test_production_queries_use_only_approved_columns(tmp_path):
    """Search, record, lookup, duplicate-check and sign-in SQL, recorded offline in production mode."""
    code = ("import json\nfrom app import prodverify\nr = prodverify.run()\nprint(json.dumps(r))\n")
    p = _run(code, {"JWT_SECRET": "a-real-secret-value"}, tmp_path)
    assert p.returncode == 0, p.stderr[-1500:]
    r = json.loads(p.stdout.strip().splitlines()[-1])
    assert r["sensitive_requested"] == [] and r["not_approved"] == [] and r["not_in_schema_export"] == []
    assert r["restricted_still_mapped"] == [] and r["writes_attempted"] == []
    assert r["tsql_problems"] == [], r["tsql_problems"]  # e.g. "IS 1", which SQLite accepts and SQL Server rejects
    assert r["tables_referenced"] == 33 and r["columns_referenced"] == 288
    assert all(isinstance(v, int) and v > 0 for v in r["areas"].values()), r["areas"]
    assert r["forms"]["Employee"]["restricted"] == ["EmDOB", "USCitizen", "I9Complete"]


def test_query_checker_detects_a_sensitive_column(tmp_path):
    code = ("from sqlalchemy import select, table, column\nfrom app import prodverify\n"
            "print(sorted(prodverify.columns_in(select(table('tblEmployee', column('SSNum'), column('EmLastName'))))))\n")
    p = _run(code, {"JWT_SECRET": "a-real-secret-value"}, tmp_path)
    assert "('tblEmployee', 'SSNum')" in p.stdout, p.stdout + p.stderr[-800:]

def test_production_refuses_to_start_with_demo_passwords(tmp_path):
    code = ("from app import webauth\nfrom app.config import settings\nwebauth.set_password(1, settings.demo_password)\nwebauth.set_password(2, 'a-proper-long-password')\n"
            "from fastapi.testclient import TestClient\nfrom app.main import app\ntry:\n    TestClient(app).__enter__()\n    print('STARTED')\nexcept RuntimeError as e:\n    print('REFUSED', e)\n")
    p = _run(code, {"JWT_SECRET": "a-real-secret-value"}, tmp_path)
    assert "REFUSED" in p.stdout and "1 web sign-in account(s) still use the demo password" in p.stdout, p.stdout + p.stderr[-800:]


def test_demo_and_production_use_different_sign_in_files(tmp_path):
    code = "from app.config import settings\nprint(settings.web_auth_url)\n"
    env = {"JWT_SECRET": "a-real-secret-value", "WEB_AUTH_DATABASE_URL": ""}
    prod = _run(code, env, tmp_path).stdout.strip()
    demo = _run(code, {**env, "DATA_SOURCE": "demo"}, tmp_path).stdout.strip()
    assert prod.endswith("web_auth_production.db") and demo.endswith("web_auth.db") and prod != demo, (prod, demo)


def test_boolean_filters_render_for_sql_server():
    from sqlalchemy import select
    from sqlalchemy.dialects import mssql

    from app import models as m

    sql = str(select(m.Employee.EmployeeID).where(m.Employee.EmployeeDuplicate == False, m.Customer.OnHold == True).compile(dialect=mssql.dialect()))  # noqa: E712
    assert " IS " not in sql and "= 0" in sql and "= 1" in sql


def test_live_search_test_runs_on_demo_data(client, admin_headers, capsys):
    from app import livecheck

    assert livecheck.main(["livecheck"]) == 2          # not production and no --demo: refuses
    lines: list[str] = []
    assert livecheck.run(out=lines.append) == 0
    text = "\n".join(lines)
    assert "RESULT: OK" in text and "[FAIL]" not in text
    assert "employees: first page of everyone, by name: " in text and "weekly tracking: newest 50 rows" in text and "jobs: not manned" in text and "customers: with active jobs" in text