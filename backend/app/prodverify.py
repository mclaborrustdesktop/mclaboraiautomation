"""Offline check of what the app would ask the production SQL Server for.

    .venv\\Scripts\\python.exe -m app.prodverify

Runs the real search, detail, lookup, sign-in and duplicate-check code in production mode
against a recorder instead of a database.  No connection is opened.  Every table.column the
recorded statements mention is compared with:

  * the approved column list   tools/prod-check/required_schema.json
  * the sensitive column list  (same file) - none may ever be requested
  * the client's schema export docs/schema/McLabor_Database_structure.csv

It also lists which Add/Edit form fields can be saved to production as they are.
Run it in its own process: it forces DATA_SOURCE=production for itself only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_ENV = os.environ.get("PRODVERIFY_ENV", "production").lower()  # "production" or "staging"
os.environ["DATA_SOURCE"] = _ENV
os.environ.setdefault(f"{_ENV.upper()}_DB_SERVER", "offline-verification.invalid")
os.environ.setdefault(f"{_ENV.upper()}_DB_EXPECTED_SERVER_NAME", "OFFLINE-VERIFICATION")
os.environ.setdefault(f"{_ENV.upper()}_DB_TRUSTED_CONNECTION", "true")
os.environ[f"{_ENV.upper()}_WRITES_ENABLED"] = "false"

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import mssql  # noqa: E402
from sqlalchemy.orm import class_mapper  # noqa: E402
from sqlalchemy.sql import visitors  # noqa: E402
from sqlalchemy.sql.elements import ColumnClause  # noqa: E402

from . import duplicates, models as m, production, schemas, search, webauth  # noqa: E402
from .config import BACKEND_DIR, RESTRICTED_FIELDS, settings  # noqa: E402
from .database import Base  # noqa: E402
from .routers import customers, dashboard, employees, lookups, projects, tracking, users  # noqa: E402

REQUIRED = BACKEND_DIR.parent / "tools" / "prod-check" / "required_schema.json"
# Constructs SQLite accepts but SQL Server rejects.
T_SQL_INVALID = {"parameter inside GROUP BY (SQL Server treats each one as a different expression)": r"GROUP BY (?:(?!ORDER BY).)*?(:[A-Za-z_]\w*|\?)",
                 "IS 0 / IS 1": r"\bIS (NOT )?[01]\b", "IS true / IS false": r"\bIS (NOT )?(true|false)\b", "LIMIT": r"\bLIMIT \d", "|| concatenation": r"\|\|"}
ALIASES = {"yit": "tblPullDownYearsInTrade"}  # alias used inside the one literal SQL expression (models.py)


class _Result:
    """Empty result that answers every accessor the app uses."""

    def scalars(self):
        return self

    def unique(self):
        return self

    def all(self):
        return []

    def first(self):
        return None

    def one_or_none(self):
        return None

    def one(self):
        return (0,) * 12  # an all-zero totals row

    def scalar_one_or_none(self):
        return None

    def scalar_one(self):
        return 5  # "some rows match", so the facet and count paths are exercised too

    def scalar(self):
        return None

    def __iter__(self):
        return iter(())


class Recorder:
    """Stands in for a database session: remembers statements, returns nothing, connects to nothing."""

    def __init__(self) -> None:
        self.statements: list = []
        self.writes: list[str] = []

    def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return _Result()

    def get(self, model, ident):
        self.statements.append(select(model))
        return None

    def add(self, obj):
        self.writes.append(type(obj).__name__)

    def commit(self):
        pass

    flush = rollback = close = commit


def _base_table(t) -> str | None:
    while t is not None and not hasattr(t, "name"):
        t = getattr(t, "element", None)
    seen = 0
    while t is not None and hasattr(t, "element") and seen < 5:  # alias -> real table
        t = t.element
        seen += 1
    return getattr(t, "name", None)


def columns_in(stmt) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    elements = list(visitors.iterate(stmt))
    for sel in [e for e in elements if hasattr(e, "selected_columns")]:  # "SELECT whole_table" lists its columns here
        for col in sel.selected_columns:
            elements.extend(visitors.iterate(col))
    for el in elements:
        if isinstance(el, ColumnClause):
            if el.is_literal:  # raw SQL text: pull alias.column pairs out of it
                for alias, col in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", el.name):
                    found.add((ALIASES.get(alias, alias), col))
            elif el.table is not None:
                table = _base_table(el.table)
                if table:
                    found.add((ALIASES.get(table, table), el.name))
    return found


SAMPLE_FILTERS = {
    "state": "MA", "city": "Boston", "trade": "Electrician", "trade_id": 1, "qualification": "Journeyman", "status": "Active", "status_id": 1,
    "available": True, "licensed": True, "osha": True, "will_travel": True, "us_citizen": True, "i9_complete": True, "min_years": 5, "max_years": 30,
    "min_rate": 20, "max_rate": 60, "license_expiring_days": 60, "customer_type": "General Contractor", "type_id": 1, "salesman_id": 1, "on_hold": True,
    "contract_on_file": True, "min_revenue": 1000, "has_active_projects": True, "industry": "Healthcare", "salesman": "Pat Doe", "customer": "Acme",
    "customer_id": 1, "zip": "021", "manned": False, "min_employees": 3, "ocip": True, "start_window": "this_month",
}


def exercise(rec: Recorder) -> dict[str, int | str]:
    """Run the app's read paths against the recorder. Returns statements recorded per area."""
    done: dict[str, int | str] = {}

    def area(name: str, fn) -> None:
        before = len(rec.statements)
        try:
            fn()
        except HTTPException:
            pass  # "not found" is expected: the recorder returns no rows
        except Exception as exc:  # noqa: BLE001 - report, do not hide
            done[name] = f"NOT EXERCISED ({type(exc).__name__}: {exc})"
            return
        done[name] = len(rec.statements) - before

    kw = ["smith", "617"]
    # The recorder returns no rows, so pretend each page query found two records: the follow-up statements
    # (load those records, count filter values) are then recorded and checked as well.
    real_page_ids = search._page_ids

    def recorded_page_ids(db, pk, conditions, order, offset, limit):
        real_page_ids(db, pk, conditions, order, offset, limit)
        return [1, 2], 5

    search._page_ids = recorded_page_ids
    area("employee search (all filters)", lambda: [search.search_employees(rec, dict(SAMPLE_FILTERS, licensed=v), kw, 1, 25, sort=s, with_facets=True)
                                                    for v in (True, False) for s in ("relevance", "name", "years", "rate", "newest")])
    area("customer search (all filters)", lambda: [search.search_customers(rec, dict(SAMPLE_FILTERS, has_active_projects=v), kw, 1, 25, sort=s, with_facets=True)
                                                    for v in (True, False) for s in ("relevance", "name", "revenue", "newest")])
    area("job search (all filters)", lambda: [search.search_projects(rec, dict(SAMPLE_FILTERS, manned=v, start_window=w), kw, 1, 25, sort="relevance", with_facets=True)
                                               for v in (True, False) for w in ("this_week", "this_month", "next_month", "this_year")])
    area("filter counts (all facets)", lambda: [fn(rec, {}, [], 1, 50, with_facets=True) for fn in (search.search_employees, search.search_customers, search.search_projects)])
    area("AI search vocabulary", lambda: [search.vocab(rec), search.vocab(rec, "projects", "jobs for harbor electric in boston")])
    area("employee record", lambda: employees._load(rec, 1))
    area("customer record", lambda: customers._load(rec, 1))
    area("job record", lambda: projects._load(rec, 1))
    area("weekly tracking record", lambda: tracking._load(rec, 1))
    area("lookup lists (form drop-downs)", lambda: lookups.lookups(db=rec, _=None))
    area("duplicate check: employee", lambda: duplicates.find_employee_duplicates(
        rec, {"EmFirstName": "Dana", "EmLastName": "Quill", "EmEmail": "d@example.com", "EmMobilePhone": "6175550100", "EmHomePhone": "6175550101", "EmCity": "Boston"}))
    area("duplicate check: customer", lambda: duplicates.find_customer_duplicates(
        rec, {"CustBusName": "Harborline Mechanical", "CustEmail": "a@example.com", "Phone": "6175550100", "CustWebSiteHLink": "example.com"}))
    area("sign-in: find staff member", lambda: webauth._find_staff(rec, "ADMIN"))
    area("users list", lambda: users.list_users(q="a", active=True, page=1, page_size=50, db=rec, _=None))
    area("user record", lambda: users._load(rec, 1))
    area("dashboard", lambda: dashboard.dashboard(db=rec, _=None))
    area("weekly tracking list", lambda: tracking.list_tracking(week_ending_date=None, employee_id=1, customer_id=1, project_id=1, q="smith", page=1, page_size=25, db=rec, _=None))
    return done


