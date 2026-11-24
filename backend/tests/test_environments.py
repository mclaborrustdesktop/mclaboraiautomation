"""DEMO / STAGING / PRODUCTION separation. No SQL Server is contacted (server names are made up)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from test_production import _run

STAGING = {"DATA_SOURCE": "staging", "JWT_SECRET": "a-real-secret-value", "STAGING_DB_SERVER": "copy-host.invalid", "STAGING_DB_EXPECTED_SERVER_NAME": "COPY-HOST\\SQLEXPRESS",
           "STAGING_DB_TRUSTED_CONNECTION": "true", "PRODUCTION_DB_SERVER": None, "PRODUCTION_DB_EXPECTED_SERVER_NAME": None, "PRODUCTION_DB_TRUSTED_CONNECTION": None}

START = "from fastapi.testclient import TestClient\nfrom app.main import app\ntry:\n    TestClient(app).__enter__()\n    print('STARTED')\nexcept (RuntimeError, ValueError) as e:\n    print('REFUSED', e)\n"


def test_demo_is_the_default_environment():
    assert settings.environment == "demo" and settings.is_demo and not settings.is_sql_server
    assert settings.db_server is None and settings.sql_writes_allowed is False
    assert settings.web_auth_url.endswith(".db")


def test_staging_uses_only_staging_settings(tmp_path):
    code = ("import json\nfrom app.config import settings as s\nfrom app import production, models as m\nfrom sqlalchemy.dialects.mssql.pyodbc import dialect\n"
            "args, _ = dialect().create_connect_args(production.build_sql_server_url())\n"
            "print(json.dumps({'env': s.environment, 'conn': args[0], 'auth': s.web_auth_url, 'restricted': s.restricted_field_names, 'writes': s.sql_writes_allowed,"
            " 'dob_unmapped': m.Employee.EmDOB is None, 'pw_unmapped': not hasattr(m.OfficeStaff, 'OfficeStaffPassword'), 'problems': s.environment_problems()}))\n")
    # production settings are present too (with a password) and must be ignored completely
    extra = {**STAGING, "WEB_AUTH_DATABASE_URL": "", "PRODUCTION_DB_SERVER": "live-host.invalid", "PRODUCTION_DB_EXPECTED_SERVER_NAME": "LIVE-HOST\\SQLEXPRESS",
             "PRODUCTION_DB_USER": "live_user", "PRODUCTION_DB_PASSWORD": "live-s3cret", "PRODUCTION_WRITES_ENABLED": "true", "PRODUCTION_WRITE_APPROVAL": "TICKET-1"}
    p = _run(code, extra, tmp_path)
    assert p.returncode == 0, p.stderr[-1500:]
    r = json.loads(p.stdout.strip().splitlines()[-1])
    assert r["env"] == "staging" and r["problems"] == []
    assert "Server=copy-host.invalid" in r["conn"] and "live-host" not in r["conn"] and "live_user" not in r["conn"] and "live-s3cret" not in r["conn"]
    assert "ApplicationIntent=ReadOnly" in r["conn"] and "Encrypt=yes" in r["conn"] and "TrustServerCertificate=no" in r["conn"]
    assert r["writes"] is False                       # production's write switch does not unlock staging
    assert r["auth"].endswith("web_auth_staging.db")  # its own sign-in file
    assert r["restricted"] == ["EmDOB", "USCitizen", "I9Complete"] and r["dob_unmapped"] and r["pw_unmapped"]


def test_staging_is_read_only_over_the_api(tmp_path):
    code = ("from fastapi.testclient import TestClient\nfrom app.main import app\n"
            "with TestClient(app) as c:\n    print(c.post('/api/employees', json={}).status_code, c.put('/api/customers/1', json={}).status_code, c.get('/api/health').json()['environment'])\n")
    p = _run(code, STAGING, tmp_path)
    assert p.stdout.strip().splitlines()[-1] == "423 423 staging", p.stdout + p.stderr[-800:]


@pytest.mark.parametrize("extra,expected", [
    ({"STAGING_DB_EXPECTED_SERVER_NAME": None}, "STAGING_DB_EXPECTED_SERVER_NAME is not set"),
    ({"STAGING_DB_SERVER": None}, "STAGING_DB_SERVER is not set"),
    ({"PRODUCTION_DB_SERVER": "copy-host.invalid"}, "must be different"),
    ({"PRODUCTION_DB_EXPECTED_SERVER_NAME": "copy-host\\sqlexpress"}, "must be different"),
    ({"STAGING_DB_EXPECTED_SERVER_NAME": "LIVE-HOST\\SQLEXPRESS", "PRODUCTION_DB_SERVER": "live-host\\sqlexpress"}, "wrong environment"),
    ({"STAGING_DB_TRUST_SERVER_CERTIFICATE": "true"}, "TRUST_SERVER_CERTIFICATE must stay false"),
    ({"JWT_SECRET": "change-me-in-production-mc-labor-demo-secret"}, "JWT_SECRET"),
    ({"DATA_SOURCE": "prod"}, "DATA_SOURCE must be one of"),
])
def test_unsafe_environment_settings_are_refused(tmp_path, extra, expected):
    p = _run(START, {**STAGING, **extra}, tmp_path)
    out = p.stdout + p.stderr
    assert "STARTED" not in p.stdout and expected in out, out[-1200:]


def test_same_server_is_allowed_for_a_different_database(tmp_path):
    # e.g. a development database that sits next to the live one on the same server
    extra = {**STAGING, "STAGING_DB_NAME": "McLabor Development", "PRODUCTION_DB_SERVER": "copy-host.invalid", "PRODUCTION_DB_EXPECTED_SERVER_NAME": "COPY-HOST\\SQLEXPRESS"}
    p = _run("from app.config import settings\nprint(settings.environment_problems())\n", extra, tmp_path)
    assert p.stdout.strip() == "[]", p.stdout + p.stderr[-800:]


def test_identity_check_refuses_the_wrong_server(tmp_path):
    code = ("from app import production as p\n"
            "p.check_identity('copy-host\\\\sqlexpress', 'McLabor'); print('same server: accepted')\n"
            "for server, db in (('LIVE-HOST\\\\SQLEXPRESS', 'McLabor'), ('COPY-HOST\\\\SQLEXPRESS', 'McLabor 20260811 Development'), (None, 'McLabor')):\n"
            "    try:\n        p.check_identity(server, db); print('ACCEPTED', server, db)\n    except p.WrongServer as e:\n        print('refused:', e)\n")
    p = _run(code, STAGING, tmp_path)
    lines = p.stdout.strip().splitlines()
    assert lines[0] == "same server: accepted" and len(lines) == 4 and all(l.startswith("refused:") for l in lines[1:]), p.stdout + p.stderr[-800:]
    assert "may only use server 'COPY-HOST\\SQLEXPRESS'" in lines[1] and "LIVE-HOST" in lines[1]


def test_identity_check_is_installed_on_sql_server_engines(tmp_path):
    code = ("from sqlalchemy import event\nfrom app.database import engine\nfrom app import production\n"
            "print(engine.dialect.name, len(list(engine.pool.dispatch.connect)), len(list(engine.dispatch.before_cursor_execute)))\n")
    p = _run(code, STAGING, tmp_path)
    name, connect_listeners, guard_listeners = p.stdout.strip().split()
    assert name == "mssql" and int(connect_listeners) >= 1 and int(guard_listeners) >= 1, p.stdout + p.stderr[-800:]


def test_sign_in_from_another_environment_is_rejected(client, admin_headers):
    staff_id = client.get("/api/auth/me", headers=admin_headers).json()["OfficeStaffID"]
    now = datetime.now(timezone.utc)

    def token(env):
        payload = {"sub": str(staff_id), "iat": now, "exp": now + timedelta(minutes=5)}
        if env:
            payload["env"] = env
        return {"Authorization": "Bearer " + jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)}

    assert client.get("/api/auth/me", headers=token("demo")).status_code == 200
    for other in ("staging", "production"):
        r = client.get("/api/auth/me", headers=token(other))
        assert r.status_code == 401 and "different environment" in r.json()["detail"]


def test_staging_queries_use_only_approved_columns(tmp_path):
    code = "import json\nfrom app import prodverify\nprint(json.dumps(prodverify.run()))\n"
    p = _run(code, {**STAGING, "PRODVERIFY_ENV": "staging"}, tmp_path)
    assert p.returncode == 0, p.stderr[-1500:]
    r = json.loads(p.stdout.strip().splitlines()[-1])
    assert r["sensitive_requested"] == [] and r["not_approved"] == [] and r["tsql_problems"] == [] and r["writes_attempted"] == []
    assert r["tables_referenced"] == 33 and r["columns_referenced"] == 288


def test_lookups_and_health_report_the_environment(client, admin_headers):
    assert client.get("/api/health").json()["environment"] == "demo"
    assert client.get("/api/lookups", headers=admin_headers).json()["environment"] == "demo"
    st = client.get("/api/system/status", headers=admin_headers).json()
    assert st["environment"] == "demo" and st["database"]["mode"].startswith("demo")
