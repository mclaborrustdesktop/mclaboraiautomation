from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from .. import models as m
from ..config import settings
from ..database import get_db
from ..integrity import validate_references
from ..schemas import Page, TrackingCreate, TrackingOut, TrackingSummary, TrackingUpdate
from ..search import DEFAULT_PAGE_SIZE, TRACKING_MAX_PAGE_SIZE, search_tracking, tracking_summary
from ..seed import week_ending
from ..security import require_feature

router = APIRouter(prefix="/api/tracking", tags=["tracking"])

_OPTS = (
    selectinload(m.Tracking.employee), selectinload(m.Tracking.customer), selectinload(m.Tracking.project),
    selectinload(m.Tracking.payroll_co_on_site),
)


def _load(db: Session, tracking_id: int, for_update: bool = False) -> m.Tracking:
    stmt = select(m.Tracking)
    if for_update and settings.db_backend != "sqlite":
        stmt = stmt.with_for_update()  # serialises two people saving the same week at the same moment
    t = db.execute(stmt.options(*_OPTS).where(m.Tracking.TrackingID == tracking_id)).scalar_one_or_none()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tracking record not found")
    return t


def tracking_out(t: m.Tracking) -> TrackingOut:
    out = TrackingOut.model_validate(t)
    s = tracking_summary(t)
    out.employee_name, out.customer_name, out.site_name, out.payroll_on_site = s["employee_name"], s["customer_name"], s["site_name"], s["payroll_on_site"]
    out.version = audit.row_version(t)
    return out


_HOURS = ("SatHours", "SunHours", "MonHours", "TueHours", "WedHours", "ThuHours", "FriHours")


def _check_numbers(data: dict) -> None:
    """Hours 0-24 per day, rates not negative: the rules the Access form enforces with its own checks."""
    problems = []
    for k in _HOURS:
        v = data.get(k)
        if v is not None and not 0 <= float(v) <= 24:
            problems.append(f"{k[:3]} hours must be between 0 and 24")
    for k in ("PayRate", "OTPayRate", "BillRate", "BillRateOT"):
        v = data.get(k)
        if v is not None and (float(v) < 0 or float(v) > 1000):
            problems.append(f"{k} must be between 0 and 1000")
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "; ".join(problems))


def _employee_usable(db: Session, employee_id: int) -> None:
    e = db.get(m.Employee, employee_id)
    if e is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown employee")
    if e.EmployeeNoCommunication:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{e.full_name} is marked 'do not contact' and cannot be assigned")
    if e.status and (e.status.PullDownEmployeeStatus or "").strip().lower() in ("do not use", "inactive"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{e.full_name} has status '{e.status.PullDownEmployeeStatus}' and cannot be assigned")


@router.get("/weeks")
def weeks(db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_feature("tracking.view"))):
    # the two most recent years of weeks; older weeks are reached by typing a date
    rows = db.execute(select(m.Tracking.WeekEndingDate).distinct().order_by(m.Tracking.WeekEndingDate.desc()).limit(104)).all()
    current = week_ending(date.today())
    dates = sorted({d for (d,) in rows} | {current, current + timedelta(weeks=1)}, reverse=True)
    return {"current": current, "weeks": dates}


@router.get("", response_model=Page[TrackingSummary])
def list_tracking(
    week_ending_date: date | None = None,
    employee_id: int | None = None,
    customer_id: int | None = None,
    project_id: int | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=TRACKING_MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    _: m.OfficeStaff = Depends(require_feature("tracking.view")),
):
    rows, total = search_tracking(db, week_ending_date, employee_id, customer_id, project_id, q, page, page_size)
    return Page(items=[tracking_summary(t) for t in rows], total=total, page=page, page_size=page_size)


def _validate_refs(db: Session, data: dict) -> None:
    if "EmployeeID" in data and db.get(m.Employee, data["EmployeeID"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown employee")
    if "ProjectID" in data:
        p = db.get(m.Project, data["ProjectID"])
        if p is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown project")
        data.setdefault("CustomerID", p.CustomerID)
        if data.get("CustomerID") != p.CustomerID:
            data["CustomerID"] = p.CustomerID  # project owns the customer relationship


@router.post("", response_model=TrackingOut, status_code=201)
def create_tracking(body: TrackingCreate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("tracking.edit"))):
    data = body.model_dump()
    _validate_refs(db, data)
    _employee_usable(db, data["EmployeeID"])
    _check_numbers(data)
    validate_references(db, m.Tracking, {k: data.get(k) for k in ("PayrollCoOnSiteID",)})
    we = week_ending(data["WeekEndingDate"])
    dup = db.execute(
        select(m.Tracking.TrackingID).where(
            m.Tracking.EmployeeID == data["EmployeeID"], m.Tracking.ProjectID == data["ProjectID"], m.Tracking.WeekEndingDate == we
        )
    ).first()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "This employee is already assigned to that job for this week")
    iso = we.isocalendar()
    data["WeekEndingDate"] = we
    if data.get("OTPayRate") is None:
        data["OTPayRate"] = round(float(data["PayRate"]) * 1.5, 2)
    if data.get("BillRateOT") is None:
        data["BillRateOT"] = round(float(data["BillRate"]) * 1.5, 2)
    t = m.Tracking(**data, AssignWeek=iso.week, AssignYear=iso.year, AssignmentUserName=user.Initials)
    t.recompute()
    db.add(t)
    db.flush()
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="tracking.create", OfficeStaffActivityObjectID=t.TrackingID))
    db.commit()
    t = _load(db, t.TrackingID)
    audit.record(user, "tracking.create", "tblTracking", t.TrackingID, None, audit.snapshot(t), summary=f"{t.employee.full_name if t.employee else ''} @ {t.project.SiteName if t.project else ''} week ending {we}")
    return tracking_out(t)