def form_fields() -> dict[str, dict[str, list[str]]]:
    """Which Add/Edit fields map straight onto a production column."""
    structure = production.load_structure_csv(Path(settings.schema_csv_dir) / production.STRUCTURE_CSV)
    out = {}
    for label, schema, table in (("Employee", schemas.EmployeeCreate, "tblEmployee"), ("Customer", schemas.CustomerCreate, "tblCustomer"),
                                 ("Job", schemas.ProjectCreate, "tblProject")):
        cols = structure.get(table.lower(), {})
        direct, restricted, derived, other = [], [], [], []
        for name in schema.model_fields:
            if name in RESTRICTED_FIELDS.get(table, ()):
                restricted.append(name)
            elif name in production.PRODUCTION_MAPPED.get(table, {}):
                derived.append(name)
            elif name.lower() in cols:
                direct.append(name)
            else:
                other.append(name)
        out[label] = {"direct": direct, "restricted": restricted, "derived": derived, "other": other}
    return out


def run() -> dict:
    required = json.loads(REQUIRED.read_text(encoding="utf-8"))
    approved = {(t.lower(), c.lower()) for t, cols in required["tables"].items() for c in cols}
    sensitive = {(t.lower(), c.lower()) for t, cols in required["sensitive_columns"].items() for c in cols}
    structure = production.load_structure_csv(Path(settings.schema_csv_dir) / production.STRUCTURE_CSV)

    rec = Recorder()
    areas = exercise(rec)
    statements = list(rec.statements) + [select(mapper.class_) for mapper in Base.registry.mappers]  # + every mapped entity (relationship loads)

    referenced: set[tuple[str, str]] = set()
    # Loading an entity selects every column mapped on it, so count all mapped columns as requested.
    for mapper in Base.registry.mappers:
        for prop in mapper.column_attrs:
            for col in prop.columns:
                referenced |= columns_in(col)
    compiled = 0
    tsql_problems: list[str] = []
    for stmt in statements:
        referenced |= columns_in(stmt)
        sql = str(stmt.compile(dialect=mssql.dialect()))  # must render as SQL Server syntax
        for label, pattern in T_SQL_INVALID.items():
            hit = re.search(pattern, sql, re.I | re.S)
            if hit:
                tsql_problems.append(f"{label}: ...{sql[max(0, hit.start() - 50):hit.end() + 10]}...".replace("\n", " "))
        compiled += 1

    mapped_restricted = [f"{mp.local_table.name}.{c.name}" for mp in Base.registry.mappers for c in mp.local_table.columns
                         if c.name in RESTRICTED_FIELDS.get(mp.local_table.name, ())]
    low = {(t.lower(), c.lower()): f"{t}.{c}" for t, c in referenced}
    return {
        "statements": compiled,
        "areas": areas,
        "columns_referenced": len(low),
        "tables_referenced": len({t for t, _ in low}),
        "sensitive_requested": sorted(low[k] for k in low if k in sensitive),
        "not_approved": sorted(low[k] for k in low if k not in approved),
        "not_in_schema_export": sorted(low[k] for k in low if k[1] not in structure.get(k[0], {})),
        "restricted_still_mapped": sorted(mapped_restricted),
        "tsql_problems": sorted(set(tsql_problems))[:20],
        "approved_but_unused": len(approved - set(low)),
        "writes_attempted": rec.writes,
        "forms": form_fields(),
    }


