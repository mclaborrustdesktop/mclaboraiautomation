"""Reference checks for create/update payloads.

Turns "unknown lookup id" into a clear 422 instead of a database IntegrityError
(SQLite) or a constraint violation (SQL Server / PostgreSQL).  Works off the ORM
metadata, so every ``*ID`` column with a ForeignKey is checked automatically.

A lookup value must also be USABLE: the real lookup tables contain blank rows and
rows switched off with an ``...Active`` flag; a save must not point at either.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Boolean, select
from sqlalchemy.orm import Session

_FRIENDLY = {
    "EmTradeID": "trade", "SubTrade1ID": "sub-trade 1", "SubTrade2ID": "sub-trade 2", "EmQualificationID": "qualification",
    "EmExperienceID": "experience", "EmEmployeeStatusID": "employee status", "EmStateCityID": "city", "StateCityID": "city",
    "SiteStateCityID": "city", "ReferrerEmployeeID": "referring employee", "EmContractWith_PayrollCoID": "payroll company",
    "CustContractWith_PayrollCoID": "payroll company", "CustStatusID": "customer status", "CustomerTypeID": "customer type",
    "SalesmanID": "sales rep", "SalesStatusID": "sales status", "CustomerID": "customer", "ProjStatusID": "job status",
    "ProjectWCCID": "WCC code", "ParentProjectID": "parent job", "PayrollCoOnSiteID": "payroll company on site",
    "MonStatusFlagID": "status flag", "EmployeeID": "employee", "ProjectID": "job", "EmployeeLicenseStateID": "license state",
    "EmployeeLicenseTradeID": "license trade", "EmployeeLicenseTypeID": "license type", "CustomerContactTitleID": "contact title",
    "EmployeeNoteTypeID": "note type", "EmployeeNoteCustomerID": "customer",
}


def _label_column(table, pk_name: str):
    """The lookup's label column, by the McLabor naming rule (<Name>ID -> <Name>), when it has one."""
    if pk_name.lower().endswith("id"):
        for c in table.columns:
            if c.name.lower() == pk_name[:-2].lower():
                return c
    return table.columns.get("City") if table.name == "tblPullDownStateCities" else None


def _active_column(table):
    for c in table.columns:
        if c.name.lower().endswith("active") and isinstance(c.type, Boolean):
            return c
    return None


def validate_references(db: Session, model_cls: type, data: dict[str, Any]) -> None:
    table = model_cls.__table__
    problems = []
    for key, value in data.items():
        if value is None or key not in table.columns:
            continue
        for fk in table.columns[key].foreign_keys:
            target = fk.column
            ttable = target.table
            friendly = _FRIENDLY.get(key, key)
            row = db.execute(select(ttable).where(target == value).limit(1)).first()
            if row is None:
                problems.append(f"Unknown {friendly} (id {value})")
                continue
            row = row._mapping
            label_col = _label_column(ttable, target.name)
            label = row[label_col.name] if label_col is not None else None
            if label_col is not None and ttable.name.startswith("tblPullDown") and (label is None or not str(label).strip()):
                problems.append(f"The {friendly} entry (id {value}) is blank in the lookup list and cannot be used")
                continue
            active_col = _active_column(ttable)
            if active_col is not None and ttable.name.startswith("tblPullDown") and row[active_col.name] is False:
                problems.append(f"The {friendly} '{label}' is no longer active and cannot be chosen")
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(problems))
