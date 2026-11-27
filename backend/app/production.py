"""SQL Server (production McLabor database) adapter.

Safety model - production stays untouched until explicitly approved:

1. Off by default.  DATA_SOURCE=demo uses the local SQLite file.  A SQL Server
   URL is refused unless DATA_SOURCE=production (see database.make_engine).
2. Read-only by default.  With DATA_SOURCE=production the engine gets a guard
   that rejects every statement that is not SELECT / WITH / SET, before it
   reaches the server.  DDL (CREATE/ALTER/DROP/TRUNCATE...) is always rejected,
   even after approval.  Writes need BOTH PRODUCTION_WRITES_ENABLED=true and a
   PRODUCTION_WRITE_APPROVAL reference.  The connection also declares
   ApplicationIntent=ReadOnly while writes are off.  A db_datareader-only SQL
   login is still recommended as the outer layer of defence.
3. No schema changes, no seeding.  main.py only runs create_all/seed on SQLite.
4. Credentials come from backend/.env (never committed) and are never logged or
   returned by the API - describe() masks them.

The ORM models are checked against the client's schema export
(docs/schema/McLabor_Database_structure.csv + McLabor_table_relationship.csv)
offline, and against INFORMATION_SCHEMA on the live server (read-only) by
``python -m app.production check``.
"""
from __future__ import annotations

import csv
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import URL, Boolean, Date, DateTime, Float, Integer, Numeric, String, Text, event, text

from .config import settings

log = logging.getLogger("mclabor.production")

STRUCTURE_CSV = "McLabor_Database_structure.csv"
RELATIONSHIP_CSV = "McLabor_table_relationship.csv"

# Model attributes that are plain columns in the demo but are derived from other
# production tables when DATA_SOURCE=production (see models.py).  They are
# read-only in production mode.
PRODUCTION_MAPPED: dict[str, dict[str, str]] = {
    "tblEmployee": {
        "YearsInTrade": "from YearsInTradeID -> tblPullDownYearsInTrade",
        "WillTravel": "from tblEmployeeB.WillTravel",
    },
    "tblProject": {
        "SiteCity": "from SiteStateCityID -> tblPullDownStateCities.City",
        "SiteState": "from SiteStateCityID -> tblPullDownStates",
    },
}


def detect_driver() -> str | None:
    try:
        import pyodbc
    except ImportError:
        return None
    found = sorted((d for d in pyodbc.drivers() if re.fullmatch(r"ODBC Driver \d+ for SQL Server", d)), key=lambda d: int(re.findall(r"\d+", d)[0]))
    return found[-1] if found else None


def driver_name() -> str:
    return settings.db_driver or detect_driver() or "ODBC Driver 18 for SQL Server"


class ProductionWriteBlocked(RuntimeError):
    """Raised when a write is attempted on a SQL Server environment without approval."""


class WrongServer(RuntimeError):
    """Raised when the server that answered is not the one this environment is allowed to use."""


# --------------------------------------------------------------- connection
def build_sql_server_url() -> URL:
    """Connection URL for the ACTIVE environment (staging or production) - never the other one's settings."""
    s = settings
    env = s.environment.upper()
    if not s.is_sql_server:
        raise RuntimeError("DATA_SOURCE is 'demo': there is no SQL Server connection in this environment.")
    if not s.db_server:
        raise RuntimeError(f"DATA_SOURCE={s.environment} but {env}_DB_SERVER is not set in backend/.env")
    # Credentials go in the URL's username/password fields (masked by SQLAlchemy in
    # str()/repr()/logs) - never inside an odbc_connect string, which is not masked.
    query = {
        "driver": driver_name(),
        "Encrypt": "yes" if s.db_encrypt else "no",
        "TrustServerCertificate": "yes" if s.db_trust_server_certificate else "no",  # 'yes' only with the owner's TLS waiver (config rule)
        "APP": f"MC Labor Web {s.environment}" + (" (read-only)" if not s.sql_writes_allowed else ""),
        # cloud databases drop idle connections and have short transient outages: let the driver retry a lost
        # connection a few times before the website reports an error (ODBC Driver 17.1 and newer)
        "ConnectRetryCount": str(max(0, s.db_connect_retries)),
        "ConnectRetryInterval": "5",
    }
    if not s.sql_writes_allowed:
        query["ApplicationIntent"] = "ReadOnly"
    user = password = None
    if s.db_trusted_connection:
        query["Trusted_Connection"] = "yes"
    else:
        if not (s.db_user and s.db_password):
            raise RuntimeError(f"Set {env}_DB_USER and {env}_DB_PASSWORD in backend/.env, or {env}_DB_TRUSTED_CONNECTION=true")
        user, password = s.db_user, s.db_password
    host, _, port = s.db_server.partition(",")  # "server,1433" or "server\\INSTANCE"
    return URL.create(
        "mssql+pyodbc", username=user, password=password, host=host.strip(), port=int(port) if port.strip() else None,
        database=s.db_name, query=query,
    )


