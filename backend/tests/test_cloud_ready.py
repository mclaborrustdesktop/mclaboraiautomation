"""Container / cloud hosting: readiness, secrets from files, request ids, JSON logs, Azure built-in authentication."""
from __future__ import annotations

import json
import logging

from app.config import Settings, settings
from app.observability import JsonFormatter, request_id_var

SECRET = "g" * 40


def test_readiness_reports_database_and_sign_in_store(client):
    r = client.get("/api/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready" and body["checks"] == {"database": "ok", "sign_in_store": "ok"} and body["environment"] == "demo"
    assert "password" not in r.text.lower()


def test_readiness_is_503_when_the_database_is_down(client, monkeypatch):
    from app import main

    class Broken:
        def connect(self):
            raise RuntimeError("down")

    monkeypatch.setattr(main, "engine", Broken())
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "unavailable" and "down" not in r.text


def test_secrets_can_come_from_files(tmp_path):
    (tmp_path / "jwt_secret").write_text("from-a-mounted-secret-file-0123456789", encoding="utf-8")
    (tmp_path / "production_db_password").write_text("p@ss-from-file", encoding="utf-8")
    s = Settings(_secrets_dir=str(tmp_path), data_source="demo")
    assert s.jwt_secret == "from-a-mounted-secret-file-0123456789" and s.production_db_password == "p@ss-from-file"


def test_every_response_carries_a_request_id(client):
    r = client.get("/api/health")
    rid = r.headers["X-Request-ID"]
    assert rid and len(rid) == 16
    assert client.get("/api/health", headers={"X-Request-ID": "proxy-abc-123"}).headers["X-Request-ID"] == "proxy-abc-123"  # the proxy's id is kept
    assert client.get("/api/health", headers={"X-Request-ID": "bad id with spaces<>"}).headers["X-Request-ID"] != "bad id with spaces<>"  # unsafe ids are replaced


def test_json_log_lines_are_json_and_hold_no_query_string():
    record = logging.LogRecord("mclabor.access", logging.INFO, __file__, 1, "GET /api/employees -> 200 in 12 ms", (), None)
    record.method, record.path, record.status, record.ms = "GET", "/api/employees", 200, 12
    token = request_id_var.set("req-1")
    try:
        line = JsonFormatter().format(record)
    finally:
        request_id_var.reset(token)
    entry = json.loads(line)
    assert entry["request_id"] == "req-1" and entry["path"] == "/api/employees" and entry["status"] == 200 and entry["environment"] == "demo"
    assert "?" not in entry["path"] and "q=" not in line


def test_azure_easyauth_gateway_names_the_person_without_a_shared_secret(client, admin_headers, monkeypatch):
    email = client.get("/api/auth/me", headers=admin_headers).json()["OfficeStaffEmail"]
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "gateway")
    monkeypatch.setattr(settings, "gateway_platform", "azure-easyauth")
    monkeypatch.setattr(settings, "gateway_trusted_proxies", "testclient")
    monkeypatch.setattr(settings, "web_admins", email)
    assert not any("GATEWAY_SECRET" in p for p in Settings(data_source="staging", access_mode="gateway", gateway_platform="azure-easyauth").environment_problems())
    assert client.get("/api/auth/me").status_code == 401                                                                     # anonymous
    assert client.get("/api/auth/me", headers={"X-MS-CLIENT-PRINCIPAL-NAME": email}).status_code == 401                      # no identity-provider header
    assert client.get("/api/auth/me", headers={"X-Gateway-Secret": SECRET, "X-Auth-Request-Email": email}).status_code == 401  # the proxy headers mean nothing here
    assert client.get("/api/auth/me", headers={"X-MS-CLIENT-PRINCIPAL-IDP": "aad", "X-MS-CLIENT-PRINCIPAL-NAME": "stranger@example.com"}).status_code == 403
    ok = client.get("/api/auth/me", headers={"X-MS-CLIENT-PRINCIPAL-IDP": "aad", "X-MS-CLIENT-PRINCIPAL-NAME": email.upper()})
    assert ok.status_code == 200 and ok.json()["Profile"] is True
    monkeypatch.setattr(settings, "gateway_trusted_proxies", "127.0.0.1")
    assert client.get("/api/auth/me", headers={"X-MS-CLIENT-PRINCIPAL-IDP": "aad", "X-MS-CLIENT-PRINCIPAL-NAME": email}).status_code == 401  # wrong address
    assert any("GATEWAY_PLATFORM" in p for p in Settings(data_source="staging", gateway_platform="something-else").environment_problems())


def _rsa_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return private, pem


class _FakeJwkClient:
    """Stands in for Cloudflare's published keys: returns the test public key for kid 'test-key' only."""

    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token):
        import jwt as pyjwt

        header = pyjwt.get_unverified_header(token)
        if header.get("kid") != "test-key":
            raise pyjwt.exceptions.PyJWKClientError("unknown kid")
        return type("Key", (), {"key": self.public_key})()


