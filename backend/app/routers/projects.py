from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit, derived
from .. import models as m
from ..config import settings
from ..database import get_db
from ..schemas import Page, ProjectCreate, ProjectOut, ProjectSummary, ProjectUpdate, TrackingSummary
from ..search import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, search_projects, tracking_summary
from ..security import require_feature
from ..integrity import validate_references
from .employees import _sync_city

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _load(db: Session, project_id: int, for_update: bool = False) -> m.Project:
    stmt = select(m.Project)
    if for_update and settings.db_backend != "sqlite":
        stmt = stmt.with_for_update()  # serialises two people saving the same job at the same moment
    p = db.execute(
        stmt
        .options(
            selectinload(m.Project.customer), selectinload(m.Project.status), selectinload(m.Project.wcc),
        )
        .where(m.Project.ProjectID == project_id)
    ).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


RECENT_ASSIGNMENTS = 60


def _recent_assignments(db: Session, project_id: int) -> list[m.Tracking]:
    """The newest weekly assignments of one job - a bounded query, never the job's whole history."""
    return list(db.execute(
        select(m.Tracking)
        .options(selectinload(m.Tracking.employee), selectinload(m.Tracking.customer), selectinload(m.Tracking.project), selectinload(m.Tracking.payroll_co_on_site))
        .where(m.Tracking.ProjectID == project_id).order_by(m.Tracking.WeekEndingDate.desc(), m.Tracking.TrackingID.desc()).limit(RECENT_ASSIGNMENTS)
    ).scalars().all())


def project_out(p: m.Project, db: Session) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    out.customer_name = p.customer.CustBusName if p.customer else None
    out.status_name = p.status.PullDownProjStatus if p.status else None
    out.wcc_code = p.wcc.PullDownWCC if p.wcc else None
    out.wcc_desc = p.wcc.PullDownWCCDesc if p.wcc else None
    out.assignments = [TrackingSummary(**tracking_summary(t)) for t in _recent_assignments(db, p.ProjectID)]
    out.version = audit.row_version(p)
    return out


@router.get("", response_model=Page[ProjectSummary])
def list_projects(
    q: str | None = None,
    customer_id: int | None = None,
    status_id: int | None = None,
    state: str | None = None,
    city: str | None = None,
    zip: str | None = Query(None, max_length=10),
    manned: bool | None = None,
    sort: str = Query("start", pattern="^(name|start|relevance)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    _: m.OfficeStaff = Depends(require_feature("projects.view")),
):
    filters = {k: v for k, v in dict(customer_id=customer_id, status_id=status_id, state=state, city=city, zip=zip, manned=manned).items() if v is not None}
    keywords = [t for t in (q or "").lower().split() if t]
    res = search_projects(db, filters, keywords, page, page_size, sort="relevance" if keywords and sort == "start" else sort, strict_keywords=True)
    return Page(items=res.items, total=res.total, page=page, page_size=page_size, facets=res.facets)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("projects.edit"))):
    if db.get(m.Customer, body.CustomerID) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown customer")
    data = body.model_dump()
    validate_references(db, m.Project, data)
    _sync_city(db, data, "SiteStateCityID", "SiteCity", "SiteState")
    derived.prepare_project(data)
    p = m.Project(**data, ProjectEntryUserName=user.Initials)
    db.add(p)
    db.flush()
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="project.create", OfficeStaffActivityObjectID=p.ProjectID))
    db.commit()
    p = _load(db, p.ProjectID)
    audit.record(user, "project.create", "tblProject", p.ProjectID, None, audit.snapshot(p), summary=p.SiteName)
    return project_out(p, db)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_feature("projects.view"))):
    return project_out(_load(db, project_id), db)


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("projects.edit"))):
    p = _load(db, project_id, for_update=True)
    data = body.model_dump(exclude_unset=True)
    audit.require_version(p, data.pop("expected_version", None))
    before = audit.snapshot(p)
    if "CustomerID" in data and db.get(m.Customer, data["CustomerID"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown customer")
    if "CustomerID" in data and data["CustomerID"] != p.CustomerID and db.execute(select(m.Tracking.TrackingID).where(m.Tracking.ProjectID == project_id).limit(1)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This job already has weekly tracking for its customer; it cannot be moved to another customer")
    validate_references(db, m.Project, data)
    _sync_city(db, data, "SiteStateCityID", "SiteCity", "SiteState")
    derived.prepare_project(data)
    for k, v in data.items():
        setattr(p, k, v)
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="project.update", OfficeStaffActivityObjectID=project_id))
    db.commit()
    db.expire_all()
    p = _load(db, project_id)
    audit.record(user, "project.update", "tblProject", project_id, before, audit.snapshot(p), summary=p.SiteName)
    return project_out(p, db)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("projects.edit"))):
    if not user.OfficeStaffCanDelete:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account cannot delete records")
    p = _load(db, project_id)
    if db.execute(select(m.Tracking.TrackingID).where(m.Tracking.ProjectID == project_id).limit(1)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Project has tracking history; set status to Cancelled instead")
    before, name = audit.snapshot(p), p.SiteName
    db.delete(p)
    db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="project.delete", OfficeStaffActivityObjectID=project_id))
    db.commit()
    audit.record(user, "project.delete", "tblProject", project_id, before, None, summary=name)
