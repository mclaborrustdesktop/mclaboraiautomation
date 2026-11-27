"""Unverified server certificate on the office network: refused unless the owner's written waiver is recorded."""
from app.config import Settings

BASE = dict(data_source="production", production_db_server="live,1433", production_db_expected_server_name="LIVE\\SQLEXPRESS",
            production_db_name="McLabor", production_db_user="mclabor", production_db_encrypt=True, jwt_secret="x" * 40,
            production_writes_enabled=False, access_mode="login", web_admins="ARI")


def test_trust_server_certificate_needs_the_waiver():
    s = Settings(**BASE, production_db_trust_server_certificate=True, _env_file=None)
    assert any("TLS_WAIVER" in p for p in s.environment_problems())
    s = Settings(**BASE, production_db_trust_server_certificate=True, production_db_tls_waiver="too short", _env_file=None)
    assert any("TLS_WAIVER" in p for p in s.environment_problems())


def test_waiver_recorded_is_accepted_and_verification_stays_the_default():
    s = Settings(**BASE, production_db_trust_server_certificate=True,
                 production_db_tls_waiver="Approved by the owner on 2026-11-27 until the live server has a trusted certificate", _env_file=None)
    assert not any("TLS_WAIVER" in p or "TRUST_SERVER_CERTIFICATE" in p for p in s.environment_problems())
    assert s.db_trust_server_certificate is True
    d = Settings(**BASE, _env_file=None)
    assert d.db_trust_server_certificate is False
