"""Write mapping for the three values the McLabor structure stores somewhere else than the forms show them.

The forms (and the demo tables) have plain fields: years in trade (a number), will-travel (a text) and the job's
site city/state. In the production shape (SQL Server, or the PostgreSQL database built from the same structure):

* ``YearsInTrade`` is ``tblEmployee.YearsInTradeID`` -> ``tblPullDownYearsInTrade`` (labels like "5 years");
* ``WillTravel`` lives in the 1:1 extension table ``tblEmployeeB``;
* a job's city/state come from ``SiteStateCityID`` (the text columns do not exist).

``prepare_*`` turns the form's values into the right columns before the row is saved and returns the follow-up
to run once the row has an id. In the demo shape nothing changes.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from . import models as m
from .config import settings


def _years_rows(db: Session) -> list[tuple[int, str, int | None]]:
    t = m._tblYearsInTrade
    out = []
    for i, label in db.execute(select(t.c.PullDownYearsInTradeID, t.c.PullDownYearsInTrade)).all():
        digits = re.match(r"\s*(\d+)", str(label or ""))
        out.append((int(i), str(label or ""), int(digits.group(1)) if digits else None))
    return out


def years_in_trade_id(db: Session, years: int | None) -> int | None:
    """The lookup row whose label starts with this number ("5 years" for 5), or 422 with the choices that exist."""
    if years is None:
        return None
    rows = _years_rows(db)
    for i, _label, n in rows:
        if n == int(years):
            return i
    choices = ", ".join(sorted({lbl.strip() for _, lbl, n in rows if n is not None}, key=lambda s: int(re.match(r"\s*(\d+)", s).group(1))))
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'Years in trade' must be one of the values the list has ({choices}); {years} is not one of them.")


def prepare_employee(db: Session, data: dict[str, Any]) -> Callable[[int], None] | None:
    """Rewrites ``data`` in place for the production shape. Returns a follow-up (employee id -> None) or None."""
    if not settings.production_shape:
        return None
    if "YearsInTrade" in data:
        data["YearsInTradeID"] = years_in_trade_id(db, data.pop("YearsInTrade"))
    if "WillTravel" not in data:
        return None
    will_travel = data.pop("WillTravel")
    b = m._tblEmployeeB

    def after(employee_id: int) -> None:
        existing = db.execute(select(b.c.EmployeeBID).where(b.c.EmployeeID == employee_id).limit(1)).first()
        if existing is None:
            db.execute(insert(b).values(EmployeeID=employee_id, WillTravel=will_travel))
        else:
            db.execute(update(b).where(b.c.EmployeeID == employee_id).values(WillTravel=will_travel))

    return after


def prepare_project(data: dict[str, Any]) -> None:
    """The site city/state text does not exist in the production shape: they follow from SiteStateCityID."""
    if settings.production_shape:
        data.pop("SiteCity", None)
        data.pop("SiteState", None)
