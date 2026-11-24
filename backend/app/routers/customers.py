from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from .. import models as m
from ..config import settings
from ..database import get_db
from ..schemas import CustomerCreate, CustomerNoteIn, CustomerNoteOut, CustomerOut, CustomerSummary, CustomerUpdate, Page, ProjectSummary
from ..duplicates import blocking, find_customer_duplicates
from ..integrity import validate_references
from ..search import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, assigned_counts, project_summary, search_customers
from ..security import require_feature
from .employees import _sync_city

router = APIRouter(prefix="/api/customers", tags=["customers"])


class CustomerDuplicateCheck(BaseModel):
    CustBusName: str | None = None
    Phone: str | None = None
    CustEmail: str | None = None
    CustWebSiteHLink: str | None = None
    exclude_id: int | None = None


def _load(db: Session, customer_id: int, for_update: bool = False) -> m.Customer:
    stmt = select(m.Customer)
    if for_update and settings.db_backend != "sqlite":
        stmt = stmt.with_for_update()  # serialises two people saving the same customer at the same moment
    c = db.execute(
        stmt
        .options(
            selectinload(m.Customer.status), selectinload(m.Customer.customer_type), selectinload(m.Customer.salesman),
            selectinload(m.Customer.sales_status), selectinload(m.Customer.payroll_co),
            selectinload(m.Customer.contacts).selectinload(m.CustomerContact.title),
            selectinload(m.Customer.notes),
            selectinload(m.Customer.projects).selectinload(m.Project.status),
            selectinload(m.Customer.projects).selectinload(m.Project.wcc),
            selectinload(m.Customer.projects).selectinload(m.Project.customer),
        )
        .where(m.Customer.CustomerID == customer_id)
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return c


def customer_out(c: m.Customer, db: Session | None = None) -> CustomerOut:
    out = CustomerOut.model_validate(c)
    out.status_name = c.status.PulldownCustStatus if c.status else None
    out.type_name = c.customer_type.PullDownCustomerType if c.customer_type else None
    out.salesman_name = f"{c.salesman.PullDownSalesmanFName} {c.salesman.PullDownSalesmanLName}" if c.salesman else None
    out.sales_status_name = c.sales_status.PullDownSalesStatus if c.sales_status else None
    out.payroll_co_name = c.payroll_co.PullDownContractWith_PayrollCoName if c.payroll_co else None
    for co, contact in zip(out.contacts, c.contacts):
        co.title_name = contact.title.PullDownCustomerContactTitle if contact.title else None
    assigned = assigned_counts(db, [p.ProjectID for p in c.projects]) if db is not None else {}
    out.projects = [ProjectSummary(**project_summary(p, None, assigned.get(p.ProjectID, 0)))
                    for p in sorted(c.projects, key=lambda p: p.StartDate or p.ProjectEntryTimestamp.date(), reverse=True)]
    out.version = audit.row_version(c, _children(c))
    return out


def _children(c: m.Customer) -> dict[str, list]:
    return {"contacts": list(c.contacts)}


@router.get("", response_model=Page[CustomerSummary])
def list_customers(
    q: str | None = None,
    status_id: int | None = None,
    type_id: int | None = None,
    salesman_id: int | None = None,
    state: str | None = None,
    city: str | None = None,
    zip: str | None = Query(None, max_length=10),
    on_hold: bool | None = None,
    sort: str = Query("name", pattern="^(name|newest|revenue|relevance)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    _: m.OfficeStaff = Depends(require_feature("customers.view")),
):
    filters = {k: v for k, v in dict(status_id=status_id, type_id=type_id, salesman_id=salesman_id, state=state, city=city, zip=zip, on_hold=on_hold).items() if v is not None}
    keywords = [t for t in (q or "").lower().split() if t]
    res = search_customers(db, filters, keywords, page, page_size, sort="relevance" if keywords and sort == "name" else sort, strict_keywords=True)
    return Page(items=res.items, total=res.total, page=page, page_size=page_size, facets=res.facets)


@router.post("", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerCreate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("customers.edit"))):
    data = body.model_dump(exclude={"contacts", "allow_duplicate"})
    validate_references(db, m.Customer, data)
    for ct in body.contacts:
        validate_references(db, m.CustomerContact, ct.model_dump())
    _sync_city(db, data, "StateCityID", "City", "State")
    matches = blocking(find_customer_duplicates(db, data))
    if matches and not body.allow_duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "This looks like a customer that is already on file.", "matches": matches})
    c = m.Customer(**data, CustEntryUserName=user.Initials)
    for ct in body.contacts:
        c.contacts.append(m.CustomerContact(**ct.model_dump(), CustomerContactUserName=user.Initials))
    db.add(c)
    db.flush()
    action = "customer.create.duplicate_confirmed" if matches else "customer.create"
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName=action, OfficeStaffActivityObjectID=c.CustomerID))
    db.commit()
    c = _load(db, c.CustomerID)
    audit.record(user, action, "tblCustomer", c.CustomerID, None, audit.snapshot(c, _children(c)), summary=c.CustBusName)
    return customer_out(c, db)


@router.post("/check-duplicates")
def check_duplicates(body: CustomerDuplicateCheck, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_feature("customers.view"))):
    """Likely/possible existing customers for the given business name, phone, e-mail or website."""
    return {"matches": find_customer_duplicates(db, body.model_dump(exclude={"exclude_id"}), exclude_id=body.exclude_id)}


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_feature("customers.view"))):
    return customer_out(_load(db, customer_id), db)


@router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, body: CustomerUpdate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("customers.edit"))):
    c = _load(db, customer_id, for_update=True)
    data = body.model_dump(exclude_unset=True)
    audit.require_version(c, data.pop("expected_version", None), _children(c))
    before = audit.snapshot(c, _children(c))
    contacts = data.pop("contacts", None)
    validate_references(db, m.Customer, data)
    for ct in contacts or []:
        validate_references(db, m.CustomerContact, ct)
    _sync_city(db, data, "StateCityID", "City", "State")
    for k, v in data.items():
        setattr(c, k, v)
    if contacts is not None:
        c.contacts.clear()
        db.flush()
        for ct in contacts:
            c.contacts.append(m.CustomerContact(**ct, CustomerContactUserName=user.Initials))
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="customer.update", OfficeStaffActivityObjectID=customer_id))
    db.commit()
    db.expire_all()
    c = _load(db, customer_id)
    audit.record(user, "customer.update", "tblCustomer", customer_id, before, audit.snapshot(c, _children(c)), summary=c.CustBusName)
    return customer_out(c, db)


@router.post("/{customer_id}/notes", response_model=CustomerNoteOut, status_code=201)
def add_note(customer_id: int, body: CustomerNoteIn, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("customers.edit"))):
    _load(db, customer_id)
    n = m.CustomerNote(CustomerID=customer_id, CustomerNoteUserName=user.Initials, CustomerNote=body.CustomerNote)
    db.add(n)
    db.commit()
    db.refresh(n)
    audit.record(user, "customer.note", "tblCustomer", customer_id, None, None, summary=body.CustomerNote[:300])
    return CustomerNoteOut.model_validate(n)


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: int, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("customers.edit"))):
    if not user.OfficeStaffCanDelete:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account cannot delete records")
    c = _load(db, customer_id)
    if c.projects:
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer has jobs on file; set status to Inactive instead")
    before, name = audit.snapshot(c, _children(c)), c.CustBusName
    db.delete(c)
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="customer.delete", OfficeStaffActivityObjectID=customer_id))
    db.commit()
    audit.record(user, "customer.delete", "tblCustomer", customer_id, before, None, summary=name)
