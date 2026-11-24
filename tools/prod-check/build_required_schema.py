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
    lines = [
        "-- PROPOSAL ONLY. Nothing in this file has been run. Do not run it without the owner's approval.",
        "-- For whoever administers the McLabor SQL Server (a sysadmin), in SQL Server Management Studio.",
        "--",
        "-- What it does: creates ONE login that can only read approved columns of the McLabor database.",
        f"--   {len(tables)} tables, {n_cols} columns, read access only. It cannot change, add or remove anything,",
        "--   cannot run stored procedures, and cannot see any other table or database.",
        "-- What it does not do: it creates no tables, changes no data, and changes no server setting.",
        "--   This server already allows SQL logins (mixed mode), so no restart is needed.",
        "-- Never readable by this login: " + "; ".join(f"{t}: {', '.join(c)}" for t, c in sensitive.items()),
        "-- Safe to run twice: every step checks whether it was already done.",
        "",
        "-- STEP 1 - the login. Replace the password placeholder with a long password (16+ characters) typed here by you.",
        "--          Do not e-mail it or paste it into a chat. You will type it once more when the web app is configured.",
        "USE [master];",
        "-- SAFETY: this copy of the script is for the STAGING database on DEV-PC only. It stops on any other server.",
        "IF CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) <> N'DEV-PC\\SQLEXPRESS'",
        "BEGIN",
        "    RAISERROR('Wrong server. This script only runs on DEV-PC\\SQLEXPRESS (the restored copy). Nothing was created.', 16, 1);",
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
        "-- STEP 4 - check the result (read-only queries).",
        f"-- Expect {n_cols} column permissions on {len(tables)} tables, all SELECT:",
        "SELECT COUNT(*) AS column_permissions, COUNT(DISTINCT major_id) AS tables, MIN(permission_name) AS permission, MAX(permission_name) AS permission_check",
        "FROM sys.database_permissions WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(N'mclabor_web_readonly') AND class = 1;",
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
    (HERE / "proposed-grants.sql").write_text("\n".join(lines), encoding="utf-8")
    print(f"required_schema.json: {len(tables)} tables, {sum(len(c) for c in tables.values())} columns; sensitive columns listed: {sum(len(c) for c in sensitive.values())}")


if __name__ == "__main__":
    main()
