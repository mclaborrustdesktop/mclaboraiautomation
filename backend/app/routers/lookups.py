from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..config import settings
from ..database import get_db
from ..schemas import LookupItem, Lookups
from ..security import get_current_user

router = APIRouter(prefix="/api/lookups", tags=["lookups"])


def _items(db: Session, model, id_col: str, label_col: str, sort_col: str | None = None, extra=None) -> list[LookupItem]:
    stmt = select(model)
    if sort_col:
        stmt = stmt.order_by(getattr(model, sort_col))
    out = []
    for row in db.execute(stmt).scalars():
        label = getattr(row, label_col)
        if label is None or not str(label).strip():
            continue  # real lookup tables contain a few blank entries
        out.append(LookupItem(id=getattr(row, id_col), label=str(label), extra=extra(row) if extra else None))
    return out


@router.get("", response_model=Lookups)
def lookups(db: Session = Depends(get_db), _: m.OfficeStaff = Depends(get_current_user)):
    return Lookups(
        restricted_fields=settings.restricted_field_names,
        environment=settings.environment,
        site_mode="search-only" if settings.search_only else "full",
        trades=_items(db, m.PullDownTrade, "PullDownTradeID", "PullDownTrade", "PullDownTradeSort",
                      lambda r: {"division_id": r.PullDownTradeDivisionID}),
        states=_items(db, m.PullDownState, "PullDownStateID", "PullDownState", "PullDownStateSort",
                      lambda r: {"name": r.PullDownStateName}),
        cities=_items(db, m.PullDownStateCity, "PullDownStateCityID", "City", "City",
                      lambda r: {"state_id": r.StateID, "state": r.state.PullDownState if r.state else None}),
        employee_statuses=_items(db, m.PullDownEmployeeStatus, "PullDownEmployeeStatusID", "PullDownEmployeeStatus", "PullDownEmployeeStatusSort"),
        qualifications=_items(db, m.PullDownQualification, "PullDownQualificationID", "PullDownQualification", "PullDownQualificationSort"),
        experience=_items(db, m.PullDownExperience, "PullDownExperienceID", "PullDownExperience", "PullDownExperienceSort"),
        license_types=_items(db, m.PullDownLicenseType, "PullDownLicenseTypeID", "PullDownLicenseType", "PullDownLicenseTypeSort"),
        customer_statuses=_items(db, m.PullDownCustStatus, "PulldownCustStatusID", "PulldownCustStatus", "PulldownCustStatusSort"),
        customer_types=_items(db, m.PullDownCustomerType, "PullDownCustomerTypeID", "PullDownCustomerType", "PullDownCustomerTypeSort"),
        sales_statuses=_items(db, m.PullDownSalesStatus, "PullDownSalesStatusID", "PullDownSalesStatus", "PullDownSalesStatusSort"),
        project_statuses=_items(db, m.PullDownProjStatus, "PullDownProjStatusID", "PullDownProjStatus", "PullDownProjStatusSort"),
        wcc=[LookupItem(id=r.PullDownWCCID, label=" - ".join(str(p) for p in (r.PullDownWCC, r.PullDownWCCDesc) if p) or f"#{r.PullDownWCCID}") for r in db.execute(select(m.PullDownWCC).order_by(m.PullDownWCC.PullDownWCCSort)).scalars()],
        payroll_companies=_items(db, m.PullDownContractWithPayrollCo, "PullDownContractWith_PayrollCoID", "PullDownContractWith_PayrollCoName", "PullDownContractWith_PayrollCoSort",
                                 lambda r: {"initials": r.PullDownContractWith_PayrollCoInitials}),
        payroll_on_site=_items(db, m.PullDownPayrollCoOnSite, "PullDownPayrollCoOnSiteID", "PullDownPayrollCoOnSiteName", "PullDownPayrollCoOnSiteSort",
                               lambda r: {"initials": r.PullDownPayrollCoOnSiteInitials}),
        salesmen=[LookupItem(id=r.PullDownSalesmanID, label=" ".join(p for p in (r.PullDownSalesmanFName, r.PullDownSalesmanLName) if p) or f"#{r.PullDownSalesmanID}", extra={"active": r.PullDownSalesmanActive})
                  for r in db.execute(select(m.PullDownSalesman).order_by(m.PullDownSalesman.PullDownSalesmanSort)).scalars()],
        contact_titles=_items(db, m.PullDownCustomerContactTitle, "PullDownCustomerContactTitleID", "PullDownCustomerContactTitle", "PullDownCustomerContactTitleSort"),
        note_types=_items(db, m.PullDownEmployeeNoteType, "PullDownEmployeeNoteTypeID", "PullDownEmployeeNoteType", "PullDownEmployeeNoteTypeSort"),
        divisions=_items(db, m.PullDownDivision, "PullDownDivisionID", "PullDownDivision", "PullDownDivisionSort"),
        # Real data: tblFeature lists 1,100+ Access forms and buttons, none of which is a website page.
        features=[] if settings.is_real_data else [
            LookupItem(id=r.FeatureID, label=r.FeatureTitle or r.ObjectName or f"#{r.FeatureID}", extra={"object": r.ObjectName, "description": r.FeatureDescription})
            for r in db.execute(select(m.Feature).order_by(m.Feature.FeatureSort)).scalars()],
    )
