"""The container deployment files are checked here because Docker is not available on the development PC:
the Compose stack, the two Dockerfiles and the proxy configuration must keep the security model of the application."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "cloud" / "docker-compose.yml"
BACKEND_DOCKERFILE = ROOT / "backend" / "Dockerfile"
FRONTEND_DOCKERFILE = ROOT / "frontend" / "Dockerfile"
CADDYFILE = ROOT / "deploy" / "cloud" / "Caddyfile"


def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_parses_and_names_the_four_services_plus_demo():
    c = compose()
    assert {"proxy", "auth", "frontend", "backend"} <= set(c["services"])
    assert c["services"]["backend-demo"]["profiles"] == ["demo"] and c["services"]["frontend-demo"]["profiles"] == ["demo"]


def test_only_the_proxy_publishes_ports_for_real_data():
    c = compose()
    for name, svc in c["services"].items():
        if svc.get("profiles"):
            for p in svc.get("ports", []):
                assert str(p).startswith("127.0.0.1:"), f"demo port {p} must bind to this PC only"
            continue
        if name == "proxy":
            assert {"80:80", "443:443"} <= set(map(str, svc["ports"]))
        else:
            assert "ports" not in svc, f"{name} must not publish a port"


def test_networks_isolate_the_frontend_and_give_auth_and_backend_egress():
    c = compose()
    nets = c["networks"]
    assert nets["internal"] == {"internal": True}
    s = c["services"]
    assert s["frontend"]["networks"] == ["internal"]                       # no internet for the frontend
    assert "egress" in s["auth"]["networks"] and "egress" in s["backend"]["networks"]  # identity provider / database
    assert "internal" in s["proxy"]["networks"] and "edge" in s["proxy"]["networks"]


def test_secrets_are_files_and_never_inline_values():
    c = compose()
    declared = set(c["secrets"])
    for name, svc in c["services"].items():
        for s in svc.get("secrets", []):
            assert s in declared, f"{name} uses undeclared secret {s}"
        env = svc.get("environment") or {}
        for k, v in (env.items() if isinstance(env, dict) else [e.split("=", 1) for e in env]):
            assert not re.search(r"(PASSWORD|SECRET|KEY)$", k) or str(v).startswith("/run/secrets") or "${" in str(v), f"{name}: {k} holds an inline value"
    for s, spec in c["secrets"].items():
        assert spec["file"].startswith("./secrets/"), s
    text = COMPOSE.read_text(encoding="utf-8")
    assert "MCLABOR_SECRETS_DIR" not in text or "/nonexistent" in text  # the image sets /run/secrets; the demo disables it
    assert not re.search(r"(?i)password\s*[:=]\s*['\"]?[A-Za-z0-9]{6,}", text)


def test_healthchecks_and_start_order():
    c = compose()
    s = c["services"]
    assert "healthcheck" in s["backend"] and "/api/ready" in " ".join(s["backend"]["healthcheck"]["test"])
    assert "healthcheck" in s["frontend"] and "/healthz" in " ".join(s["frontend"]["healthcheck"]["test"])
    assert s["proxy"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert s["proxy"]["depends_on"]["frontend"]["condition"] == "service_healthy"


def test_backend_trusts_only_the_compose_network_and_keeps_the_sign_in_store():
    c = compose()
    b = c["services"]["backend"]
    assert "GATEWAY_TRUSTED_PROXIES" in b["environment"] and "172.16.0.0/12" in b["environment"]["GATEWAY_TRUSTED_PROXIES"]
    assert any(v.startswith("web_auth:/app/data") for v in b["volumes"]) and "web_auth" in c["volumes"]
    assert any("docs/schema" in v and v.endswith(":ro") for v in b["volumes"])
    assert b["env_file"] == ["backend.env"] and (COMPOSE.parent / "backend.env.example").exists()


def test_dockerfiles_run_as_non_root_with_healthchecks_and_without_proxy_header_trust():
    be = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    assert "USER app" in be and "HEALTHCHECK" in be and "msodbcsql18" in be
    cmd = next(line for line in be.splitlines() if line.startswith("CMD "))
    assert "--proxy-headers" not in cmd and "--forwarded-allow-ips" not in cmd, "the backend must see the proxy's own address (GATEWAY_TRUSTED_PROXIES)"
    assert "MCLABOR_SECRETS_DIR=/run/secrets" in be and "LOG_FORMAT=json" in be
    assert re.search(r"EXPOSE 8000", be) and ("--host ::" in be or "0.0.0.0" in be)   # "::" = IPv6 and IPv4 (hosted private networks)
    fe = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
    assert "USER app" in fe and "HEALTHCHECK" in fe and ".next/standalone" in fe and 'ARG NEXT_PUBLIC_API_URL=""' in fe
    assert (ROOT / "backend" / ".dockerignore").read_text().strip().splitlines().count(".env") == 1
    assert "*.db" in (ROOT / "backend" / ".dockerignore").read_text()
    assert "output: \"standalone\"" in (ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")


VM = ROOT / "deploy" / "vm"


def test_vm_env_templates_use_cloudflare_access_read_only_and_hold_no_secret():
    for env in ("production", "staging"):
        text = (VM / "env" / f"backend.{env}.env.example").read_text(encoding="utf-8")
        cfg = dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#") and "=" in line)
        E = env.upper()
        assert cfg["DATA_SOURCE"] == env and cfg["ACCESS_MODE"] == "gateway" and cfg["GATEWAY_PLATFORM"] == "cloudflare-access"
        assert cfg["GATEWAY_TRUSTED_PROXIES"] == "127.0.0.1,::1" and "CLOUDFLARE_ACCESS_AUD" in cfg and "CLOUDFLARE_ACCESS_TEAM_DOMAIN" in cfg
        assert cfg[f"{E}_WRITES_ENABLED"] == "false" and cfg[f"{E}_DB_ENCRYPT"] == "true" and cfg[f"{E}_DB_TRUST_SERVER_CERTIFICATE"] == "false"
        assert cfg[f"{E}_DB_USER"] == "mclabor_web_read" and f"{E}_DB_PASSWORD" not in cfg and "JWT_SECRET" not in cfg  # secrets are files
        assert cfg["ANTHROPIC_API_KEY"] == "" and cfg["LOG_FORMAT"] == "json"
        other = "STAGING" if env == "production" else "PRODUCTION"
        assert not any(k.startswith(other + "_") for k in cfg), "an environment's file never holds the other environment's settings"
    prod = (VM / "env" / "backend.production.env.example").read_text(encoding="utf-8")
    stag = (VM / "env" / "backend.staging.env.example").read_text(encoding="utf-8")
    assert "McLaborStaging" in stag and "PRODUCTION_DB_NAME=McLabor\n" in prod


def test_vm_tunnel_routes_both_environments_and_the_private_sql_network():
    cfg = yaml.safe_load((VM / "cloudflared-config.yml.example").read_text(encoding="utf-8"))
    rules = cfg["ingress"]
    assert rules[-1] == {"service": "http_status:404"}
    by_host = {}
    for r in rules[:-1]:
        by_host.setdefault(r["hostname"], []).append(r["service"])
    assert set(by_host) == {"app.mclabor.example", "staging.mclabor.example"}
    assert by_host["app.mclabor.example"] == ["http://127.0.0.1:8000", "http://127.0.0.1:3000"]
    assert by_host["staging.mclabor.example"] == ["http://127.0.0.1:8100", "http://127.0.0.1:3100"]
    assert all(r.get("path") == "^/api/.*" for r in rules[:-1] if r["service"].endswith(("8000", "8100")))
    assert cfg["warp-routing"] == {"enabled": True}
    assert "0.0.0.0" not in (VM / "cloudflared-config.yml.example").read_text()


def test_vm_provisioning_plan_never_opens_an_inbound_port_and_sets_the_budget():
    plan = (VM / "azure" / "provision-vm.ps1").read_text(encoding="utf-8")
    assert "--access Deny" in plan and "deny-all-inbound" in plan
    assert "--access Allow" not in plan, "no inbound allow rule anywhere in the plan"
    assert "VmSize = 'Standard_B2ms'" in plan and "Standard_B4ms" in plan and "sql2019" in plan and "express" in plan.lower()   # B2ms default for 20 users, B4ms the option
    assert "CPU Credits Remaining" in plan                                                                                   # the throttling warning for a B-series VM
    assert "StandardSSD_LRS" in plan and "Premium" not in plan
    assert "budget.bicep" in plan and "if ($staging) { 50 } else { 200 }" in plan          # 200 USD production, 50 USD staging
    assert "AutoShutdownTime = '1900'" in plan and "'synthetic-only'" in plan             # staging deallocates nightly and is tagged for the cleanup script
    bicep = (VM / "azure" / "budget.bicep").read_text(encoding="utf-8")
    for pct in (50, 75, 90, 100):
        assert f"threshold: {pct}, thresholdType: 'Actual'" in bicep
    assert "thresholdType: 'Forecasted'" in bicep
    import json

    lifecycle = json.loads((VM / "azure" / "lifecycle.json").read_text(encoding="utf-8"))
    deletes = {r["name"]: r["definition"]["actions"]["baseBlob"]["delete"]["daysAfterModificationGreaterThan"] for r in lifecycle["rules"]}
    assert deletes == {"daily-backups-35-days": 35, "monthly-backups-12-months": 366}
    json.loads((VM / "azure" / "dcr-events.json").read_text(encoding="utf-8"))


def test_vm_backup_scripts_verify_encrypt_and_never_store_the_key_in_clear():
    backup = (VM / "backup-sql.ps1").read_text(encoding="utf-8")
    assert "WITH CHECKSUM" in backup and "RESTORE VERIFYONLY" in backup and "HMACSHA256" in backup and "ProtectedData]::Protect" in backup
    assert "Write-EventLog" in backup and "MCLaborBackup" in backup
    restore = (VM / "restore-test.ps1").read_text(encoding="utf-8")
    assert "DBCC CHECKDB" in restore and "DROP DATABASE" in restore and "_RestoreTest" in restore
    firewall = (VM / "firewall.ps1").read_text(encoding="utf-8")
    assert "-DefaultInboundAction Block" in firewall and "LocalPort 1433" in firewall and "100.96.0.0/12" in firewall
    deploy = (VM / "deploy-app.ps1").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in deploy and "HOSTNAME = '127.0.0.1'" in deploy and "NT SERVICE" in deploy and "MCLABOR_SECRETS_DIR" in deploy


def test_settings_file_can_live_outside_the_code_folder(tmp_path):
    from test_production import _run

    f = tmp_path / "service.env"
    f.write_text("DATA_SOURCE=demo\nAPP_NAME=From the service env file\n", encoding="utf-8")
    p = _run("from app.config import settings\nprint(settings.app_name)\n", {"MCLABOR_SETTINGS_FILE": str(f), "MCLABOR_ENV_FILE": None}, tmp_path)
    assert p.returncode == 0 and p.stdout.strip().splitlines()[-1] == "From the service env file", p.stdout + p.stderr[-500:]


def test_proxy_strips_visitor_identity_headers_and_adds_the_secret():
    caddy = CADDYFILE.read_text(encoding="utf-8")
    assert "forward_auth auth:4180" in caddy
    for h in ("X-Gateway-Secret", "Cf-Access-Authenticated-User-Email", "X-MS-CLIENT-PRINCIPAL-NAME"):
        assert f"request_header -{h}" in caddy, h
    assert "request_header X-Gateway-Secret {file./run/secrets/gateway_secret}" in caddy
    assert "reverse_proxy backend:8000" in caddy and "reverse_proxy frontend:3000" in caddy
    assert "Strict-Transport-Security" in caddy
    # the frontend path must strip the e-mail header too (the API path gets it from forward_auth on purpose)
    frontend_block = caddy.split("handle {", 1)[1]
    assert "request_header -X-Auth-Request-Email" in frontend_block