build_production_url = build_sql_server_url  # older name


def check_identity(actual_server: str | None, actual_database: str | None) -> None:
    """The server must call itself what this environment expects. Stops staging settings reaching the live
    server (and the reverse) even if an address or DNS name points somewhere unexpected."""
    expected = (settings.db_expected_server_name or "").strip()
    env = settings.environment
    if not expected:
        raise WrongServer(f"{env.upper()}_DB_EXPECTED_SERVER_NAME is not set; refusing to use the connection.")
    if (actual_server or "").strip().lower() != expected.lower():
        raise WrongServer(f"This is the {env} environment and may only use server '{expected}', but the server that answered is '{actual_server}'. Connection refused.")
    if (actual_database or "").strip().lower() != settings.db_name.strip().lower():
        raise WrongServer(f"This is the {env} environment and may only use database '{settings.db_name}', but the connection opened '{actual_database}'. Connection refused.")


def install_identity_check(engine) -> None:
    @event.listens_for(engine, "connect")
    def _identity(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        try:
            row = cur.execute("SELECT CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)), DB_NAME()").fetchone()
        finally:
            cur.close()
        check_identity(row[0], row[1])
        # every later statement on this connection is cancelled if it runs longer than the limit
        dbapi_conn.timeout = max(1, int(settings.query_timeout_seconds))


def describe() -> dict[str, Any]:
    """Configuration summary that is safe to show in the UI / logs (no secrets)."""
    s = settings
    try:
        import pyodbc  # noqa: F401

        drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
        pyodbc_ok = True
    except ImportError:
        drivers, pyodbc_ok = [], False
    if s.is_postgres:
        from sqlalchemy.engine import make_url

        u = make_url(s.postgres_url)
        return {
            "data_source": s.environment, "environment": s.environment, "environment_label": s.environment_label, "backend": "postgres",
            "server_configured": True, "server": f"{u.host}:{u.port or 5432}", "expected_server_name": None, "database": u.database,
            "auth": "password" if u.password else "none", "password_set": bool(u.password), "driver": "psycopg", "pyodbc_installed": False,
            "driver_installed": True, "sql_server_drivers_found": [], "writes_enabled": True, "write_approval_recorded": True, "writes_allowed": True,
            "shape": "production" if s.production_shape else "demo", "mode": f"{s.environment}: PostgreSQL, read-write",
        }
    mode = "demo (local SQLite)" if s.is_demo else f"{s.environment}: " + ("read-write (approved)" if s.sql_writes_allowed else "read-only")
    return {
        "backend": s.db_backend,
        "data_source": s.environment,
        "environment": s.environment,
        "environment_label": s.environment_label,
        "server_configured": bool(s.db_server),
        "server": s.db_server,
        "expected_server_name": s.db_expected_server_name,
        "database": s.db_name if s.is_sql_server else "mclabor_demo.db",
        "auth": "none (local file)" if s.is_demo else ("windows" if s.db_trusted_connection else ("sql login" if s.db_user else "not configured")),
        "password_set": bool(s.db_password),
        "driver": driver_name(),
        "pyodbc_installed": pyodbc_ok,
        "driver_installed": driver_name() in drivers,
        "sql_server_drivers_found": drivers,
        "writes_enabled": s.sql_writes_enabled,
        "write_approval_recorded": bool(s.sql_write_approval),
        "writes_allowed": s.sql_writes_allowed,
        "mode": mode,
    }

# --------------------------------------------------------------- write guard
_READ_ONLY = re.compile(r"^\s*(?:/\*.*?\*/\s*|--[^\n]*\n\s*)*(select|with|set)\b", re.I | re.S)
_DDL = re.compile(r"^\s*(?:/\*.*?\*/\s*|--[^\n]*\n\s*)*(create|alter|drop|truncate|grant|revoke|deny|exec|execute|dbcc|backup|restore)\b", re.I | re.S)


def check_statement(statement: str, writes_allowed: bool) -> None:
    if _DDL.match(statement):
        raise ProductionWriteBlocked("Schema/administrative statements are never sent to the production database by this app.")
    if not writes_allowed and not _READ_ONLY.match(statement):
        raise ProductionWriteBlocked(f"The {settings.environment} database is read-only for this app until writes are approved ({settings.environment.upper()}_WRITES_ENABLED + {settings.environment.upper()}_WRITE_APPROVAL).")


def install_write_guard(engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _guard(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        check_statement(statement, settings.sql_writes_allowed)


def writes_allowed() -> bool:
    """True when the current data source accepts writes (the demo; PostgreSQL unless the site is a search-only mirror;
    SQL Server only with the approved write switch)."""
    return settings.writes_allowed


# --------------------------------------------------------------- schema check
_COMPATIBLE: list[tuple[type, set[str]]] = [
    (Boolean, {"bit"}),
    (Integer, {"int", "smallint", "tinyint", "bigint"}),
    (DateTime, {"datetime", "datetime2", "smalldatetime", "datetimeoffset"}),
    (Date, {"date", "datetime", "datetime2", "smalldatetime"}),
    (Numeric, {"money", "smallmoney", "decimal", "numeric", "float", "real"}),
    (Float, {"money", "smallmoney", "decimal", "numeric", "float", "real"}),
    (Text, {"nvarchar", "varchar", "ntext", "text", "nchar", "char"}),
    (String, {"nvarchar", "varchar", "ntext", "text", "nchar", "char", "uniqueidentifier"}),
]


def _compatible(sa_type: Any, sql_type: str) -> bool:
    for cls, ok in _COMPATIBLE:
        if isinstance(sa_type, cls):
            return sql_type.lower() in ok
    return True


@dataclass
class SchemaReport:
    source: str
    tables_checked: int = 0
    columns_checked: int = 0
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: dict[str, list[str]] = field(default_factory=dict)
    type_mismatches: list[str] = field(default_factory=list)
    mapped_columns: list[str] = field(default_factory=list)
    unknown_relationships: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing_tables or self.missing_columns or self.type_mismatches)

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "ok": self.ok}


def load_structure_csv(path: Path) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = defaultdict(dict)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if len(row) >= 4:
                _schema, table, column, sql_type = (x.strip() for x in row[:4])
                tables[table.lower()][column.lower()] = sql_type
    return tables


def load_relationship_csv(path: Path) -> set[tuple[str, str, str, str]]:
    rels = set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if len(row) >= 7:
                rels.add((row[2].strip().lower(), row[3].strip().lower(), row[5].strip().lower(), row[6].strip().lower()))
    return rels


def compare_models(structure: dict[str, dict[str, str]], relationships: set | None, source: str) -> SchemaReport:
    from . import models  # noqa: F401 - registers the tables on Base.metadata
    from .database import Base

    rep = SchemaReport(source=source)
    if not Base.metadata.sorted_tables:
        raise RuntimeError("No ORM tables registered - schema comparison would be meaningless")
    for table in Base.metadata.sorted_tables:
        rep.tables_checked += 1
        cols = structure.get(table.name.lower())
        if cols is None:
            rep.missing_tables.append(table.name)
            continue
        for col in table.columns:
            rep.columns_checked += 1
            sql_type = cols.get(col.name.lower())
            if sql_type is None:
                how = PRODUCTION_MAPPED.get(table.name, {}).get(col.name)
                if how:
                    rep.mapped_columns.append(f"{table.name}.{col.name} ({how})")
                else:
                    rep.missing_columns.setdefault(table.name, []).append(col.name)
                continue
            if not _compatible(col.type, sql_type):
                rep.type_mismatches.append(f"{table.name}.{col.name}: model {col.type} vs server {sql_type}")
            if relationships is not None:
                for fk in col.foreign_keys:
                    key = (table.name.lower(), col.name.lower(), fk.column.table.name.lower(), fk.column.name.lower())
                    if key not in relationships:
                        rep.unknown_relationships.append(f"{table.name}.{col.name} -> {fk.column.table.name}.{fk.column.name}")
    return rep


def validate_against_csv(directory: str | Path | None = None) -> SchemaReport:
    d = Path(directory or settings.schema_csv_dir)
    structure_path, rel_path = d / STRUCTURE_CSV, d / RELATIONSHIP_CSV
    if not structure_path.exists():
        rep = SchemaReport(source=f"{structure_path} (missing)")
        rep.missing_tables.append(f"schema export not found at {structure_path}")
        return rep
    rels = load_relationship_csv(rel_path) if rel_path.exists() else None
    return compare_models(load_structure_csv(structure_path), rels, source=f"CSV export ({structure_path.name})")


def validate_live(engine) -> SchemaReport:
    """Compare the models with INFORMATION_SCHEMA on the connected server (SELECT only)."""
    structure: dict[str, dict[str, str]] = defaultdict(dict)
    with engine.connect() as conn:
        for table, column, sql_type in conn.execute(text(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo'"
        )):
            structure[table.lower()][column.lower()] = sql_type
        conn.rollback()
    return compare_models(structure, None, source="live server INFORMATION_SCHEMA")


# --------------------------------------------------------------- CLI
def _print_report(rep: SchemaReport) -> None:
    print(f"Schema check against {rep.source}: {'OK' if rep.ok else 'DIFFERENCES FOUND'}")
    print(f"  tables checked: {rep.tables_checked}, columns checked: {rep.columns_checked}")
    for t in rep.missing_tables:
        print(f"  missing table: {t}")
    for t, cols in rep.missing_columns.items():
        print(f"  {t}: columns not in production schema: {', '.join(cols)}")
    for mm in rep.type_mismatches:
        print(f"  type mismatch: {mm}")
    for mc in rep.mapped_columns:
        print(f"  mapped for production: {mc}")
    if rep.unknown_relationships:
        print(f"  note: {len(rep.unknown_relationships)} relationships used by the app are not enforced as foreign keys on the server -")
        print("        the app validates these references itself before saving:")
    for r in rep.unknown_relationships:
        print(f"    {r}")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "schema"
    if cmd == "schema":
        rep = validate_against_csv()
        _print_report(rep)
        return 0 if rep.ok else 1
    if cmd == "status":
        for k, v in describe().items():
            print(f"{k:28} {v}")
        return 0
    if cmd == "check":
        if not settings.is_sql_server:
            print("DATA_SOURCE is 'demo' - nothing to connect to. Set DATA_SOURCE=staging (or production) and that environment's *_DB_* values in backend/.env first.")
            return 2
        from sqlalchemy import create_engine

        engine = create_engine(build_sql_server_url(), future=True, pool_pre_ping=True)
        install_write_guard(engine)
        install_identity_check(engine)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT @@VERSION")).scalar_one()
            db = conn.execute(text("SELECT DB_NAME()")).scalar_one()
            emp = conn.execute(text("SELECT COUNT(*) FROM dbo.tblEmployee")).scalar_one()
            conn.rollback()
        print(f"Connected (read-only) to database {db}: {version.splitlines()[0]}")
        print(f"tblEmployee rows: {emp}")
        rep = validate_live(engine)
        _print_report(rep)
        return 0 if rep.ok else 1
    print("usage: python -m app.production [schema|status|check]")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
