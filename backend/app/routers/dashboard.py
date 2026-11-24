from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as m
from ..ai import ai_mode
from ..database import get_db
from ..schemas import DashboardStats
from ..seed import week_ending
from ..security import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db), _: m.OfficeStaff = Depends(get_current_user)):
    we = week_ending(date.today())
    count = lambda stmt: db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()  # noqa: E731

    active_status_ids = select(m.PullDownEmployeeStatus.PullDownEmployeeStatusID).where(
        m.PullDownEmployeeStatus.PullDownEmployeeStatus.in_(["Active", "Available", "On Assignment"])
    )
    employees_total = count(select(m.Employee.EmployeeID))
    employees_active = count(select(m.Employee.EmployeeID).where(m.Employee.EmEmployeeStatusID.in_(active_status_ids)))
    employees_available = count(select(m.Employee.EmployeeID).where(m.Employee.PostEmployeeAsAvailable == True))
    customers_total = count(select(m.Customer.CustomerID))
    customers_active = count(
        select(m.Customer.CustomerID).join(m.PullDownCustStatus).where(m.PullDownCustStatus.PulldownCustStatus == "Active")
    )
    projects_total = count(select(m.Project.ProjectID))
    projects_active = count(
        select(m.Project.ProjectID).join(m.PullDownProjStatus).where(m.PullDownProjStatus.PullDownProjStatus == "Active")
    )
    wk = db.execute(
        select(
            func.count(m.Tracking.TrackingID),
            func.coalesce(func.sum(m.Tracking.TotalHours), 0),
            func.coalesce(func.sum(m.Tracking.InvoiceAmount), 0),
            func.coalesce(func.sum(m.Tracking.EmGrossPayroll), 0),
        ).where(m.Tracking.WeekEndingDate == we)
    ).one()
    invoice, payroll = float(wk[2]), float(wk[3])
    margin = round((invoice - payroll) / invoice, 4) if invoice else None
    users_total = count(select(m.OfficeStaff.OfficeStaffID).where(m.OfficeStaff.OfficeStaffActive == True))
    cutoff = date.today() + timedelta(days=90)
    licenses_expiring = count(
        select(m.EmployeeLicense.EmployeeLicenseID).where(m.EmployeeLicense.EmployeeLicenseExpDate.between(date.today(), cutoff))
    )
    top_trades = [
        {"trade": t, "count": c}
        for t, c in db.execute(
            select(m.PullDownTrade.PullDownTrade, func.count(m.Employee.EmployeeID))
            .join(m.Employee, m.Employee.EmTradeID == m.PullDownTrade.PullDownTradeID)
            .group_by(m.PullDownTrade.PullDownTrade)
            .order_by(func.count(m.Employee.EmployeeID).desc())
            .limit(8)
        ).all()
    ]
    weekly = [
        {"week_ending": d, "hours": float(h or 0), "invoice": float(i or 0), "payroll": float(p or 0), "workers": int(n or 0)}
        for d, h, i, p, n in db.execute(
            select(
                m.Tracking.WeekEndingDate,
                func.sum(m.Tracking.TotalHours),
                func.sum(m.Tracking.InvoiceAmount),
                func.sum(m.Tracking.EmGrossPayroll),
                func.count(func.distinct(m.Tracking.EmployeeID)),
            )
            .where(m.Tracking.WeekEndingDate <= we)
            .group_by(m.Tracking.WeekEndingDate)
            .order_by(m.Tracking.WeekEndingDate.desc())
            .limit(12)
        ).all()
    ][::-1]
    activity = [
        {"when": a.OfficeStaffActivityTimestampStart, "user": s.Initials, "action": a.OfficeStaffActivityObjectName, "object_id": a.OfficeStaffActivityObjectID}
        for a, s in db.execute(
            select(m.OfficeStaffActivity, m.OfficeStaff)
            .join(m.OfficeStaff, m.OfficeStaff.OfficeStaffID == m.OfficeStaffActivity.OfficeStaffID)
            .order_by(m.OfficeStaffActivity.OfficeStaffActivityID.desc())
            .limit(10)
        ).all()
    ]
    return DashboardStats(
        employees_total=employees_total, employees_active=employees_active, employees_available=employees_available,
        customers_total=customers_total, customers_active=customers_active, projects_total=projects_total,
        projects_active=projects_active, assignments_this_week=int(wk[0]), hours_this_week=float(wk[1]),
        invoice_this_week=invoice, payroll_this_week=payroll, margin_this_week=margin, users_total=users_total,
        licenses_expiring_90d=licenses_expiring, week_ending=we, top_trades=top_trades, weekly_hours=weekly,
        recent_activity=activity, ai_mode=ai_mode(),
    )
