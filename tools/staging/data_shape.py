"""How the real data is filled in - COUNTS AND FORMATS ONLY, never a record.

    powershell -File tools\\staging\\run-in-staging.ps1 ..\\tools\\staging\\data_shape.py

Phone numbers are shown only as shapes (every digit replaced by 9). State codes, trade and status labels are
lookup values, not personal data. Read-only: the engine's statement guard refuses anything but SELECT.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402

assert settings.is_staging, "staging only"

FILLED = "SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CAST({c} AS nvarchar(200)))), '') IS NOT NULL THEN 1 ELSE 0 END) AS [{c}]"


def filled(conn, table, cols):
    row = conn.execute(text(f"SELECT COUNT(*) AS total, {', '.join(FILLED.format(c=c) for c in cols)} FROM dbo.{table}")).mappings().one()
    print(f"{table}: {row['total']:,} rows. Filled in:")
    for c in cols:
        print(f"    {c:28} {row[c]:>9,}  ({100 * row[c] / max(1, row['total']):.0f}%)")


def top(conn, label, sql, n=8):
    print(label)
    for value, count in conn.execute(text(sql)).fetchmany(n):
        print(f"    {str(value)!r:32} {count:>9,}")


with engine.connect() as conn:
    filled(conn, "tblEmployee", ["EmState", "EmCity", "EmStateCityID", "EmZip", "EmMobilePhone", "EmHomePhone", "EmEmail", "EmTradeID",
                                 "EmEmployeeStatusID", "YearsInTradeID", "EmLicenseNum", "EmLicensedIn", "EmployeeDuplicate"])
    top(conn, "tblEmployee.EmployeeDuplicate values:", "SELECT EmployeeDuplicate, COUNT(*) FROM dbo.tblEmployee GROUP BY EmployeeDuplicate ORDER BY 2 DESC")
    top(conn, "tblEmployee.EmState most common values:", "SELECT TOP 8 EmState, COUNT(*) FROM dbo.tblEmployee GROUP BY EmState ORDER BY 2 DESC")
    top(conn, "Employee state through EmStateCityID (lookup):",
        "SELECT TOP 8 s.PullDownState, COUNT(*) FROM dbo.tblEmployee e JOIN dbo.tblPullDownStateCities c ON c.PullDownStateCityID = e.EmStateCityID "
        "JOIN dbo.tblPullDownStates s ON s.PullDownStateID = c.StateID GROUP BY s.PullDownState ORDER BY 2 DESC")
    top(conn, "Mobile phone shapes (digits shown as 9):",
        "SELECT TOP 6 TRANSLATE(EmMobilePhone, '0123456789', '9999999999'), COUNT(*) FROM dbo.tblEmployee GROUP BY TRANSLATE(EmMobilePhone, '0123456789', '9999999999') ORDER BY 2 DESC")
    top(conn, "Employee status:", "SELECT TOP 8 s.PullDownEmployeeStatus, COUNT(*) FROM dbo.tblEmployee e LEFT JOIN dbo.tblPullDownEmployeeStatus s "
        "ON s.PullDownEmployeeStatusID = e.EmEmployeeStatusID GROUP BY s.PullDownEmployeeStatus ORDER BY 2 DESC")
    top(conn, "Years-in-trade labels:", "SELECT TOP 8 y.PullDownYearsInTrade, COUNT(*) FROM dbo.tblEmployee e LEFT JOIN dbo.tblPullDownYearsInTrade y "
        "ON y.PullDownYearsInTradeID = e.YearsInTradeID GROUP BY y.PullDownYearsInTrade ORDER BY 2 DESC")
    top(conn, "tblEmployeeB.WillTravel values:", "SELECT TOP 6 WillTravel, COUNT(*) FROM dbo.tblEmployeeB GROUP BY WillTravel ORDER BY 2 DESC")
    print()
    filled(conn, "tblEmployeeLicenses", ["EmployeeID", "EmployeeLicenseExpDate", "EmployeeLicenseStateID"])
    print()
    filled(conn, "tblCustomer", ["State", "City", "StateCityID", "Zip", "Phone", "Industry", "CustStatusID", "CustomerTypeID", "SalesmanID"])
    top(conn, "tblCustomer.State most common values:", "SELECT TOP 6 State, COUNT(*) FROM dbo.tblCustomer GROUP BY State ORDER BY 2 DESC")
    top(conn, "Customer state through StateCityID (lookup):",
        "SELECT TOP 6 s.PullDownState, COUNT(*) FROM dbo.tblCustomer e JOIN dbo.tblPullDownStateCities c ON c.PullDownStateCityID = e.StateCityID "
        "JOIN dbo.tblPullDownStates s ON s.PullDownStateID = c.StateID GROUP BY s.PullDownState ORDER BY 2 DESC")
    top(conn, "Customer phone shapes:", "SELECT TOP 5 TRANSLATE(Phone, '0123456789', '9999999999'), COUNT(*) FROM dbo.tblCustomer GROUP BY TRANSLATE(Phone, '0123456789', '9999999999') ORDER BY 2 DESC")
    print()
    filled(conn, "tblProject", ["SiteStateCityID", "SiteZip", "StartDate", "ProjStatusID", "CustomerID", "JobBeingManned"])
    top(conn, "Job status:", "SELECT TOP 8 s.PullDownProjStatus, COUNT(*) FROM dbo.tblProject p LEFT JOIN dbo.tblPullDownProjStatus s ON s.PullDownProjStatusID = p.ProjStatusID GROUP BY s.PullDownProjStatus ORDER BY 2 DESC")
    print()
    row = conn.execute(text("SELECT MIN(WeekEndingDate), MAX(WeekEndingDate), COUNT(DISTINCT WeekEndingDate) FROM dbo.tblTracking")).one()
    print(f"tblTracking: weeks from {row[0]} to {row[1]} ({row[2]} different weeks)")
    top(conn, "Two-letter city names in the city list (lookup values):",
        "SELECT TOP 8 City, COUNT(*) FROM dbo.tblPullDownStateCities WHERE LEN(City) <= 2 GROUP BY City ORDER BY 2 DESC")
    conn.rollback()
