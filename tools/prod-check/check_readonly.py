"""Isolated READ-ONLY connection check for the McLabor SQL Server.

    backend\\.venv\\Scripts\\python.exe tools\\prod-check\\check_readonly.py --preflight   (no network at all)
    backend\\.venv\\Scripts\\python.exe tools\\prod-check\\check_readonly.py               (connects, read-only)

What it does
  * Connects once with ApplicationIntent=ReadOnly, asks the server about ITSELF
    (version, who am I, which tables/columns/permissions do I have), then disconnects.
  * Reads metadata only. It never selects a row from any business table, so no
    employee, customer or payroll record leaves the server.
  * Every statement must pass an allow-list (single SELECT, no INTO/EXEC/DDL/DML).

What it does not do
  * It does not import the web app, read backend/.env, or change DATA_SOURCE.
    The running demo is unaffected.
  * It does not create logins, change server settings, or open ports.
  * It never stores the password: SQL-login passwords are typed at a hidden prompt.

Settings come from tools/prod-check/prodcheck.env (copy prodcheck.env.example).
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "prodcheck.env"
REQUIRED = HERE / "required_schema.json"

TYPE_FAMILIES = {
    "bool": {"bit"},
    "int": {"int", "smallint", "tinyint", "bigint"},
    "datetime": {"datetime", "datetime2", "smalldatetime", "datetimeoffset"},
    "date": {"date", "datetime", "datetime2", "smalldatetime"},
    "number": {"money", "smallmoney", "decimal", "numeric", "float", "real"},
    "text": {"nvarchar", "varchar", "ntext", "text", "nchar", "char", "uniqueidentifier"},
}

_FORBIDDEN = re.compile(r"\b(into|insert|update|delete|merge|exec|execute|drop|alter|create|truncate|grant|revoke|deny|backup|restore|dbcc|shutdown|openrowset|xp_\w+|sp_\w+)\b", re.I)


class UnsafeStatement(RuntimeError):
    pass


def assert_read_only(sql: str) -> None:
    """Allow one plain SELECT. Anything that could write, run code or change settings is refused."""
    bare = re.sub(r"'[^']*'", "''", sql)  # permission names such as 'INSERT' are passed as text, not executed
    if ";" in bare or "--" in bare or "/*" in bare:
        raise UnsafeStatement("Only a single statement without comments is allowed")
    if not re.match(r"^\s*select\b", bare, re.I):
        raise UnsafeStatement("Only SELECT statements are allowed")
    hit = _FORBIDDEN.search(bare)
    if hit:
        raise UnsafeStatement(f"Keyword not allowed in the read-only check: {hit.group(1)}")


def load_config(path: Path = CONFIG) -> dict[str, str]:
    cfg: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip().upper()] = v.strip()
    return cfg


def sql_drivers() -> list[str]:
    try:
        import pyodbc
    except ImportError:
        return []
    return [d for d in pyodbc.drivers() if "SQL Server" in d]


def pick_driver(cfg: dict[str, str], drivers: list[str]) -> str | None:
    if cfg.get("DRIVER"):
        return cfg["DRIVER"]
    modern = sorted((d for d in drivers if re.fullmatch(r"ODBC Driver \d+ for SQL Server", d)), key=lambda d: int(re.findall(r"\d+", d)[0]))
    return modern[-1] if modern else None


def yes(v: str | None, default: bool) -> bool:
    return default if v is None or v == "" else v.strip().lower() in ("yes", "true", "1", "y")


def build_connection_string(cfg: dict[str, str], driver: str, password: str | None) -> str:
    parts = [
        "DRIVER={" + driver + "}",
        f"SERVER={cfg['SERVER']}",
        f"DATABASE={cfg.get('DATABASE', 'McLabor')}",
        "ApplicationIntent=ReadOnly",
        "APP=MC Labor read-only check",
        f"Encrypt={'yes' if yes(cfg.get('ENCRYPT'), True) else 'no'}",
        f"TrustServerCertificate={'yes' if yes(cfg.get('TRUST_SERVER_CERTIFICATE'), False) else 'no'}",
    ]
    if cfg.get("AUTH", "windows").lower() == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={cfg['USER']}", "PWD={" + (password or "").replace("}", "}}") + "}"]
    return ";".join(parts)


def mask(text: str, secret: str | None) -> str:
    text = re.sub(r"PWD=\{.*?\}(?=;|$)", "PWD=***", text)
    return text.replace(secret, "***") if secret else text


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.fails = 0
        self.warns = 0

    def head(self, title: str) -> None:
        self.say("")
        self.say(title)
        self.say("-" * len(title))

    def say(self, text: str = "") -> None:
        self.lines.append(text)
        print(text)

    def ok(self, text: str) -> None:
        self.say(f"  [ OK ] {text}")

    def warn(self, text: str) -> None:
        self.warns += 1
        self.say(f"  [WARN] {text}")

    def fail(self, text: str) -> None:
        self.fails += 1
        self.say(f"  [FAIL] {text}")

    def info(self, text: str) -> None:
        self.say(f"         {text}")


def explain_connection_error(message: str, cfg: dict[str, str]) -> list[str]:
    m = message.lower()
    if "im002" in m or "data source name not found" in m:
        return ["The ODBC driver name is wrong or not installed. Run with --preflight to see the installed drivers."]
    if "certificate" in m or "ssl provider" in m:
        return ["The server answered, but its encryption certificate is not trusted by this PC (normal for a server with no certificate installed:",
                "SQL Server then uses a temporary 'SSL_Self_Signed_Fallback' certificate that no client can verify).",
                "Proper fix (needs approval and an administrator): install a certificate named after the server - see docs/production-connection-report.md.",
                "Run tools\\prod-check\\inspect_certificate.py to see the certificate. TRUST_SERVER_CERTIFICATE=yes skips verification; use it only if the owner approves."]
    if "18456" in m or "login failed" in m:
        return ["The server answered and refused this login: wrong user name/password, the login does not exist, or (for a SQL login) the server only allows Windows logins.",
                "Nothing is wrong with the network. Whoever administers SQL Server must provide an approved login."]
    if "18452" in m or "untrusted domain" in m or "sspi" in m:
        return ["Windows authentication cannot be used from this PC: it is not signed in with an account the SQL Server trusts (different domain or workgroup).",
                "Use a dedicated SQL login instead (AUTH=sql), which the SQL Server administrator must create."]
    if "4060" in m or "cannot open database" in m:
        return [f"The login works, but it has no access to the database '{cfg.get('DATABASE', 'McLabor')}' (or the name is different)."]
    if "08001" in m or "not found" in m or "timeout" in m or "timed out" in m or "53" in m or "network-related" in m or "tcp provider" in m:
        return ["This PC could not reach the SQL Server. Usual causes, in order:",
                "  1. The SERVER name in prodcheck.env is not exactly what Access uses (include the \\INSTANCE part, if any).",
                "  2. This PC is not on the office network / VPN.",
                "  3. The server does not accept network (TCP/IP) connections, or a firewall blocks it.",
                "Do not change server or firewall settings yourself - report this result first."]
    return ["Unrecognised error. Send the report file - it contains no password."]


def preflight(cfg: dict[str, str], rep: Report) -> tuple[bool, str | None]:
    rep.head("1. This PC (no network used)")
    try:
        import pyodbc

        rep.ok(f"pyodbc {pyodbc.version} is installed (Python {sys.version_info.major}.{sys.version_info.minor}, {'64' if sys.maxsize > 2**32 else '32'}-bit)")
    except ImportError:
        rep.fail("pyodbc is not installed in this Python. Run the command with backend\\.venv\\Scripts\\python.exe")
        return False, None
    drivers = sql_drivers()
    driver = pick_driver(cfg, drivers)
    rep.info("SQL Server ODBC drivers installed: " + (", ".join(drivers) or "none"))
    if driver is None or driver not in drivers:
        rep.fail("No 'ODBC Driver 17/18 for SQL Server' found. It must be installed (Microsoft download, needs approval) before any check.")
        return False, None
    rep.ok(f"Will use: {driver}")
    if driver in ("SQL Server", "SQL Server Native Client 11.0"):
        rep.warn("That driver is deprecated. Prefer 'ODBC Driver 17 for SQL Server' or newer.")

    domain = os.environ.get("USERDNSDOMAIN")
    rep.info(f"Windows sign-in: {os.environ.get('USERDOMAIN', '?')}\\{os.environ.get('USERNAME', '?')}"
             + (f" (domain {domain})" if domain else " (local account - this PC is not signed in to a Windows domain)"))

    rep.head("2. Settings in prodcheck.env")
    if not CONFIG.exists():
        rep.fail("prodcheck.env not found. Copy prodcheck.env.example to prodcheck.env and fill in SERVER.")
        return False, driver
    if "PASSWORD" in cfg or "PWD" in cfg:
        rep.fail("Remove the password from prodcheck.env. Passwords are never stored in a file - you will be asked to type it.")
        return False, driver
    if not cfg.get("SERVER"):
        rep.fail("SERVER is empty. Enter the SQL Server name exactly as the Access application uses it.")
        return False, driver
    auth = cfg.get("AUTH", "windows").lower()
    if auth not in ("windows", "sql"):
        rep.fail("AUTH must be 'windows' or 'sql'.")
        return False, driver
    if auth == "sql" and not cfg.get("USER"):
        rep.fail("AUTH=sql needs USER (the approved read-only login name).")
        return False, driver
    env = cfg.get("ENVIRONMENT", "").lower()
    if env not in ("staging", "production"):
        rep.fail("ENVIRONMENT must be 'staging' (a restored copy) or 'production' (the live database).")
        return False, driver
    rep.ok(f"Environment: {env.upper()}   Server: {cfg['SERVER']}   Database: {cfg.get('DATABASE', 'McLabor')}   Sign-in: {'Windows account' if auth == 'windows' else 'SQL login ' + cfg['USER']}")
    rep.info(f"Encrypt={'yes' if yes(cfg.get('ENCRYPT'), True) else 'no'}  TrustServerCertificate={'yes' if yes(cfg.get('TRUST_SERVER_CERTIFICATE'), False) else 'no'}")
    if auth == "windows" and not domain:
        local = cfg["SERVER"].split("\\")[0].split(",")[0].lower() in ("localhost", ".", "(local)", "127.0.0.1", os.environ.get("COMPUTERNAME", "").lower())
        if not local:
            rep.warn("AUTH=windows from a PC that is not in a Windows domain normally fails against another computer. Expect to need AUTH=sql.")
    return True, driver


def run(cfg: dict[str, str], driver: str, rep: Report, required: dict) -> None:
    import pyodbc

    auth = cfg.get("AUTH", "windows").lower()
    password = None
    if auth == "sql":
        password = os.environ.get("PRODCHECK_PASSWORD") or getpass.getpass(f"Password for SQL login {cfg['USER']} (typing is hidden): ")

    rep.head("3. Connection")
    host = cfg["SERVER"].split("\\")[0]
    if "," in host and "\\" not in cfg["SERVER"]:
        name, port = host.split(",", 1)
        try:
            with socket.create_connection((name.strip(), int(port)), timeout=5):
                rep.ok(f"TCP port {port.strip()} on {name.strip()} is reachable")
        except OSError as exc:
            rep.warn(f"TCP port {port.strip()} on {name.strip()} did not answer ({exc.__class__.__name__}).")
    try:
        conn = pyodbc.connect(build_connection_string(cfg, driver, password), timeout=10, autocommit=False, readonly=True)
    except pyodbc.Error as exc:
        rep.fail("Could not connect.")
        rep.info(mask(" ".join(str(a) for a in exc.args), password)[:400])
        for line in explain_connection_error(" ".join(str(a) for a in exc.args), cfg):
            rep.info(line)
        return
    conn.timeout = 30
    cur = conn.cursor()

    def q(sql: str, *params):
        assert_read_only(sql)
        return cur.execute(sql, *params).fetchall()

    try:
        ver, edition, db, login, updateability = q(
            "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(50)), CAST(SERVERPROPERTY('Edition') AS nvarchar(100)), DB_NAME(), SUSER_SNAME(), "
            "CAST(DATABASEPROPERTYEX(DB_NAME(), 'Updateability') AS nvarchar(30))")[0]
        actual_server = q("SELECT CAST(SERVERPROPERTY('ServerName') AS nvarchar(128))")[0][0]
        expected_server = cfg.get("EXPECT_SERVER_NAME", "").strip()
        if not expected_server:
            rep.warn(f"EXPECT_SERVER_NAME is not set in prodcheck.env. The server that answered calls itself {actual_server!r}.")
        elif (actual_server or "").lower() != expected_server.lower():
            rep.fail(f"WRONG SERVER: expected {expected_server!r} ({cfg.get('ENVIRONMENT', '?')} environment) but {actual_server!r} answered. Stopping.")
            return
        else:
            rep.ok(f"The server identifies itself as {actual_server} - the expected {cfg.get('ENVIRONMENT', '?')} server")
        rep.ok(f"Connected to database '{db}' as '{login}'")
        rep.info(f"SQL Server {ver} ({edition}); database is {updateability}")
        try:
            scheme, encrypted, transport = q("SELECT auth_scheme, encrypt_option, net_transport FROM sys.dm_exec_connections WHERE session_id = @@SPID")[0]
            rep.info(f"Sign-in method: {scheme}; encrypted: {encrypted}; transport: {transport}")
            if str(encrypted).upper() != "TRUE":
                rep.warn("The connection is not encrypted. Keep ENCRYPT=yes.")
        except pyodbc.Error:
            rep.info("(connection details not visible to this login - fine)")

        rep.head("4. Is the login restricted? (it should only be able to read approved columns)")
        sysadmin, owner, writer, ddl, reader = q("SELECT IS_SRVROLEMEMBER('sysadmin'), IS_ROLEMEMBER('db_owner'), IS_ROLEMEMBER('db_datawriter'), "
                                                 "IS_ROLEMEMBER('db_ddladmin'), IS_ROLEMEMBER('db_datareader')")[0]
        for flag, name in ((sysadmin, "server administrator (sysadmin)"), (owner, "database owner (db_owner)"), (writer, "db_datawriter"), (ddl, "db_ddladmin")):
            if flag == 1:
                rep.fail(f"This login is a {name}. It can change data. Do not use it for the web app.")
        if reader == 1:
            rep.warn("This login is in db_datareader: it can read EVERY table, including the sensitive columns. A column-restricted role is preferred.")
        dbperm = q("SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'INSERT'), HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'UPDATE'), HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'DELETE'), "
                   "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'ALTER'), HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'EXECUTE'), HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CONTROL')")[0]
        bad = [n for n, f in zip(("INSERT", "UPDATE", "DELETE", "ALTER", "EXECUTE", "CONTROL"), dbperm) if f == 1]
        if bad:
            rep.fail("Database-wide permissions beyond reading: " + ", ".join(bad))
        else:
            rep.ok("No database-wide write, alter or execute permission")

        tables = required["tables"]
        schema = required.get("schema", "dbo")
        writable, unreadable = [], []
        for t in tables:
            sel, ins, upd, dele = q("SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', 'SELECT'), HAS_PERMS_BY_NAME(?, 'OBJECT', 'INSERT'), HAS_PERMS_BY_NAME(?, 'OBJECT', 'UPDATE'), "
                                    "HAS_PERMS_BY_NAME(?, 'OBJECT', 'DELETE')", *([f"{schema}.{t}"] * 4))[0]
            if 1 in (ins, upd, dele):
                writable.append(t)
            if sel is None:
                unreadable.append(t)
        if writable:
            rep.fail(f"The login can modify {len(writable)} table(s): " + ", ".join(writable[:8]) + (" ..." if len(writable) > 8 else ""))
        else:
            rep.ok(f"No INSERT/UPDATE/DELETE permission on any of the {len(tables)} tables the app uses")

        exposed = []
        for t, cols in required.get("sensitive_columns", {}).items():
            for c in cols:
                if q("SELECT HAS_PERMS_BY_NAME(?, 'OBJECT', 'SELECT', ?, 'COLUMN')", f"{schema}.{t}", c)[0][0] == 1:
                    exposed.append(f"{t}.{c}")
        if exposed:
            rep.fail(f"{len(exposed)} sensitive column(s) are readable by this login (they must stay hidden): " + ", ".join(exposed))
        else:
            rep.ok("Sensitive columns (SSN, bank details, date of birth, work-eligibility, staff passwords) are NOT readable")

        server_roles = ("sysadmin", "securityadmin", "serveradmin", "setupadmin", "processadmin", "diskadmin", "dbcreator", "bulkadmin")
        flags = q("SELECT " + ", ".join(f"IS_SRVROLEMEMBER('{r}')" for r in server_roles))[0]
        in_roles = [r for r, f in zip(server_roles, flags) if f == 1]
        if in_roles:
            rep.fail("The login is in server role(s) " + ", ".join(in_roles) + ": far too much. Do not use it.")
        else:
            rep.ok("Not a member of any fixed server role")
        routines = q("SELECT COUNT(*) FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id WHERE o.type IN ('P', 'PC', 'FN', 'IF', 'TF', 'FS', 'FT', 'X') "
                     "AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'EXECUTE') = 1")[0][0]
        if routines:
            rep.fail(f"The login can execute {routines} stored procedure(s)/function(s); it must execute none.")
        else:
            rep.ok("Cannot execute any stored procedure or function")
        other_writable = q("SELECT COUNT(*) FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id WHERE o.type IN ('U', 'V') AND ("
                           "HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'INSERT') = 1 OR HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'UPDATE') = 1 "
                           "OR HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'DELETE') = 1 OR HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'ALTER') = 1)")[0][0]
        if other_writable:
            rep.fail(f"The login can modify or alter {other_writable} table(s)/view(s) in the database (any table, not only the ones the app uses).")
        else:
            rep.ok("No INSERT/UPDATE/DELETE/ALTER permission on any table or view in the whole database")
        readable_cols = q("SELECT COUNT(*) FROM sys.columns c JOIN sys.objects o ON o.object_id = c.object_id WHERE o.name IN (" + ", ".join("?" for _ in tables) + ") "
                          "AND HAS_PERMS_BY_NAME(? + QUOTENAME(o.name), 'OBJECT', 'SELECT', c.name, 'COLUMN') = 1", *tables, f"{schema}.")[0][0]
        expected_cols = sum(len(c) for c in tables.values())
        if readable_cols == expected_cols:
            rep.ok(f"Readable columns on the approved tables: {readable_cols} (exactly the approved list)")
        elif readable_cols < expected_cols:
            rep.fail(f"Only {readable_cols} of the {expected_cols} approved columns are readable; the sync would be incomplete.")
        else:
            rep.warn(f"{readable_cols} columns are readable on the approved tables; the approved list has {expected_cols}. Access is wider than approved.")
        view_any = q("SELECT HAS_PERMS_BY_NAME(NULL, NULL, 'VIEW ANY DATABASE')")[0][0]
        if view_any == 1:
            rep.warn("The login can list every database on the server (VIEW ANY DATABASE). Harmless but wider than needed; the grant script denies it.")
        else:
            rep.ok("Cannot list other databases on the server")
        visible_tables = q("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ?", schema)[0][0]
        if visible_tables > len(tables):
            rep.warn(f"The login can see {visible_tables} tables/views; the app needs {len(tables)}. Access is wider than necessary.")
        else:
            rep.ok(f"The login sees {visible_tables} tables/views (the app needs {len(tables)})")

        rep.head("5. Schema compatibility (names and types only - no rows are read)")
        live: dict[str, dict[str, str]] = {}
        for t, c, typ in q("SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ?", schema):
            live.setdefault(t.lower(), {})[c.lower()] = typ.lower()
        missing_tables = [t for t in tables if t.lower() not in live]
        missing_cols, wrong_types, checked = [], [], 0
        for t, cols in tables.items():
            have = live.get(t.lower())
            if have is None:
                continue
            for c, fam in cols.items():
                checked += 1
                typ = have.get(c.lower())
                if typ is None:
                    missing_cols.append(f"{t}.{c}")
                elif typ not in TYPE_FAMILIES[fam]:
                    wrong_types.append(f"{t}.{c} (app expects {fam}, server has {typ})")
        for label, items in (("table(s) missing or not readable", missing_tables), ("column(s) missing or not readable", missing_cols), ("column type difference(s)", wrong_types)):
            if items:
                rep.fail(f"{len(items)} {label}: " + ", ".join(items[:12]) + (" ..." if len(items) > 12 else ""))
        if not (missing_tables or missing_cols or wrong_types):
            rep.ok(f"All {len(tables)} tables and {checked} columns the app needs exist with compatible types")
        used = required.get("withheld_but_used_by_demo", {})
        if used:
            rep.info("Note: the demo screens also show " + "; ".join(f"{t}: {', '.join(c)}" for t, c in used.items())
                     + ". These stay hidden in production until the owner approves them.")
    except UnsafeStatement as exc:
        rep.fail(f"Internal safety stop: {exc}")
    except pyodbc.Error as exc:
        rep.fail("A read-only metadata query failed: " + mask(" ".join(str(a) for a in exc.args), password)[:300])
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()
        rep.say("")
        rep.say("  Disconnected. Nothing was written and no table rows were read.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Isolated read-only check of the McLabor SQL Server connection.")
    ap.add_argument("--preflight", action="store_true", help="check this PC and the settings only; do not touch the network")
    ap.add_argument("--config", help="settings file to use instead of prodcheck.env")
    args = ap.parse_args(argv)
    if args.config:
        global CONFIG
        CONFIG = Path(args.config)

    rep = Report()
    rep.say("MC Labor - read-only SQL Server connection check")
    rep.say(dt.datetime.now().strftime("%Y-%m-%d %H:%M") + ("   (preflight: no network)" if args.preflight else ""))
    cfg = load_config(CONFIG)
    ready, driver = preflight(cfg, rep)
    if ready and driver and not args.preflight:
        run(cfg, driver, rep, json.loads(REQUIRED.read_text(encoding="utf-8")))

    rep.head("Result")
    if rep.fails:
        rep.say(f"  NOT READY - {rep.fails} problem(s), {rep.warns} warning(s). See [FAIL] lines above.")
    elif args.preflight or not ready:
        rep.say(f"  This PC is ready for the check ({rep.warns} warning(s)). Run again without --preflight to connect.")
    else:
        rep.say(f"  READ-ONLY CONNECTION VERIFIED ({rep.warns} warning(s)).")
    out = HERE / "reports"
    out.mkdir(exist_ok=True)
    path = out / f"prodcheck-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    path.write_text("\n".join(rep.lines) + "\n", encoding="utf-8")
    print(f"\nReport saved (contains no password): {path}")
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