def test_cloudflare_access_tokens_are_verified_not_trusted(client, admin_headers, monkeypatch):
    import time as _time

    import jwt as pyjwt

    from app import cloudflare_access

    private, pem = _rsa_keypair()
    other_private, other_pem = _rsa_keypair()
    email = client.get("/api/auth/me", headers=admin_headers).json()["OfficeStaffEmail"]
    team, aud = "mclabor.cloudflareaccess.com", "aud-tag-0123456789abcdef"
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "access_mode", "gateway")
    monkeypatch.setattr(settings, "gateway_platform", "cloudflare-access")
    monkeypatch.setattr(settings, "gateway_trusted_proxies", "testclient")
    monkeypatch.setattr(settings, "cloudflare_access_team_domain", team)
    monkeypatch.setattr(settings, "cloudflare_access_aud", aud)
    monkeypatch.setattr(settings, "web_admins", email)
    monkeypatch.setattr(cloudflare_access, "_jwk_client", lambda issuer: _FakeJwkClient(private.public_key()))
    now = int(_time.time())

    def token(key_pem=pem, kid="test-key", **over):
        claims = {"email": email, "aud": aud, "iss": f"https://{team}", "iat": now, "exp": now + 600, **over}
        return pyjwt.encode(claims, key_pem, algorithm="RS256", headers={"kid": kid})

    assert client.get("/api/auth/me").status_code == 401                                                                      # anonymous
    assert client.get("/api/auth/me", headers={"Cf-Access-Authenticated-User-Email": email}).status_code == 401              # a plain header is not identity
    ok = client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token()})
    assert ok.status_code == 200 and ok.json()["Profile"] is True
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token(key_pem=other_pem)}).status_code == 401        # signed by someone else
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token(aud="another-application")}).status_code == 401
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token(iss="https://evil.example")}).status_code == 401
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token(exp=now - 120)}).status_code == 401           # expired
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token(email="stranger@example.com")}).status_code == 403  # valid token, not on the lists
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": "not.a.token"}).status_code == 401
    # the token also travels in Cloudflare's cookie (a hosted front end forwards it); verified the same way
    assert client.get("/api/auth/me", cookies={"CF_Authorization": token()}).status_code == 200
    assert client.get("/api/auth/me", cookies={"CF_Authorization": token(aud="another-application")}).status_code == 401
    monkeypatch.setattr(settings, "gateway_trusted_proxies", "127.0.0.1")
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token()}).status_code == 401                        # did not come through the tunnel
    # "any" source address is acceptable only on this platform (the signed token is the proof: hosted services put their own proxy in front)
    monkeypatch.setattr(settings, "gateway_trusted_proxies", "any")
    assert client.get("/api/auth/me", headers={"Cf-Access-Jwt-Assertion": token()}).status_code == 200
    assert any("any is only allowed" in p for p in Settings(data_source="production", access_mode="gateway", gateway_platform="proxy", gateway_secret="x" * 40,
                                                            gateway_trusted_proxies="any").environment_problems())
    assert any("CLOUDFLARE_ACCESS" in p for p in Settings(data_source="production", access_mode="gateway", gateway_platform="cloudflare-access").environment_problems())
    assert not any("CLOUDFLARE" in p for p in Settings(data_source="production", access_mode="gateway", gateway_platform="cloudflare-access",
                                                       cloudflare_access_team_domain=team, cloudflare_access_aud=aud).environment_problems())


def test_trusted_proxies_accept_addresses_and_networks_only():
    s = Settings(data_source="demo", gateway_trusted_proxies="127.0.0.1, ::1, 172.16.0.0/12, testclient")
    assert s.is_trusted_proxy("127.0.0.1") and s.is_trusted_proxy("::1") and s.is_trusted_proxy("172.18.0.5") and s.is_trusted_proxy("testclient")
    assert not s.is_trusted_proxy("198.51.100.5") and not s.is_trusted_proxy("172.32.0.1") and not s.is_trusted_proxy("") and not s.is_trusted_proxy(None)
    assert not Settings(data_source="demo", gateway_trusted_proxies="not-an-address/99").is_trusted_proxy("172.18.0.5")
    assert not Settings(data_source="demo", gateway_trusted_proxies="").is_trusted_proxy("127.0.0.1")


def test_cloud_connection_string_retries_transient_errors(tmp_path):
    from test_production import _run

    code = ("from app import production\nfrom sqlalchemy.dialects.mssql.pyodbc import dialect\n"
            "args, _ = dialect().create_connect_args(production.build_sql_server_url())\nprint(args[0])\n")
    p = _run(code, {"DATA_SOURCE": "staging", "JWT_SECRET": "a-real-secret-value", "STAGING_DB_SERVER": "copy-host.invalid", "STAGING_DB_EXPECTED_SERVER_NAME": "COPY",
                    "STAGING_DB_TRUSTED_CONNECTION": "true", "DB_CONNECT_RETRIES": "4"}, tmp_path)
    assert p.returncode == 0, p.stderr[-800:]
    assert "ConnectRetryCount=4" in p.stdout and "ConnectRetryInterval=5" in p.stdout and "Encrypt=yes" in p.stdout
