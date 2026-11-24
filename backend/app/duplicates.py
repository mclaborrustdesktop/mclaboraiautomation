"""Duplicate detection for employees and customers.

The Access application flags duplicate workers with ``tblEmployee.EmployeeDuplicate``
after the fact.  The web app warns *before* a record is created: the create
endpoints refuse likely duplicates (HTTP 409 with the candidate list) unless the
user confirms with ``allow_duplicate``.

Matching is deliberately simple and explainable - every match carries the
reasons shown to the user:

Employees                                  Customers
- same e-mail                       0.95   - same normalised business name  0.95
- same first+last name and DOB      0.95   - same e-mail                    0.90
- same mobile/home phone            0.90   - same phone                     0.85
- same first+last name              0.70   - same website domain            0.80
- similar name (typo) + same city   0.65   - similar business name          0.70
- similar name (typo)               0.50

Candidate rows are pre-filtered in SQL with portable predicates (LIKE on a name
prefix / last 4 phone digits, equality on e-mail) so the same code runs on
SQLite and SQL Server without scanning whole tables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from . import models as m
from .sqlutil import ci_eq, contains, starts_with

BLOCK_THRESHOLD = 0.70  # create is refused at or above this score unless confirmed
SHOW_THRESHOLD = 0.50  # check endpoint lists candidates from this score

_BUSINESS_SUFFIXES = {
    "llc", "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "lp", "llp", "pc", "pllc", "the", "and",
}


def digits(s: str | None) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-10:] if len(d) >= 10 else d


def norm_text(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def norm_business(s: str | None) -> str:
    return " ".join(t for t in norm_text(s.replace("&", " and ") if s else s).split() if t not in _BUSINESS_SUFFIXES)


def domain(s: str | None) -> str:
    s = (s or "").lower().strip()
    if "@" in s:
        s = s.split("@", 1)[1]
    s = re.sub(r"^https?://", "", s).split("/")[0]
    return s[4:] if s.startswith("www.") else s


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


@dataclass
class Match:
    id: int
    name: str
    score: float
    reasons: list[str] = field(default_factory=list)
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    email: str | None = None
    status: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "score": round(self.score, 2), "level": "likely" if self.score >= BLOCK_THRESHOLD else "possible"}


def _phone_like(column, d: str):
    return column.like(f"%{d[-4:]}") if len(d) >= 7 else None


# --------------------------------------------------------------- employees
def find_employee_duplicates(db: Session, data: dict[str, Any], exclude_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
    first, last = norm_text(data.get("EmFirstName")), norm_text(data.get("EmLastName"))
    email = (data.get("EmEmail") or "").strip().lower()
    phones = {p for p in (digits(data.get("EmMobilePhone")), digits(data.get("EmHomePhone"))) if len(p) >= 7}
    dob: date | None = data.get("EmDOB")
    city = norm_text(data.get("EmCity"))

    preds = []
    if last:
        preds.append(starts_with(m.Employee.EmLastName, last[:3]))
    if first and last:
        preds.append(starts_with(m.Employee.EmFirstName, first[:3]))
    if email:
        preds.append(ci_eq(m.Employee.EmEmail, email))
    for p in phones:
        preds += [_phone_like(m.Employee.EmMobilePhone, p), _phone_like(m.Employee.EmHomePhone, p)]
    preds = [p for p in preds if p is not None]
    if not preds:
        return []

    stmt = select(m.Employee).options(selectinload(m.Employee.status)).where(or_(*preds)).limit(500)
    if exclude_id:
        stmt = stmt.where(m.Employee.EmployeeID != exclude_id)

    out: list[Match] = []
    for e in db.execute(stmt).scalars():
        reasons, score = [], 0.0
        ef, el = norm_text(e.EmFirstName), norm_text(e.EmLastName)
        same_name = bool(first and last and ef == first and el == last)
        name_sim = similar(f"{first} {last}", f"{ef} {el}") if first and last else 0.0
        if email and (e.EmEmail or "").strip().lower() == email:
            score = max(score, 0.95); reasons.append("same e-mail")
        if same_name and dob and e.EmDOB == dob:
            score = max(score, 0.95); reasons.append("same name and date of birth")
        if phones & {digits(e.EmMobilePhone), digits(e.EmHomePhone)} - {""}:
            score = max(score, 0.90); reasons.append("same phone number")
        if same_name:
            score = max(score, 0.70); reasons.append("same first and last name")
        elif name_sim >= 0.85:
            if city and norm_text(e.EmCity) == city:
                score = max(score, 0.65); reasons.append("similar name in the same city")
            else:
                score = max(score, 0.50); reasons.append("similar name")
        if score >= SHOW_THRESHOLD:
            out.append(Match(
                id=e.EmployeeID, name=f"{e.EmFirstName} {e.EmLastName}", score=score, reasons=reasons, city=e.EmCity, state=e.EmState,
                phone=e.EmMobilePhone or e.EmHomePhone, email=e.EmEmail, status=e.status.PullDownEmployeeStatus if e.status else None,
            ))
    out.sort(key=lambda x: (-x.score, x.name))
    return [x.as_dict() for x in out[:limit]]


# --------------------------------------------------------------- customers
def find_customer_duplicates(db: Session, data: dict[str, Any], exclude_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
    name = norm_business(data.get("CustBusName"))
    email = (data.get("CustEmail") or "").strip().lower()
    phone = digits(data.get("Phone"))
    site = domain(data.get("CustWebSiteHLink"))
    first_word = name.split(" ")[0] if name else ""

    preds = []
    if first_word:
        preds.append(contains(m.Customer.CustBusName, first_word[:4]))
    if email:
        preds.append(ci_eq(m.Customer.CustEmail, email))
    if len(phone) >= 7:
        preds.append(_phone_like(m.Customer.Phone, phone))
    if site:
        preds.append(contains(m.Customer.CustWebSiteHLink, site))
    if not preds:
        return []

    stmt = select(m.Customer).options(selectinload(m.Customer.status)).where(or_(*preds)).limit(500)
    if exclude_id:
        stmt = stmt.where(m.Customer.CustomerID != exclude_id)

    out: list[Match] = []
    for c in db.execute(stmt).scalars():
        reasons, score = [], 0.0
        cn = norm_business(c.CustBusName)
        if name and cn == name:
            score = max(score, 0.95); reasons.append("same business name")
        elif name and similar(name, cn) >= 0.85:
            score = max(score, 0.70); reasons.append("similar business name")
        if email and (c.CustEmail or "").strip().lower() == email:
            score = max(score, 0.90); reasons.append("same e-mail")
        if len(phone) >= 7 and digits(c.Phone) == phone:
            score = max(score, 0.85); reasons.append("same phone number")
        if site and domain(c.CustWebSiteHLink) == site:
            score = max(score, 0.80); reasons.append("same website")
        if score >= SHOW_THRESHOLD:
            out.append(Match(
                id=c.CustomerID, name=c.CustBusName, score=score, reasons=reasons, city=c.City, state=c.State, phone=c.Phone,
                email=c.CustEmail, status=c.status.PulldownCustStatus if c.status else None,
            ))
    out.sort(key=lambda x: (-x.score, x.name))
    return [x.as_dict() for x in out[:limit]]


def blocking(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [x for x in matches if x["score"] >= BLOCK_THRESHOLD]