def main() -> int:
    if not settings.is_sql_server:
        print("Could not switch this process to a SQL Server environment.")
        return 2
    r = run()
    bad = r["sensitive_requested"] or r["not_approved"] or r["not_in_schema_export"] or r["restricted_still_mapped"] or r["writes_attempted"] or r["tsql_problems"]
    print(f"Query verification for the {settings.environment} environment (offline - no database connection was opened)")
    print(f"  statements checked: {r['statements']}   tables: {r['tables_referenced']}   columns: {r['columns_referenced']}")
    for name, n in r["areas"].items():
        print(f"    {name:34} {n if isinstance(n, str) else str(n) + ' statement(s)'}")
    for label, key in (("sensitive columns requested", "sensitive_requested"), ("columns outside the approved list", "not_approved"),
                       ("columns missing from the client's schema export", "not_in_schema_export"), ("restricted columns still mapped", "restricted_still_mapped"),
                       ("writes attempted by read paths", "writes_attempted"), ("SQL that SQL Server would reject", "tsql_problems")):
        print(f"  {label}: {', '.join(r[key]) if r[key] else 'none'}")
    print(f"  approved columns not used by these paths: {r['approved_but_unused']}")
    print("  Add/Edit form fields:")
    for label, f in r["forms"].items():
        print(f"    {label}: {len(f['direct'])} map directly to a production column")
        if f["restricted"]:
            print(f"      hidden in production (restricted): {', '.join(f['restricted'])}")
        if f["derived"]:
            print(f"      read-only in production (stored elsewhere; needs a write mapping before writes are enabled): {', '.join(f['derived'])}")
        if f["other"]:
            print(f"      not single columns (handled by the app): {', '.join(f['other'])}")
    skipped = [n for n, v in r["areas"].items() if isinstance(v, str)]
    print("RESULT: " + ("PROBLEMS FOUND" if bad else "OK" + (f" (but {len(skipped)} area(s) not exercised)" if skipped else "")))
    return 1 if bad or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
