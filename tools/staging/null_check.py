"""Which columns the website treats as "always filled in" are actually empty (NULL) in the real data? Counts only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

CHECK = {
    "tblOfficeStaff": "OfficeStaffFirstName OfficeStaffLastName OfficeStaffFullName Initials OfficeStaffActive OfficeStaffCanDelete OfficeStaffEmployeeResearch OfficeStaffHideHours OfficeStaffTrackingReportEmailReceive Profile",
    "tblEmployeeNotes": "EmployeeNote EmployeeNoteTimestamp EmployeeID",
    "tblEmployee": "EmFirstName EmLastName PostEmployeeAsAvailable EmEntryTimestamp EmployeeDuplicate",
    "tblEmployeeLicenses": "EmployeeID",
    "tblCustomerNotes": "CustomerNote CustomerNoteTimestamp CustomerNoteActive CustomerID",
    "tblCustomerContacts": "CustomerID",
    "tblCustomer": "CustBusName ContractOnFile OnHold CustEntryTimestamp",
    "tblProject": "CustomerID SiteName NumberOfEmployees JobBeingManned ProjectEntryTimestamp OCIPJob RateJob",
    "tblTracking": "CustomerID EmployeeID ProjectID WeekEndingDate AssignWeek AssignYear PayRate BillRate TotalHours RegularHours OvertimeHours InvoiceAmount EmGrossPayroll DirVerified Placeholder AssignmentTimestamp",
    "tblPullDownSalesman": "PullDownSalesmanActive",
}
with engine.connect() as c:
    for table, cols in CHECK.items():
        cols = cols.split()
        row = c.execute(text(f"SELECT COUNT({cols[0]}) + SUM(CASE WHEN {cols[0]} IS NULL THEN 1 ELSE 0 END), " + ", ".join(f"SUM(CASE WHEN {x} IS NULL THEN 1 ELSE 0 END)" for x in cols) + f" FROM dbo.{table}")).one()
        empty = [f"{x} ({n:,})" for x, n in zip(cols, row[1:]) if n]
        print(f"{table} ({row[0]:,} rows): " + ("NULL in " + ", ".join(empty) if empty else "all filled"))
    c.rollback()
