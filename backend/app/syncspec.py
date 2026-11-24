"""What the one-way synchronization is allowed to copy: the approved tables and columns, nothing else.

Source of truth: ``tools/prod-check/required_schema.json`` (the 33 tables and the columns the website was approved to
read, plus the sensitive columns that must never leave the office). Both sides of the sync use this module: the
office agent selects exactly these columns, the cloud side refuses anything outside them, and the mirror tables are
created without the sensitive columns, so they cannot even hold such data.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Column, Index, Integer, MetaData, Table

from .config import BACKEND_DIR, settings

REQUIRED = BACKEND_DIR.parent / "tools" / "prod-check" / "required_schema.json"

# Column names that are refused everywhere, approved list or not (belt and braces for the sensitive list).
FORBIDDEN_NAME = re.compile(r"(ssn|socialsecurity|bank|routing|dob\b|birth|password|passwd|citizen|i9\b|\brace|emsex|w4|dependents|driverlic|dlnum|passport)", re.I)

# Tables without an ORM model: their key is the 1:1 link column.
PRIMARY_KEY_OVERRIDES = {"tblEmployeeB": "EmployeeID"}

# Search indexes the mirror needs (the website's filters and sorts); foreign keys are deliberately absent: a mirror
# must accept whatever the office database holds, dangling ids included.
MIRROR_INDEXES = {
    "tblEmployee": [("EmLastName", "EmFirstName"), ("EmEmployeeStatusID",), ("EmTradeID",), ("EmStateCityID",), ("EmZip",), ("EmCity",), ("EmState",)],
    "tblCustomer": [("CustBusName",), ("CustStatusID",), ("StateCityID",), ("City",), ("State",), ("SalesmanID",)],
    "tblProject": [("CustomerID",), ("ProjStatusID", "StartDate"), ("SiteStateCityID",)],
    "tblTracking": [("WeekEndingDate",), ("EmployeeID", "WeekEndingDate"), ("ProjectID", "WeekEndingDate"), ("CustomerID",)],
    "tblEmployeeLicenses": [("EmployeeID",)], "tblEmployeeNotes": [("EmployeeID",)],
    "tblCustomerContacts": [("CustomerID",)], "tblCustomerNotes": [("CustomerID",)],
    "tblOfficeStaffPermission": [("OfficeStaffID",)], "tblOfficeStaffActivity": [("OfficeStaffID",)],
}


@lru_cache(maxsize=1)
def _spec() -> dict:
    return json.loads(Path(REQUIRED).read_text(encoding="utf-8"))


def approved_tables() -> dict[str, list[str]]:
    """{table: [approved columns, sorted]} - the only data the sync may copy."""
    spec = _spec()
    sensitive = {t: set(c) for t, c in spec.get("sensitive_columns", {}).items()}
    out: dict[str, list[str]] = {}
    for table, cols in spec["tables"].items():
        keep = [c for c in cols if c not in sensitive.get(table, set()) and not FORBIDDEN_NAME.search(c)]
        out[table] = sorted(keep)
    return out


def sensitive_columns() -> dict[str, list[str]]:
    return {t: sorted(c) for t, c in _spec().get("sensitive_columns", {}).items()}


def primary_key(table: str) -> str:
    if table in PRIMARY_KEY_OVERRIDES:
        return PRIMARY_KEY_OVERRIDES[table]
    from . import models  # noqa: F401 - registers the ORM tables
    from .database import Base

    t = Base.metadata.tables.get(table)
    if t is not None and len(t.primary_key.columns) == 1:
        return next(iter(t.primary_key.columns)).name
    from .pgschema import primary_key as by_naming_rule  # tblPullDownYearsInTrade -> PullDownYearsInTradeID

    pk = by_naming_rule(table, [(c, "int") for c in approved_tables().get(table, [])])
    if pk is None:
        raise KeyError(f"No single-column primary key known for {table}")
    return pk


def table_order() -> list[str]:
    """Parents before children (lookups, staff, employees, customers, projects, tracking); tblEmployeeB after tblEmployee."""
    from .synthdb import build_metadata

    ordered = [t.name for t in build_metadata().sorted_tables]
    approved = approved_tables()
    out = [t for t in ordered if t in approved]
    for t in approved:
        if t not in out:
            out.append(t)
    return out


def check_columns(table: str, columns) -> None:
    """Raise ValueError when a column is not approved for this table (unknown table, sensitive or unlisted column)."""
    approved = approved_tables()
    if table not in approved:
        raise ValueError(f"{table} is not an approved table for the synchronization")
    allowed = set(approved[table])
    bad = sorted(c for c in columns if c not in allowed)
    if bad:
        raise ValueError(f"{table}: column(s) not approved for the synchronization: {', '.join(bad[:8])}")


@lru_cache(maxsize=1)
def mirror_metadata() -> MetaData:
    """The mirror's tables: approved columns only (typed from the schema export), a primary key, search indexes, no
    foreign keys and no sensitive columns at all."""
    from .production import load_structure_csv
    from .synthdb import _sa_type

    structure = load_structure_csv(Path(settings.schema_csv_dir) / "McLabor_Database_structure.csv")
    md = MetaData()
    for table, cols in approved_tables().items():
        pk = primary_key(table)
        csv_types = structure.get(table.lower(), {})
        columns = []
        for col in sorted(cols, key=lambda c: (c != pk, c)):
            if col == pk:
                columns.append(Column(col, Integer(), primary_key=True, autoincrement=False))
            else:
                columns.append(Column(col, _sa_type(col, csv_types.get(col.lower(), "nvarchar")), nullable=True))
        t = Table(table, md, *columns)
        for n, idx in enumerate(MIRROR_INDEXES.get(table, []), 1):
            if all(c in cols for c in idx):
                Index(f"ix_sync_{table[3:].lower()}_{n}", *[t.c[c] for c in idx])
    return md
