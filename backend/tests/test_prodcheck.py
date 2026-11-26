"""Offline tests for the isolated read-only connection check (tools/prod-check). No SQL Server is contacted."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "prod-check"
spec = importlib.util.spec_from_file_location("check_readonly", TOOL / "check_readonly.py")
chk = importlib.util.module_from_spec(spec)
sys.modules["check_readonly"] = chk
spec.loader.exec_module(chk)


@pytest.mark.parametrize("sql", [
    "SELECT DB_NAME(), SUSER_SNAME()",
    "select TABLE_NAME, COLUMN_NAME, DATA_TYPE from INFORMATION_SCHEMA.COLUMNS where TABLE_SCHEMA = ?",
    "SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', 'SELECT', ?, 'COLUMN')",
])
def test_allows_metadata_selects(sql):
    chk.assert_read_only(sql)


@pytest.mark.parametrize("sql", [
    "UPDATE tblEmployee SET EmLastName = 'x'",
    "DELETE FROM tblTracking",
    "SELECT * INTO copy FROM tblEmployee",
    "SELECT 1; DROP TABLE tblEmployee",
    "SELECT 1 -- hidden",
    "SELECT 1 /* hidden */",
    "EXEC sp_who",
    "SELECT * FROM OPENROWSET('x','y','z')",
    "WITH x AS (SELECT 1) DELETE FROM x",
    "SELECT name FROM sys.tables WHERE 1 = (SELECT 1) GRANT SELECT ON t TO public",
])
def test_refuses_anything_else(sql):
    with pytest.raises(chk.UnsafeStatement):
        chk.assert_read_only(sql)


def test_every_statement_in_the_script_passes_its_own_guard():
    """The script never reads rows from a business table: it only names tbl* objects as parameters."""
    src = (TOOL / "check_readonly.py").read_text(encoding="utf-8")
    assert "FROM dbo.tbl" not in src and "FROM tbl" not in src
    assert "import app" not in src and "from app" not in src
    statements = [s for s in __import__("re").findall(r'"(SELECT [^"]+)"', src)]
    assert len(statements) >= 8
    joined = __import__("re").findall(r'q\(\s*((?:"[^"]*"\s*)+)', src)
    for parts in joined:
        chk.assert_read_only("".join(__import__("re").findall(r'"([^"]*)"', parts)))


def test_connection_string_is_read_only_and_masks_password():
    cfg = {"SERVER": "SRV\\SQLEXPRESS", "AUTH": "sql", "USER": "ro_user"}
    cs = chk.build_connection_string(cfg, "ODBC Driver 17 for SQL Server", "p;w}d")
    assert "ApplicationIntent=ReadOnly" in cs and "Encrypt=yes" in cs and "TrustServerCertificate=no" in cs
    assert "PWD={p;w}}d}" in cs
    assert "p;w" not in chk.mask(cs, "p;w}d")
    win = chk.build_connection_string({"SERVER": "SRV", "AUTH": "windows"}, "ODBC Driver 17 for SQL Server", None)
    assert "Trusted_Connection=yes" in win and "PWD" not in win and "UID" not in win


def test_required_schema_excludes_sensitive_columns():
    req = json.loads((TOOL / "required_schema.json").read_text(encoding="utf-8"))
    assert len(req["tables"]) == 33
    emp = req["tables"]["tblEmployee"]
    for col in ("SSNum", "EmDOB", "BankAccountNumber", "BankRoutingNumber", "USCitizen", "I9Complete"):
        assert col not in emp
        assert col in req["sensitive_columns"]["tblEmployee"]
    assert "OfficeStaffPassword" not in req["tables"]["tblOfficeStaff"]
    assert "YearsInTradeID" in emp and "WillTravel" in req["tables"]["tblEmployeeB"]
    for name in ("proposed-grants.sql", "proposed-grants-production.sql"):
        grants = (TOOL / name).read_text(encoding="utf-8")
        body = grants.split("USE [McLabor]")[1]
        statements = []
        for chunk in body.split(";"):
            code = " ".join(line.strip() for line in chunk.splitlines() if line.strip() and not line.strip().startswith("--") and line.strip().upper() != "GO").strip()
            if code:
                statements.append(code)
        grant_lines = [s for s in statements if s.upper().startswith("GRANT")]
        deny_lines = [s for s in statements if s.upper().startswith("DENY")]
        assert len(grant_lines) == 33 and all(s.upper().startswith("GRANT SELECT ON DBO.") for s in grant_lines)
        for col in ("SSNum", "BankAccountNumber", "EmDOB", "OfficeStaffPassword"):
            assert not any(f"[{col}]" in s for s in grant_lines)          # never granted
            assert any(f"[{col}]" in s and "DENY SELECT" in s for s in deny_lines)  # explicitly refused
        db_deny = next(s for s in deny_lines if "ON DATABASE::[McLabor]" in s)
        for perm in ("INSERT", "UPDATE", "DELETE", "EXECUTE", "ALTER", "CREATE TABLE", "TAKE OWNERSHIP"):
            assert perm in db_deny
        assert "CONTROL" not in db_deny                                  # denying CONTROL would deny SELECT too
        # no write verb anywhere except inside the DENY statements and comments
        for s in statements:
            if not s.upper().startswith("DENY"):
                keywords = __import__("re").sub(r"\[[^\]]*\]", "", s).upper()  # column names such as OfficeStaffCanDelete are identifiers, not verbs
                assert not __import__("re").search(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE)\b", keywords), s[:80]
        assert "DENY VIEW ANY DATABASE TO [mclabor_web_read]" in grants
    verify = (TOOL / "verify-readonly-login.sql").read_text(encoding="utf-8")
    assert verify.count("EXECUTE AS LOGIN") == 1 and verify.rstrip().endswith("REVERT;")
    for s in verify.split(";"):
        first = " ".join(line for line in s.strip().splitlines() if not line.strip().startswith("--")).strip().upper()
        assert not first.startswith(("INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC ", "BEGIN TRAN", "GRANT", "DENY")), first[:60]


def test_passwords_in_config_file_are_refused(tmp_path, monkeypatch):
    cfg_file = tmp_path / "prodcheck.env"
    cfg_file.write_text("SERVER=SRV\nAUTH=sql\nUSER=ro\nPASSWORD=secret\n")
    monkeypatch.setattr(chk, "CONFIG", cfg_file)
    rep = chk.Report()
    ready, _ = chk.preflight(chk.load_config(cfg_file), rep)
    assert ready is False and any("Remove the password" in line for line in rep.lines)
    assert all("secret" not in line for line in rep.lines)
