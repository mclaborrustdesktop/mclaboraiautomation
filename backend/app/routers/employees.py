from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit, derived
from .. import models as m
from ..config import settings
from ..database import get_db
from ..schemas import (
    EmployeeCreate, EmployeeNoteIn, EmployeeNoteOut, EmployeeOut, EmployeeSummary, EmployeeUpdate, Page, TrackingSummary,
)
from ..duplicates import blocking, find_employee_duplicates
from ..integrity import validate_references
from ..search import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, search_employees, tracking_summary
from ..security import require_feature

router = APIRouter(prefix="/api/employees", tags=["employees"])


class EmployeeDuplicateCheck(BaseModel):
    EmFirstName: str | None = None
    EmLastName: str | None = None
    EmMobilePhone: str | None = None
    EmHomePhone: str | None = None
    EmEmail: str | None = None
    EmDOB: date | None = None
    EmCity: str | None = None
    exclude_id: int | None = None


def _load(db: Session, employee_id: int, for_update: bool = False) -> m.Employee:
    """``for_update`` locks the row until the transaction ends, so two people saving at the same moment are
    serialised and the second one's version check sees the first one's change (PostgreSQL / SQL Server; SQLite ignores it)."""
    stmt = select(m.Employee)
    if for_update and settings.db_backend != "sqlite":
        stmt = stmt.with_for_update()
    e = db.execute(
        stmt
        .options(
            selectinload(m.Employee.status), selectinload(m.Employee.trade), selectinload(m.Employee.sub_trade1),
            selectinload(m.Employee.sub_trade2), selectinload(m.Employee.qualification), selectinload(m.Employee.experience),
            selectinload(m.Employee.payroll_co),
            selectinload(m.Employee.licenses).selectinload(m.EmployeeLicense.state),
            selectinload(m.Employee.licenses).selectinload(m.EmployeeLicense.trade),
            selectinload(m.Employee.licenses).selectinload(m.EmployeeLicense.license_type),
            selectinload(m.Employee.notes).selectinload(m.EmployeeNote.note_type),
        )
        .where(m.Employee.EmployeeID == employee_id)
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return e


def employee_out(db: Session, e: m.Employee) -> EmployeeOut:
    recent = db.execute(
        select(m.Tracking)
        .options(selectinload(m.Tracking.customer), selectinload(m.Tracking.project), selectinload(m.Tracking.employee),
                 selectinload(m.Tracking.payroll_co_on_site))
        .where(m.Tracking.EmployeeID == e.EmployeeID)
        .order_by(m.Tracking.WeekEndingDate.desc())
        .limit(12)
    ).scalars().all()
    out = EmployeeOut.model_validate(e)
    out.status_name = e.status.PullDownEmployeeStatus if e.status else None
    out.trade_name = e.trade.PullDownTrade if e.trade else None
    out.sub_trade1_name = e.sub_trade1.PullDownTrade if e.sub_trade1 else None
    out.sub_trade2_name = e.sub_trade2.PullDownTrade if e.sub_trade2 else None
    out.qualification_name = e.qualification.PullDownQualification if e.qualification else None
    out.experience_name = e.experience.PullDownExperience if e.experience else None
    out.payroll_co_name = e.payroll_co.PullDownContractWith_PayrollCoName if e.payroll_co else None
    for lic_out, lic in zip(out.licenses, e.licenses):
        lic_out.state_code = lic.state.PullDownState if lic.state else None
        lic_out.trade_name = lic.trade.PullDownTrade if lic.trade else None
        lic_out.license_type_name = lic.license_type.PullDownLicenseType if lic.license_type else None
    for n_out, n in zip(out.notes, e.notes):
        n_out.note_type_name = n.note_type.PullDownEmployeeNoteType if n.note_type else None
    out.recent_assignments = [TrackingSummary(**tracking_summary(t)) for t in recent]
    out.version = audit.row_version(e, _children(e))
    return out


def _children(e: m.Employee) -> dict[str, list]:
    return {"licenses": list(e.licenses)}


@router.get("", response_model=Page[EmployeeSummary])
def list_employees(
    q: str | None = Query(None, description="Free text (name, city, notes)"),
    trade_id: int | None = None,
    status_id: int | None = None,
    state: str | None = None,
    city: str | None = None,
    zip: str | None = Query(None, max_length=10, description="ZIP code or its first digits"),
    available: bool | None = None,
    licensed: bool | None = None,
    min_years: int | None = None,
    sort: str = Query("name", pattern="^(name|newest|relevance|years|rate)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    _: m.OfficeStaff = Depends(require_feature("employees.view")),
):
    filters = {k: v for k, v in dict(trade_id=trade_id, status_id=status_id, state=state, city=city, zip=zip, available=available,
                                     licensed=licensed, min_years=min_years).items() if v is not None}
    keywords = [t for t in (q or "").lower().split() if t]
    res = search_employees(db, filters, keywords, page, page_size, sort="relevance" if keywords and sort == "name" else sort, strict_keywords=True)
    return Page(items=res.items, total=res.total, page=page, page_size=page_size, facets=res.facets)


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeCreate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("employees.edit"))):
    data = _drop_restricted(body.model_dump(exclude={"licenses", "allow_duplicate"}))
    validate_references(db, m.Employee, data)
    for lic in body.licenses:
        validate_references(db, m.EmployeeLicense, lic.model_dump())
    _sync_city(db, data, "EmStateCityID", "EmCity", "EmState")
    matches = blocking(find_employee_duplicates(db, data))
    if matches and not body.allow_duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "This looks like an employee who is already on file.", "matches": matches})
    after = derived.prepare_employee(db, data)
    e = m.Employee(**data, EmEntryUserName=user.Initials)
    for lic in body.licenses:
        e.licenses.append(m.EmployeeLicense(**lic.model_dump()))
    db.add(e)
    db.flush()
    if after:
        after(e.EmployeeID)
    action = "employee.create.duplicate_confirmed" if matches else "employee.create"
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName=action, OfficeStaffActivityObjectID=e.EmployeeID))
    db.commit()
    e = _load(db, e.EmployeeID)
    audit.record(user, action, "tblEmployee", e.EmployeeID, None, audit.snapshot(e, _children(e)), summary=e.full_name)
    return employee_out(db, e)


