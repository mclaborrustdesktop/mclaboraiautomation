"""PostgreSQL schema generated from the McLabor SQL Server structure export.

    .venv\\Scripts\\python.exe -m app.pgschema write [out_dir]            -> schema.sql, indexes.sql, constraints.sql
    .venv\\Scripts\\python.exe -m app.pgschema apply <postgresql url> [--indexes] [--constraints]

Source: docs/schema/McLabor_Database_structure.csv (every table and column of the client's database) and
McLabor_table_relationship.csv (its foreign keys). Every ``tbl*`` table, the ``Web*`` tables and ``SettingsBE``
are reproduced with the same table and column names (quoted, so the case is kept), primary keys inferred from the
McLabor naming rule (``tblEmployee`` -> ``EmployeeID``), identity primary keys that also accept explicit ids
(for the migration copy), foreign keys from the relationship export, and PostgreSQL types mapped from the SQL
Server ones. The ORM (models.py) runs unchanged on the result in its production shape.

Business rules the website relies on go in constraints.sql (applied after the migrated data has been checked, so a
legacy row cannot block the copy) and the search indexes in indexes.sql. The office servers are never a target.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from .config import settings

STRUCTURE_CSV = "McLabor_Database_structure.csv"
RELATIONSHIP_CSV = "McLabor_table_relationship.csv"
INCLUDE_PREFIXES = ("tbl", "Web")
INCLUDE_EXACT = {"SettingsBE"}

TYPE_MAP = {
    "int": "integer", "smallint": "smallint", "tinyint": "smallint", "bigint": "bigint", "bit": "boolean",
    "money": "numeric(19,4)", "smallmoney": "numeric(10,4)", "decimal": "numeric(18,4)", "numeric": "numeric(18,4)",
    "float": "double precision", "real": "real",
    "datetime": "timestamp", "datetime2": "timestamp", "smalldatetime": "timestamp", "datetimeoffset": "timestamptz", "date": "date", "time": "time",
    "nvarchar": "text", "varchar": "text", "nchar": "text", "char": "text", "ntext": "text", "text": "text", "sysname": "text",
    "uniqueidentifier": "uuid", "varbinary": "bytea", "binary": "bytea", "image": "bytea", "timestamp": "bytea", "rowversion": "bytea",
    "xml": "xml", "sql_variant": "text", "hierarchyid": "text", "geography": "text", "geometry": "text",
}

# tables/columns the website writes with rules the Access form enforced by hand
CONSTRAINTS = [
    ('tblTracking', 'ck_tracking_hours', 'CHECK (("SatHours" IS NULL OR "SatHours" BETWEEN 0 AND 24) AND ("SunHours" IS NULL OR "SunHours" BETWEEN 0 AND 24) AND ("MonHours" IS NULL OR "MonHours" BETWEEN 0 AND 24) AND ("TueHours" IS NULL OR "TueHours" BETWEEN 0 AND 24) AND ("WedHours" IS NULL OR "WedHours" BETWEEN 0 AND 24) AND ("ThuHours" IS NULL OR "ThuHours" BETWEEN 0 AND 24) AND ("FriHours" IS NULL OR "FriHours" BETWEEN 0 AND 24))'),
    ('tblTracking', 'ck_tracking_rates', 'CHECK (("PayRate" IS NULL OR "PayRate" >= 0) AND ("BillRate" IS NULL OR "BillRate" >= 0) AND ("OTPayRate" IS NULL OR "OTPayRate" >= 0) AND ("BillRateOT" IS NULL OR "BillRateOT" >= 0))'),
    ('tblEmployee', 'ck_employee_names', 'CHECK (length(trim("EmFirstName")) > 0 AND length(trim("EmLastName")) > 0)'),
    ('tblCustomer', 'ck_customer_name', 'CHECK (length(trim("CustBusName")) > 0)'),
    ('tblProject', 'ck_project_dates', 'CHECK ("EndDate" IS NULL OR "StartDate" IS NULL OR "EndDate" >= "StartDate")'),
    ('tblProject', 'ck_project_site', 'CHECK (length(trim("SiteName")) > 0)'),
]
UNIQUE_INDEXES = [
    ('ux_tracking_employee_project_week', 'tblTracking', '("EmployeeID", "ProjectID", "WeekEndingDate")', 'WHERE "Placeholder" IS NOT TRUE'),
    ('ux_officestaff_initials', 'tblOfficeStaff', '(lower("Initials"))', 'WHERE "Initials" IS NOT NULL'),
    ('ux_employeeb_employee', 'tblEmployeeB', '("EmployeeID")', ''),
]
SEARCH_INDEXES = [
    ('ix_employee_last_first', 'tblEmployee', '(lower("EmLastName"), lower("EmFirstName"))'),
    ('ix_employee_status', 'tblEmployee', '("EmEmployeeStatusID")'),
    ('ix_employee_trade', 'tblEmployee', '("EmTradeID")'),
    ('ix_employee_city', 'tblEmployee', '("EmStateCityID")'),
    ('ix_employee_zip', 'tblEmployee', '("EmZip")'),
    ('ix_customer_name', 'tblCustomer', '(lower("CustBusName"))'),
    ('ix_customer_status', 'tblCustomer', '("CustStatusID")'),
    ('ix_customer_city', 'tblCustomer', '("StateCityID")'),
    ('ix_project_customer', 'tblProject', '("CustomerID")'),
    ('ix_project_status_start', 'tblProject', '("ProjStatusID", "StartDate")'),
    ('ix_project_city', 'tblProject', '("SiteStateCityID")'),
    ('ix_tracking_week', 'tblTracking', '("WeekEndingDate")'),
    ('ix_tracking_employee_week', 'tblTracking', '("EmployeeID", "WeekEndingDate")'),
    ('ix_tracking_project_week', 'tblTracking', '("ProjectID", "WeekEndingDate")'),
    ('ix_tracking_customer', 'tblTracking', '("CustomerID")'),
    ('ix_employeelicenses_employee', 'tblEmployeeLicenses', '("EmployeeID")'),
    ('ix_employeenotes_employee', 'tblEmployeeNotes', '("EmployeeID")'),
    ('ix_customercontacts_customer', 'tblCustomerContacts', '("CustomerID")'),
    ('ix_customernotes_customer', 'tblCustomerNotes', '("CustomerID")'),
]
TRIGRAM_INDEXES = [  # word searches ("contains") use ILIKE; pg_trgm serves them from an index
    ('tx_employee_last', 'tblEmployee', '"EmLastName"'), ('tx_employee_first', 'tblEmployee', '"EmFirstName"'),
    ('tx_customer_name', 'tblCustomer', '"CustBusName"'), ('tx_project_site', 'tblProject', '"SiteName"'),
]


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load_structure(path: Path) -> "OrderedDict[str, list[tuple[str, str]]]":
    """{table: [(column, sql_type), ...]} in file order, original case."""
    tables: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if len(row) < 4:
                continue
            _schema, table, column, sql_type = (x.strip() for x in row[:4])
            if not table or table.lower() == "table":
                continue
            tables.setdefault(table, []).append((column, sql_type))
    return tables


def load_relationships(path: Path) -> list[tuple[str, str, str, str, str]]:
    """[(name, child table, child column, parent table, parent column)] with the original case."""
    out = []
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if len(row) >= 7:
                out.append((row[0].strip(), row[2].strip(), row[3].strip(), row[5].strip(), row[6].strip()))
    return out


def included(table: str) -> bool:
    return table in INCLUDE_EXACT or table.startswith(INCLUDE_PREFIXES)


def primary_key(table: str, columns: list[tuple[str, str]]) -> str | None:
    """The McLabor rule: tblEmployee -> EmployeeID, tblPullDownTrade -> PullDownTradeID (case-insensitive)."""
    names = [c for c, _ in columns]
    base = table[3:] if table.startswith("tbl") else table
    for cand in (base + "ID", base + "Id", table + "ID"):
        for n in names:
            if n.lower() == cand.lower():
                return n
    ints = {c: t for c, t in columns if t.lower() in ("int", "bigint")}
    for n in names:  # first integer column ending in ID
        if n in ints and n.lower().endswith("id"):
            return n
    return None


def pg_type(sql_type: str) -> str:
    return TYPE_MAP.get((sql_type or "").lower(), "text")


def generate(csv_dir: Path | None = None) -> dict[str, str]:
    d = Path(csv_dir or settings.schema_csv_dir)
    structure = load_structure(d / STRUCTURE_CSV)
    rels = load_relationships(d / RELATIONSHIP_CSV)
    tables = OrderedDict((t, cols) for t, cols in structure.items() if included(t))
    lower = {t.lower(): t for t in tables}
    pks = {t: primary_key(t, cols) for t, cols in tables.items()}

    lines = ["-- McLabor database structure for PostgreSQL, generated by app/pgschema.py from the SQL Server export.",
             "-- Table and column names keep their case (quoted). Nothing here points at the office servers.",
             "BEGIN;", ""]
    for t, cols in tables.items():
        pk = pks[t]
        defs = []
        for c, st in cols:
            typ = pg_type(st)
            if c == pk and typ in ("integer", "bigint", "smallint"):
                defs.append(f"  {q(c)} {typ} GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
            elif c == pk:
                defs.append(f"  {q(c)} {typ} PRIMARY KEY")
            else:
                defs.append(f"  {q(c)} {typ}")
        lines.append(f"CREATE TABLE {q(t)} (\n" + ",\n".join(defs) + "\n);")
    lines.append("")
    # foreign keys: only between included tables, only when both columns exist; one per (child col -> parent col)
    seen = set()
    fk_lines = []
    col_sets = {t: {c.lower(): c for c, _ in cols} for t, cols in tables.items()}
    for name, ct, cc, pt, pc in rels:
        ct_, pt_ = lower.get(ct.lower()), lower.get(pt.lower())
        if not ct_ or not pt_ or cc.lower() not in col_sets[ct_] or pc.lower() not in col_sets[pt_]:
            continue
        if pks.get(pt_) and pks[pt_].lower() != pc.lower():
            continue  # a PostgreSQL foreign key must reference a unique column; the export has a few that do not
        key = (ct_, col_sets[ct_][cc.lower()], pt_, col_sets[pt_][pc.lower()])
        if key in seen:
            continue
        seen.add(key)
        cname = re.sub(r"[^A-Za-z0-9_]", "_", f"fk_{ct_[3:] if ct_.startswith('tbl') else ct_}_{key[1]}")
        if len(cname) > 63:  # PostgreSQL cuts names at 63 characters; keep them unique with a short hash
            import hashlib

            cname = cname[:55] + "_" + hashlib.sha1("|".join(key).encode()).hexdigest()[:7]
        fk_lines.append(f"ALTER TABLE {q(key[0])} ADD CONSTRAINT {q(cname)} FOREIGN KEY ({q(key[1])}) REFERENCES {q(key[2])} ({q(key[3])}) ON DELETE NO ACTION NOT VALID;")
    lines += fk_lines
    lines += ["", "-- NOT VALID: existing rows are not checked at creation (a migrated legacy row with a dangling id cannot block the copy);",
              "-- new rows are. After the migrated data has been cleaned: ALTER TABLE ... VALIDATE CONSTRAINT ...", "COMMIT;", ""]
    schema = "\n".join(lines)

    idx = ["-- Search indexes for the website (app/pgschema.py). Safe to apply at any time; CONCURRENTLY avoids locking a live table.", ""]
    fk_cols = sorted({(k[0], k[1]) for k in seen})
    for t, c in fk_cols:
        short = t[3:] if t.startswith("tbl") else t
        idx.append(f"CREATE INDEX IF NOT EXISTS {q(('ix_' + short + '_' + c)[:63])} ON {q(t)} ({q(c)});")
    idx.append("")
    for name, t, cols in SEARCH_INDEXES:
        if t in tables:
            idx.append(f"CREATE INDEX IF NOT EXISTS {q(name)} ON {q(t)} {cols};")
    indexes = "\n".join(idx) + "\n"
    trg = ["-- Word searches (ILIKE 'contains') served from trigram indexes: needs the pg_trgm contrib extension, which hosted",
           "-- PostgreSQL (Railway, Azure, AWS) ships. Optional: the searches work without it, from sequential scans.",
           "CREATE EXTENSION IF NOT EXISTS pg_trgm;"]
    for name, t, col in TRIGRAM_INDEXES:
        if t in tables:
            trg.append(f"CREATE INDEX IF NOT EXISTS {q(name)} ON {q(t)} USING gin ({col} gin_trgm_ops);")
    trigram = "\n".join(trg) + "\n"

    cons = ["-- Business rules the website enforces, as database constraints (app/pgschema.py).",
            "-- Apply AFTER the migrated data has been checked (a legacy row that breaks a rule would stop the ALTER). The",
            "-- website validates the same rules itself, so the application works with or without these.", ""]
    for t, name, body in CONSTRAINTS:
        if t in tables:
            cons.append(f"ALTER TABLE {q(t)} ADD CONSTRAINT {q(name)} {body} NOT VALID;")
    cons.append("")
    for name, t, cols, where in UNIQUE_INDEXES:
        if t in tables:
            cons.append(f"CREATE UNIQUE INDEX IF NOT EXISTS {q(name)} ON {q(t)} {cols} {where};".replace("  ", " ").rstrip())
    constraints = "\n".join(cons) + "\n"
    return {"schema.sql": schema, "indexes.sql": indexes, "trigram-indexes.sql": trigram, "constraints.sql": constraints,
            "_tables": str(len(tables)), "_foreign_keys": str(len(fk_lines)), "_columns": str(sum(len(c) for c in tables.values()))}


def refuse_office_hosts(url: str) -> None:
    u = make_url(url)
    host = (u.host or "").lower()
    if settings.is_office_host(host):
        raise RuntimeError(f"Refusing to apply a schema on '{u.host}': the office servers are never touched.")
    if not u.drivername.startswith("postgresql"):
        raise RuntimeError("The schema is for PostgreSQL only (postgresql+psycopg://...).")


def apply(url: str, indexes: bool = False, constraints: bool = False, quiet: bool = False) -> dict[str, int]:
    """Create the schema in an EMPTY PostgreSQL database (refuses when any of the tables already exists)."""
    refuse_office_hosts(url)
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    files = generate()
    engine = create_engine(url, future=True)
    existing = set(inspect(engine).get_table_names())
    if existing & {t for t in load_structure(Path(settings.schema_csv_dir) / STRUCTURE_CSV) if included(t)}:
        raise RuntimeError("Tables already exist in that database: refusing to build on top of them.")
    trigram = False
    with engine.begin() as conn:
        conn.exec_driver_sql(files["schema.sql"].replace("BEGIN;", "").replace("COMMIT;", ""))
        if indexes:
            conn.exec_driver_sql(files["indexes.sql"])
            trigram = conn.execute(text("SELECT count(*) FROM pg_available_extensions WHERE name = 'pg_trgm'")).scalar_one() > 0
            if trigram:
                conn.exec_driver_sql(files["trigram-indexes.sql"])
        if constraints:
            conn.exec_driver_sql(files["constraints.sql"])
    n = len(inspect(engine).get_table_names())
    engine.dispose()
    if not quiet:
        print(f"Schema applied: {n} tables, {files['_foreign_keys']} foreign keys{', indexes' if indexes else ''}"
              f"{' (trigram indexes too)' if trigram else ' (pg_trgm not available: trigram indexes skipped)' if indexes else ''}{', constraints' if constraints else ''}.")
    return {"tables": n, "trigram": int(trigram)}


def reset_sequences(conn) -> int:
    """After rows with explicit ids were copied in (migration, synthetic data), move every identity sequence past them."""
    rows = conn.execute(text(
        "SELECT c.relname, a.attname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
        "WHERE c.relkind = 'r' AND a.attidentity <> '' AND c.relnamespace = 'public'::regnamespace"
    )).all()
    for table, column in rows:
        conn.execute(text(f'SELECT setval(pg_get_serial_sequence(\'{q(table)}\', \'{column}\'), COALESCE((SELECT MAX({q(column)}) FROM {q(table)}), 0) + 1, false)'))
    return len(rows)


def write(out_dir: Path) -> dict[str, str]:
    files = generate()
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        if not name.startswith("_"):
            (out_dir / name).write_text(content, encoding="utf-8", newline="\n")
    return files


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "write"
    if cmd == "write":
        out = Path(argv[2]) if len(argv) > 2 else Path(settings.schema_csv_dir).parent.parent / "deploy" / "railway" / "postgres"
        files = write(out)
        print(f"Wrote {out}: {files['_tables']} tables, {files['_columns']} columns, {files['_foreign_keys']} foreign keys (schema.sql, indexes.sql, trigram-indexes.sql, constraints.sql)")
        return 0
    if cmd == "apply" and len(argv) > 2:
        apply(argv[2], indexes="--indexes" in argv, constraints="--constraints" in argv)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
