"""Developer tool: regenerate required_schema.json and proposed-grants.sql from the app's models.

    backend\\.venv\\Scripts\\python.exe tools\\prod-check\\build_required_schema.py

Runs offline in demo mode. It never connects to SQL Server. The read-only check
(check_readonly.py) only reads the generated JSON, so it stays independent of the app.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))
os.environ["DATA_SOURCE"] = "demo"

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric  # noqa: E402

from app import models  # noqa: E402,F401
from app.database import Base  # noqa: E402
from app.production import PRODUCTION_MAPPED  # noqa: E402

# Columns a restricted web login must NOT be able to read. The first group is used by the
# demo app today and is deliberately withheld; the second group is never used by the app.
WITHHELD_FROM_APP = {
    "tblEmployee": ["EmDOB", "USCitizen", "I9Complete"],
    "tblOfficeStaff": ["OfficeStaffPassword"],
}
NEVER_NEEDED = {
    "tblEmployee": ["SSNum", "BankName", "BankRoutingNumber", "BankAccountNumber", "BankAccountTypeID", "BankAccountActionID",
                    "Dependents", "Citizenship", "EmCountryOfBirth", "EmSex", "EmRaceID", "EmW4Notes", "EmI9Notes"],
}
# Production-only tables/columns the app reads instead of the demo-only columns.
PRODUCTION_EXTRA = {
    "tblEmployee": {"YearsInTradeID": "int"},
    "tblEmployeeB": {"EmployeeID": "int", "WillTravel": "text"},
    "tblPullDownYearsInTrade": {"PullDownYearsInTradeID": "int", "PullDownYearsInTrade": "text"},
}


def family(sa_type) -> str:
    if isinstance(sa_type, Boolean):
        return "bool"
    if isinstance(sa_type, Integer):
        return "int"
    if isinstance(sa_type, DateTime):
        return "datetime"
    if isinstance(sa_type, Date):
        return "date"
    if isinstance(sa_type, (Numeric, Float)):
        return "number"
    return "text"


def main() -> None:
    tables: dict[str, dict[str, str]] = {}
    for t in Base.metadata.sorted_tables:
        skip = set(PRODUCTION_MAPPED.get(t.name, {})) | set(WITHHELD_FROM_APP.get(t.name, []))
        tables[t.name] = {c.name: family(c.type) for c in t.columns if c.name not in skip}
    for t, cols in PRODUCTION_EXTRA.items():
        tables.setdefault(t, {}).update(cols)
    tables = {t: dict(sorted(c.items())) for t, c in sorted(tables.items())}

    sensitive = {t: sorted(set(WITHHELD_FROM_APP.get(t, []) + NEVER_NEEDED.get(t, []))) for t in sorted(set(WITHHELD_FROM_APP) | set(NEVER_NEEDED))}
    out = {"database": "McLabor", "schema": "dbo", "tables": tables, "sensitive_columns": sensitive, "withheld_but_used_by_demo": WITHHELD_FROM_APP}
    (HERE / "required_schema.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    n_cols = sum(len(c) for c in tables.values())
    n_sensitive = sum(len(c) for c in sensitive.values())
    for variant in ("staging", "production"):
        (HERE / ("proposed-grants.sql" if variant == "staging" else "proposed-grants-production.sql")).write_text(
            "\n".join(grant_script(variant, tables, sensitive, n_cols, n_sensitive)), encoding="utf-8")
    (HERE / "verify-readonly-login.sql").write_text("\n".join(verify_script(tables, sensitive, n_cols)), encoding="utf-8")
    print(f"required_schema.json: {len(tables)} tables, {n_cols} columns; sensitive columns listed: {n_sensitive}")
    print("proposed-grants.sql, proposed-grants-production.sql, verify-readonly-login.sql regenerated")


# Database-level permissions the role is explicitly REFUSED. A DENY always wins over a GRANT in SQL Server, also over
# rights that arrive later through a role membership, so the account can never write, change or execute anything,
# whatever is granted to it in the future. (CONTROL is not denied: denying it would also deny SELECT.)
DENIED_ON_DATABASE = ("INSERT", "UPDATE", "DELETE", "EXECUTE", "ALTER", "REFERENCES", "CREATE TABLE", "CREATE VIEW", "CREATE PROCEDURE",
                      "CREATE FUNCTION", "CREATE SCHEMA", "CREATE TYPE", "ALTER ANY SCHEMA", "ALTER ANY USER", "ALTER ANY ROLE",
                      "TAKE OWNERSHIP", "BACKUP DATABASE", "BACKUP LOG")
SERVER_ROLES = ("sysadmin", "securityadmin", "serveradmin", "setupadmin", "processadmin", "diskadmin", "dbcreator", "bulkadmin")


def grant_script(variant: str, tables: dict, sensitive: dict, n_cols: int, n_sensitive: int) -> list[str]:
    """The T-SQL that creates the strictly read-only login: for the restored copy (staging) or the live server (production)."""
    if variant == "production":
        server, what = "LIVE-HOST\\SQLEXPRESS", "the live database"
        header = [
            "-- PROPOSAL ONLY for the LIVE server. Nothing in this file has been run. Needs: the owner's approval for this exact step, the",
            "-- live database confirmed (docs/production/15), a restore-tested backup, and a sysadmin on the live server. No downtime: it creates one",
            f"-- login, one user, one role, {n_cols} column permissions and the explicit refusals; it changes no data, no setting and no existing permission.",
        ]
    else:
        server, what = "DEV-PC\\SQLEXPRESS", "the restored copy"
        header = ["-- PROPOSAL ONLY. Nothing in this file has been run. Do not run it without the owner's approval."]
    lines = header + [
        "-- For whoever administers the McLabor SQL Server (a sysadmin), in SQL Server Management Studio.",
        "--",
        "-- What it does: creates ONE login that can only read approved columns of the McLabor database.",
        f"--   {len(tables)} tables, {n_cols} columns, read access only. It cannot change, add or remove anything,",
        "--   cannot run stored procedures, and cannot see any other table or database.",
        "--   STEP 3b adds explicit DENYs so that no later GRANT or role membership can ever give it a write right.",
        "-- What it does not do: it creates no tables, changes no data, and changes no server setting.",
        "--   This server already allows SQL logins (mixed mode), so no restart is needed.",
        "-- Never readable by this login: " + "; ".join(f"{t}: {', '.join(c)}" for t, c in sensitive.items()),
        "-- Safe to run twice: every step checks whether it was already done.",
        "-- Afterwards, run verify-readonly-login.sql (read-only) to see the effective permissions of the new login.",
        "",
        "-- STEP 1 - the login. Replace the password placeholder with a long password (16+ characters) typed here by you.",
        "--          Do not e-mail it or paste it into a chat. You will type it once more when the web app is configured.",
        "USE [master];",
        f"-- SAFETY: this copy of the script is for {what} only. It stops on any other server.",
        f"-- {server.split(chr(92))[0]} is a placeholder: replace it with the computer name of {what} before running (the office notes have it).",
        f"IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'{server}'",
        "BEGIN",
        f"    RAISERROR('Wrong server. This script only runs on {server} ({what}). Nothing was created.', 16, 1);",
        "    SET NOEXEC ON;",
        "END",
        "DECLARE @password nvarchar(128) = N'<<TYPE-A-LONG-PASSWORD-HERE>>';",
        "IF @password LIKE N'%TYPE-A-LONG-PASSWORD%' OR LEN(@password) < 16",
        "BEGIN",
        "    RAISERROR('Replace the password placeholder with your own password of 16 or more characters. Nothing was created.', 16, 1);",
        "    SET NOEXEC ON;  -- skips every remaining step of this script",
        "END",
        "IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'mclabor_web_read')",
        "BEGIN",
        "    DECLARE @sql nvarchar(max) = N'CREATE LOGIN [mclabor_web_read] WITH PASSWORD = ' + QUOTENAME(@password, '''')",
        "        + N', CHECK_POLICY = ON, CHECK_EXPIRATION = OFF, DEFAULT_DATABASE = [McLabor]';",
        "    EXEC (@sql);",
        "END",
        "-- The login may not list or enter other databases (its default database is McLabor; CONNECT to others is never granted).",
        "DENY VIEW ANY DATABASE TO [mclabor_web_read];",
        "GO",
        "-- (Alternative instead of STEP 1, no password to manage: a dedicated local Windows account that runs the web app.",
        "--  CREATE LOGIN [DEV-PC\\mclabor_web] FROM WINDOWS WITH DEFAULT_DATABASE = [McLabor];",
        "--  then use [DEV-PC\\mclabor_web] in place of the login name in STEP 2. That Windows account must be created first.)",
        "",
        "-- STEP 2 - a database user for that login, and a role that holds the read permissions.",
        "USE [McLabor];",
        "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'mclabor_web_read')",
        "    CREATE USER [mclabor_web_read] FOR LOGIN [mclabor_web_read];",
        "IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'mclabor_web_readonly' AND type = 'R')",
        "    CREATE ROLE [mclabor_web_readonly];",
        "IF IS_ROLEMEMBER(N'mclabor_web_readonly', N'mclabor_web_read') = 0",
        "    ALTER ROLE [mclabor_web_readonly] ADD MEMBER [mclabor_web_read];",
        "GO",
        "-- Do NOT add this user to db_datareader, db_datawriter or db_owner.",
        "",
        "-- STEP 3 - read access, column by column.",
    ]
    for t, cols in tables.items():
        lines.append(f"GRANT SELECT ON dbo.[{t}] ({', '.join(f'[{c}]' for c in cols)}) TO [mclabor_web_readonly];")
    lines += [
        "GO",
        "",
        "-- STEP 3b - explicit refusals. A DENY wins over any GRANT, including rights inherited later through a role, so this",
        "--           role can never insert, update, delete, merge, alter, drop, create or execute anything in this database.",
        f"DENY {', '.join(DENIED_ON_DATABASE)} ON DATABASE::[McLabor] TO [mclabor_web_readonly];",
        "-- The sensitive columns are refused by name, so that even a future table-wide GRANT SELECT could not expose them:",
    ]
    for t, cols in sensitive.items():
        lines.append(f"DENY SELECT ON dbo.[{t}] ({', '.join(f'[{c}]' for c in cols)}) TO [mclabor_web_readonly];")
    lines += [
        "GO",
        "",
        "-- STEP 4 - check the result (read-only queries).",
        f"-- Expect {n_cols} SELECT column permissions on {len(tables)} tables:",
        "SELECT COUNT(*) AS select_column_permissions, COUNT(DISTINCT major_id) AS tables",
        "FROM sys.database_permissions WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'mclabor_web_readonly') AND class = 1 AND state = 'G' AND permission_name = 'SELECT';",
        f"-- Expect {len(DENIED_ON_DATABASE)} database-level DENYs and {n_sensitive} column DENYs:",
        "SELECT SUM(CASE WHEN class = 0 THEN 1 ELSE 0 END) AS database_denies, SUM(CASE WHEN class = 1 THEN 1 ELSE 0 END) AS column_denies",
        "FROM sys.database_permissions WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'mclabor_web_readonly') AND state = 'D';",
        "-- Expect 0 rows (the user must not be in any built-in role):",
        "SELECT r.name AS unexpected_role FROM sys.database_role_members rm JOIN sys.database_principals r ON r.principal_id = rm.role_principal_id",
        "WHERE rm.member_principal_id = DATABASE_PRINCIPAL_ID(N'mclabor_web_read') AND r.name <> N'mclabor_web_readonly';",
        "GO",
        "",
        "SET NOEXEC OFF;",
        "GO",
        "",
        "-- TO UNDO EVERYTHING:",
        "-- USE [McLabor]; DROP USER [mclabor_web_read]; DROP ROLE [mclabor_web_readonly];",
        "-- USE [master];  DROP LOGIN [mclabor_web_read];",
        "",
    ]
    return lines


def verify_script(tables: dict, sensitive: dict, n_cols: int) -> list[str]:
    """Read-only T-SQL for the administrator: impersonates the login and prints its EFFECTIVE permissions.
    Runs no INSERT/UPDATE/DELETE, not even in a rolled-back transaction: it asks the server what it WOULD allow."""
    lines = [
        "-- READ-ONLY verification of the login's effective permissions. Run in SQL Server Management Studio as a sysadmin,",
        "-- on the server where proposed-grants(-production).sql was run. It changes nothing: it impersonates the login,",
        "-- asks the server what that login may do, and reverts. No business row is read.",
        "USE [McLabor];",
        "EXECUTE AS LOGIN = N'mclabor_web_read';",
        "SELECT SUSER_SNAME() AS running_as, USER_NAME() AS database_user, DB_NAME() AS database_name;",
        "",
        "-- 1. Server roles: every row must say 0.",
        "SELECT r.role_name, IS_SRVROLEMEMBER(r.role_name) AS is_member FROM (VALUES " + ", ".join(f"('{r}')" for r in SERVER_ROLES) + ") r(role_name);",
        "",
        "-- 2. Database roles: expect exactly one row, mclabor_web_readonly.",
        "SELECT r.name AS database_role FROM sys.database_role_members rm JOIN sys.database_principals r ON r.principal_id = rm.role_principal_id",
        "WHERE rm.member_principal_id = USER_ID();",
        "",
        "-- 3. Effective database-level permissions: expect CONNECT only.",
        "SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE') ORDER BY permission_name;",
        "",
        "-- 4. Server-level: expect CONNECT SQL only (VIEW ANY DATABASE must be absent).",
        "SELECT permission_name FROM fn_my_permissions(NULL, 'SERVER') ORDER BY permission_name;",
        "",
        "-- 5. Write rights on ANY table or view of the database: expect 0 rows.",
        "SELECT s.name + '.' + o.name AS object_name, p.permission_name",
        "FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id",
        "CROSS APPLY (SELECT 'INSERT' AS permission_name UNION ALL SELECT 'UPDATE' UNION ALL SELECT 'DELETE' UNION ALL SELECT 'ALTER' UNION ALL SELECT 'REFERENCES' UNION ALL SELECT 'CONTROL') p",
        "WHERE o.type IN ('U', 'V') AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', p.permission_name) = 1;",
        "",
        "-- 6. Executable procedures and functions (write-capable or not): expect 0.",
        "SELECT COUNT(*) AS executable_routines FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id",
        "WHERE o.type IN ('P', 'PC', 'FN', 'IF', 'TF', 'FS', 'FT', 'X') AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'EXECUTE') = 1;",
        "",
        f"-- 7. Readable columns across the {len(tables)} approved tables: expect {n_cols}.",
        "SELECT COUNT(*) AS readable_approved_columns FROM sys.columns c JOIN sys.objects o ON o.object_id = c.object_id",
        "WHERE o.name IN (" + ", ".join(f"N'{t}'" for t in tables) + ") AND HAS_PERMS_BY_NAME('dbo.' + QUOTENAME(o.name), 'OBJECT', 'SELECT', c.name, 'COLUMN') = 1;",
        "",
        "-- 8. Sensitive columns: every row must say 0.",
        "SELECT col.table_name + '.' + col.column_name AS sensitive_column, HAS_PERMS_BY_NAME('dbo.' + QUOTENAME(col.table_name), 'OBJECT', 'SELECT', col.column_name, 'COLUMN') AS readable",
        "FROM (VALUES " + ", ".join(f"(N'{t}', N'{c}')" for t, cols in sensitive.items() for c in cols) + ") col(table_name, column_name);",
        "",
        "-- 9. Tables outside the approved list that this login can read: expect 0 rows.",
        "SELECT s.name + '.' + o.name AS readable_unapproved FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id",
        "WHERE o.type IN ('U', 'V') AND o.name NOT IN (" + ", ".join(f"N'{t}'" for t in tables) + ")",
        "  AND HAS_PERMS_BY_NAME(QUOTENAME(s.name) + '.' + QUOTENAME(o.name), 'OBJECT', 'SELECT') = 1;",
        "",
        "-- 10. Other databases visible to this login: expect only master, tempdb and McLabor.",
        "SELECT name AS visible_database FROM sys.databases ORDER BY name;",
        "REVERT;",
        "",
    ]
    return lines


if __name__ == "__main__":
    main()