@router.post("/check-duplicates")
def check_duplicates(body: EmployeeDuplicateCheck, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_feature("employees.view"))):
    """Likely/possible existing employees for the given name, phone, e-mail or DOB (used while typing a new record)."""
    data = body.model_dump(exclude={"exclude_id"})
    return {"matches": find_employee_duplicates(db, data, exclude_id=body.exclude_id)}


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_feature("employees.view"))):
    return employee_out(db, _load(db, employee_id))


@router.put("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, body: EmployeeUpdate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("employees.edit"))):
    e = _load(db, employee_id, for_update=True)
    data = _drop_restricted(body.model_dump(exclude_unset=True))
    audit.require_version(e, data.pop("expected_version", None), _children(e))
    before = audit.snapshot(e, _children(e))
    licenses = data.pop("licenses", None)
    validate_references(db, m.Employee, data)
    for lic in licenses or []:
        validate_references(db, m.EmployeeLicense, lic)
    _sync_city(db, data, "EmStateCityID", "EmCity", "EmState")
    after = derived.prepare_employee(db, data)
    for k, v in data.items():
        setattr(e, k, v)
    if licenses is not None:
        e.licenses.clear()
        db.flush()
        for lic in licenses:
            e.licenses.append(m.EmployeeLicense(**lic))
    db.flush()
    if after:
        after(employee_id)
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="employee.update", OfficeStaffActivityObjectID=employee_id))
    db.commit()
    db.expire_all()
    e = _load(db, employee_id)
    audit.record(user, "employee.update", "tblEmployee", employee_id, before, audit.snapshot(e, _children(e)), summary=e.full_name)
    return employee_out(db, e)


@router.post("/{employee_id}/notes", response_model=EmployeeNoteOut, status_code=201)
def add_note(employee_id: int, body: EmployeeNoteIn, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("employees.edit"))):
    _load(db, employee_id)
    validate_references(db, m.EmployeeNote, body.model_dump())
    n = m.EmployeeNote(EmployeeID=employee_id, EmployeeNoteUserName=user.Initials, **body.model_dump())
    db.add(n)
    db.commit()
    db.refresh(n)
    out = EmployeeNoteOut.model_validate(n)
    out.note_type_name = n.note_type.PullDownEmployeeNoteType if n.note_type else None
    audit.record(user, "employee.note", "tblEmployee", employee_id, None, None, summary=body.EmployeeNote[:300])
    return out


@router.delete("/{employee_id}", status_code=204)
def delete_employee(employee_id: int, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("employees.edit"))):
    if not user.OfficeStaffCanDelete:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account cannot delete records")
    e = _load(db, employee_id)
    if db.execute(select(m.Tracking.TrackingID).where(m.Tracking.EmployeeID == employee_id).limit(1)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Employee has tracking history; set status to Inactive instead")
    before = audit.snapshot(e, _children(e))
    name = e.full_name
    db.delete(e)
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="employee.delete", OfficeStaffActivityObjectID=employee_id))
    db.commit()
    audit.record(user, "employee.delete", "tblEmployee", employee_id, before, None, summary=name)


def _drop_restricted(data: dict) -> dict:
    """Restricted fields (date of birth, citizenship, I-9) are never sent to the production database."""
    hidden = settings.restricted_field_names
    return {k: v for k, v in data.items() if k not in hidden} if hidden else data


def _sync_city(db: Session, data: dict, id_key: str, city_key: str, state_key: str) -> None:
    """Keep the denormalised City/State text in step with the StateCityID lookup."""
    cid = data.get(id_key)
    if cid:
        sc = db.get(m.PullDownStateCity, cid)
        if sc is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown city id")
        data[city_key] = sc.City
        data[state_key] = sc.state.PullDownState