class BulkAssignRequest(BaseModel):
    ProjectID: int
    EmployeeIDs: list[int] = Field(..., min_length=1, max_length=100)
    WeekEndingDate: date
    PayrollCoOnSiteID: int | None = None
    PayRate: float | None = None  # None = use each employee's base rate
    BillRate: float | None = None  # None = pay rate x bill multiplier
    BillMultiplier: float = 1.5


@router.post("/bulk")
def bulk_assign(body: BulkAssignRequest, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("tracking.edit"))):
    """Assign several employees to one job for one week (from AI search multi-select)."""
    p = db.get(m.Project, body.ProjectID)
    if p is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown project")
    we = week_ending(body.WeekEndingDate)
    iso = we.isocalendar()
    created, skipped = [], []
    for eid in dict.fromkeys(body.EmployeeIDs):
        e = db.get(m.Employee, eid)
        if e is None:
            skipped.append({"EmployeeID": eid, "reason": "unknown employee"})
            continue
        dup = db.execute(
            select(m.Tracking.TrackingID).where(m.Tracking.EmployeeID == eid, m.Tracking.ProjectID == p.ProjectID, m.Tracking.WeekEndingDate == we)
        ).first()
        if dup:
            skipped.append({"EmployeeID": eid, "name": e.full_name, "reason": "already assigned that week"})
            continue
        pay = body.PayRate if body.PayRate is not None else float(e.BaseSalary or 0)
        bill = body.BillRate if body.BillRate is not None else round(pay * body.BillMultiplier, 2)
        t = m.Tracking(
            CustomerID=p.CustomerID, EmployeeID=eid, ProjectID=p.ProjectID, WeekEndingDate=we, AssignWeek=iso.week, AssignYear=iso.year,
            PayrollCoOnSiteID=body.PayrollCoOnSiteID, PayRate=pay, OTPayRate=round(pay * 1.5, 2), BillRate=bill, BillRateOT=round(bill * 1.5, 2),
            WCC=p.wcc.PullDownWCC if p.wcc else None, AssignmentUserName=user.Initials,
        )
        t.recompute()
        db.add(t)
        db.flush()
        created.append({"TrackingID": t.TrackingID, "EmployeeID": eid, "name": e.full_name, "PayRate": pay, "BillRate": bill})
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="tracking.bulk_assign", OfficeStaffActivityObjectID=p.ProjectID))
    db.commit()
    for row in created:
        audit.record(user, "tracking.create", "tblTracking", row["TrackingID"], None, {"EmployeeID": row["EmployeeID"], "ProjectID": p.ProjectID, "WeekEndingDate": we.isoformat(), "PayRate": row["PayRate"], "BillRate": row["BillRate"]},
                     summary=f"{row['name']} @ {p.SiteName} week ending {we}")
    return {"project": p.SiteName, "week_ending": we, "created": created, "skipped": skipped}


@router.get("/{tracking_id}", response_model=TrackingOut)
def get_tracking(tracking_id: int, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_feature("tracking.view"))):
    return tracking_out(_load(db, tracking_id))


@router.put("/{tracking_id}", response_model=TrackingOut)
def update_tracking(tracking_id: int, body: TrackingUpdate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("tracking.edit"))):
    t = _load(db, tracking_id, for_update=True)
    data = body.model_dump(exclude_unset=True)
    audit.require_version(t, data.pop("expected_version", None))
    before = audit.snapshot(t)
    _validate_refs(db, data)
    if "EmployeeID" in data and data["EmployeeID"] != t.EmployeeID:
        _employee_usable(db, data["EmployeeID"])
    _check_numbers(data)
    validate_references(db, m.Tracking, {k: data.get(k) for k in ("PayrollCoOnSiteID",) if k in data})
    if "WeekEndingDate" in data:
        we = week_ending(data["WeekEndingDate"])
        data["WeekEndingDate"] = we
        iso = we.isocalendar()
        t.AssignWeek, t.AssignYear = iso.week, iso.year
    for k, v in data.items():
        setattr(t, k, v)
    if any(k in data for k in ("EmployeeID", "ProjectID", "WeekEndingDate")):
        dup = db.execute(select(m.Tracking.TrackingID).where(m.Tracking.EmployeeID == t.EmployeeID, m.Tracking.ProjectID == t.ProjectID,
                                                             m.Tracking.WeekEndingDate == t.WeekEndingDate, m.Tracking.TrackingID != tracking_id)).first()
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "This employee is already assigned to that job for this week")
    t.recompute()
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="tracking.update", OfficeStaffActivityObjectID=tracking_id))
    db.commit()
    db.expire_all()
    t = _load(db, tracking_id)
    audit.record(user, "tracking.update", "tblTracking", tracking_id, before, audit.snapshot(t), summary=f"{t.employee.full_name if t.employee else ''} @ {t.project.SiteName if t.project else ''}")
    return tracking_out(t)


@router.delete("/{tracking_id}", status_code=204)
def delete_tracking(tracking_id: int, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("tracking.edit"))):
    t = _load(db, tracking_id)
    if t.TotalHours and not user.OfficeStaffCanDelete:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only users with delete rights can remove a week with hours entered")
    before = audit.snapshot(t)
    summary = f"{t.employee.full_name if t.employee else ''} @ {t.project.SiteName if t.project else ''} week ending {t.WeekEndingDate}"
    db.delete(t)
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="tracking.delete", OfficeStaffActivityObjectID=tracking_id))
    db.commit()
    audit.record(user, "tracking.delete", "tblTracking", tracking_id, before, None, summary=summary)
