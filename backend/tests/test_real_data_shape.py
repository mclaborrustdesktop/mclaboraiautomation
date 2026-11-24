"""Problems found by the first run against the real (staging) database on 2026-11-20."""
from types import SimpleNamespace

from app import models as m
from app.ai import heuristic_interpret
from app.config import settings
from app.schemas import ProjectSummary, TrackingSummary
from app.search import _unique_order
from app.security import is_web_admin, user_has_feature


def test_order_by_never_names_a_column_twice():
    # SQL Server: "A column has been specified more than once in the order by list" (newest first + id tie-breaker)
    E = m.Employee
    assert len(_unique_order([E.EmployeeID.desc(), E.EmployeeID])) == 1
    assert len(_unique_order([E.EmLastName, E.EmployeeID.desc(), E.EmployeeID, E.EmLastName.desc()])) == 2


def test_null_numbers_in_real_rows_do_not_break_a_page():
    job = ProjectSummary(ProjectID=1, CustomerID=2, SiteName="Site", SiteCity=None, SiteState=None, StartDate=None, EndDate=None,
                         NumberOfEmployees=None, JobBeingManned=None, ContractAmount=None)
    assert job.NumberOfEmployees == 0 and job.JobBeingManned is False
    row = TrackingSummary(TrackingID=1, CustomerID=1, EmployeeID=1, ProjectID=1, WeekEndingDate="2026-11-13", AssignWeek=46, AssignYear=2026,
                          PayRate=None, BillRate=None, TotalHours=None, RegularHours=None, OvertimeHours=None, InvoiceAmount=None,
                          EmGrossPayroll=None, CalcProfitMargin=None, Grade=None, DirVerified=None, Placeholder=None)
    assert row.TotalHours == 0 and row.PayRate == 0 and row.CalcProfitMargin is None


def test_junk_two_letter_cities_are_not_taken_for_a_city():
    vocab = {"cities": ["Ma", "NY", "St", "P", "Boston"], "industries": [], "salesmen": [], "customers": []}
    assert "city" not in heuristic_interpret("employees", "licensed electricians in MA", vocab).filters
    assert heuristic_interpret("employees", "electricians in boston", vocab).filters["city"] == "Boston"


def test_website_administrators_with_real_data_come_from_settings(monkeypatch):
    staff = SimpleNamespace(OfficeStaffID=77, Initials="AB", Profile=True, permissions=[])
    assert is_web_admin(staff)  # demo: the Profile flag
    monkeypatch.setattr(settings, "data_source", "staging")
    monkeypatch.setattr(settings, "web_admins", "")
    assert not is_web_admin(staff) and not user_has_feature(staff, "employees.view")  # the flag in the database is ignored
    monkeypatch.setattr(settings, "web_admins", "xy, ab")
    assert is_web_admin(staff) and user_has_feature(staff, "employees.view")
    monkeypatch.setattr(settings, "web_admins", "77")
    assert is_web_admin(staff)
