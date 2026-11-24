"""The Railway deployment files (deploy/railway) keep the application's security model and are internally consistent."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent.parent
RW = ROOT / "deploy" / "railway"


def test_service_configs_are_valid_and_health_checked():
    be = json.loads((RW / "backend.railway.json").read_text())
    fe = json.loads((ROOT / "frontend" / "railway.json").read_text())
    bk = json.loads((RW / "backup" / "railway.json").read_text())
    assert be["build"]["dockerfilePath"] == "deploy/railway/backend.Dockerfile" and be["deploy"]["healthcheckPath"] == "/api/ready"
    assert fe["deploy"]["healthcheckPath"] == "/healthz" and fe["build"]["builder"] == "DOCKERFILE"
    assert re.fullmatch(r"\d+ \d+ \* \* \*", bk["deploy"]["cronSchedule"]) and bk["deploy"]["restartPolicyType"] == "NEVER"
    assert "docs/schema/**" in be["build"]["watchPatterns"]


def test_backend_image_keeps_the_security_model():
    df = (RW / "backend.Dockerfile").read_text()
    assert "USER app" in df and "COPY docs/schema ./docs/schema" in df and "COPY backend/app ./app" in df
    cmd = next(line for line in df.splitlines() if line.startswith("CMD "))
    assert "--proxy-headers" not in cmd and "--forwarded-allow-ips" not in cmd and "${PORT:-8000}" in cmd and "--host ::" in cmd
    ignore = (ROOT / ".dockerignore").read_text()
    assert "**/.env" in ignore and "**/*.db" in ignore and "**/.venv" in ignore and "**/node_modules" in ignore


def test_env_templates_hold_no_secrets_and_use_private_urls():
    for name in ("backend.staging.env.example", "backend.production.env.example", "backup.env.example", "frontend.env.example"):
        text = (RW / "env" / name).read_text()
        for line in text.splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                if any(s in key for s in ("SECRET", "PASSWORD", "PASSPHRASE", "KEY_ID", "API_KEY")):
                    assert value in ("", "<sealed>") or value.startswith("<"), f"{name}: {key} must not carry a value"
        if name.startswith("backend"):
            assert "DATABASE_PRIVATE_URL" in text and "GATEWAY_PLATFORM=cloudflare-access" in text and "GATEWAY_TRUSTED_PROXIES=any" in text
            assert "ACCESS_SEAT_LIMIT=20" in text and "ANTHROPIC_API_KEY=\n" in text
    assert "BACKEND_INTERNAL_URL=http://backend.railway.internal" in (RW / "env" / "frontend.env.example").read_text()


def test_staging_on_postgres_settings_are_accepted_and_the_office_servers_refused():
    ok = Settings(data_source="staging", staging_database_url="postgresql+psycopg://u:p@postgres.railway.internal:5432/railway", jwt_secret="x" * 40,
                  access_mode="gateway", gateway_platform="cloudflare-access", gateway_trusted_proxies="any",
                  cloudflare_access_team_domain="t.cloudflareaccess.com", cloudflare_access_aud="aud", web_admins="ARI")
    assert ok.db_backend == "postgres" and ok.is_real_data and not ok.is_sql_server and ok.production_shape
    assert ok.search_only and not ok.writes_allowed                                   # a PostgreSQL mirror in staging/production is search-only by default
    assert ok.environment_problems() == []
    full = Settings(data_source="staging", staging_database_url="postgresql+psycopg://u:p@postgres.railway.internal:5432/railway", jwt_secret="x" * 40, web_admins="a", site_mode="full")
    assert not full.search_only and full.writes_allowed                               # the editing release, when it comes, is one setting away
    assert any("SYNC_API_KEY must be" in p for p in Settings(data_source="staging", staging_database_url="postgresql+psycopg://u:p@h.railway.internal/x", jwt_secret="x" * 40, web_admins="a", sync_api_key="short").environment_problems())
    assert not Settings(data_source="staging", staging_database_url="postgresql+psycopg://u:p@h.railway.internal/x", sync_api_key="k" * 40).sync_enabled is False
    assert ok.access == "gateway" and ok.restricted_field_names == ["EmDOB", "USCitizen", "I9Complete"]
    public_no_tls = Settings(data_source="staging", staging_database_url="postgresql+psycopg://u:p@db.example.com:5432/x", jwt_secret="x" * 40, web_admins="a")
    assert any("TLS" in p for p in public_no_tls.environment_problems())
    office = Settings(data_source="staging", staging_database_url="postgresql+psycopg://u:p@198.51.100.2:5432/x?sslmode=require", jwt_secret="x" * 40, web_admins="a",
                      office_hosts="live-host,198.51.100.2")
    assert office.is_office_host("LIVE-HOST\\SQLEXPRESS") and not office.is_office_host("db.railway.internal")
    assert any("office server" in p for p in office.environment_problems())
    same = Settings(data_source="production", production_database_url="postgresql+psycopg://u:p@h/x?sslmode=require", staging_database_url="postgresql+psycopg://u:p@h/x?sslmode=require",
                    jwt_secret="x" * 40, web_admins="a")
    assert any("must be different" in p for p in same.environment_problems())
    demo_pg = Settings(data_source="demo", database_url="postgresql+psycopg://postgres@127.0.0.1:5432/dev", access_mode="")
    assert demo_pg.db_backend == "postgres" and not demo_pg.is_real_data and not demo_pg.production_shape and demo_pg.access == "open"
    assert Settings(data_source="demo", database_url="postgresql+psycopg://postgres@127.0.0.1:5432/dev", db_shape="production").production_shape


def test_backup_scripts_encrypt_and_verify():
    b = (RW / "backup" / "backup.sh").read_text()
    r = (RW / "backup" / "restore-test.sh").read_text()
    assert "aes-256-cbc -pbkdf2" in b and "-pass env:BACKUP_PASSPHRASE" in b and "sha256sum" in b and "pg_dump --format=custom" in b
    assert "CHECKSUM MISMATCH" in r and "pg_restore" in r and "DROP DATABASE IF EXISTS" in r and "restore-test: PASSED" in r
    assert "BACKUP_PASSPHRASE=<sealed>" in (RW / "env" / "backup.env.example").read_text()


def test_frontend_proxy_forwards_identity_headers_only():
    src = (ROOT / "frontend" / "src" / "app" / "api" / "[...path]" / "route.ts").read_text()
    assert "BACKEND_INTERNAL_URL" in src and '"cf-access-jwt-assertion"' in src and '"authorization"' in src and '"cookie"' in src
    assert "force-dynamic" in src and "redirect: \"manual\"" in src
