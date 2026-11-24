"""Why are employee contact details empty on the website? Read-only check on the STAGING copy. COUNTS ONLY.

    powershell -File tools\\staging\\run-readonly.ps1 ..\\tools\\staging\\contact_check.py

Separates the four possible causes:
  1. permissions  - can this login read each approved contact column at all?
  2. mapping      - does the website ask for the right columns (model vs. schema export)?
  3. source data  - are the columns NULL, blank, or filled, for all employees and for employees who worked recently?
  4. backup age   - how old is the newest record in the copy?
No name, phone number, address or e-mail is ever fetched: every query returns counts, lengths or years.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app import models as m  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.production import load_structure_csv  # noqa: E402

assert settings.is_sql_server and not settings.sql_writes_allowed, "a read-only SQL Server environment only (staging copy, or production once approved)"

CONTACT = ["EmStreet", "EmStateCityID", "EmCity", "EmState", "EmZip", "EmHomePhone", "EmMobilePhone", "EmEmail"]
lines: list[str] = []


def say(s: str = "") -> None:
    lines.append(s)
    print(s, flush=True)


def one(conn, sql: str, **p):
    return conn.execute(text(sql), p).one()


def main() -> int:
    say(f"Employee contact columns - {settings.environment_label} on {settings.db_expected_server_name}, read-only, counts only")
    say(dt.datetime.now().strftime("%Y-%m-%d %H:%M"))

    say("\n1. Website mapping (model column names against the schema export)")
    structure = load_structure_csv(Path(settings.schema_csv_dir) / "McLabor_Database_structure.csv")
    emp_cols = structure.get("tblemployee", {})
    for c in CONTACT:
        mapped = c in m.Employee.__table__.columns
        say(f"    {c:16} in model: {'yes' if mapped else 'NO '}   in tblEmployee export: {'yes (' + emp_cols[c.lower()] + ')' if c.lower() in emp_cols else 'NO'}")
    say("    The list page shows EmCity, EmState, EmMobilePhone, EmEmail; the record page shows all of the above.")

    with engine.connect() as conn:
        say("\n2. Permissions of this login on those columns (HAS_PERMS_BY_NAME, 1 = may read)")
        perms = {c: conn.execute(text("SELECT HAS_PERMS_BY_NAME('dbo.tblEmployee', 'OBJECT', 'SELECT', :c, 'COLUMN')"), {"c": c}).scalar() for c in CONTACT}
        say("    " + ", ".join(f"{c}={v}" for c, v in perms.items()))
        others = ["EmAddress", "EmMailStreet", "EmMailCity", "EmMailState", "EmMailZip", "EmSmartPhone", "TextMsgAddress", "EmMobilePhoneTimestamp"]
        oth = {c: conn.execute(text("SELECT HAS_PERMS_BY_NAME('dbo.tblEmployee', 'OBJECT', 'SELECT', :c, 'COLUMN')"), {"c": c}).scalar() for c in others}
        say("    Other address/phone columns that exist in tblEmployee but were NOT approved for the website: " + ", ".join(f"{c}={v}" for c, v in oth.items()))
        say("    (0 = this login cannot read them; they can only be checked by an administrator)")

        say("\n3. Source data in the copy")
        total = conn.execute(text("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee")).scalar()
        say(f"    tblEmployee rows: {total:,}")
        say(f"    {'column':16} {'NULL':>9} {'blank':>9} {'filled':>9}   {'max length':>10}")
        for c in CONTACT:
            if not perms.get(c):
                say(f"    {c:16} (not readable)")
                continue
            if c == "EmStateCityID":
                nulls, filled = one(conn, "SELECT SUM(CASE WHEN EmStateCityID IS NULL THEN 1 ELSE 0 END), SUM(CASE WHEN EmStateCityID IS NOT NULL THEN 1 ELSE 0 END) FROM dbo.tblEmployee")
                linked = conn.execute(text("SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e JOIN dbo.tblPullDownStateCities c ON c.PullDownStateCityID = e.EmStateCityID")).scalar()
                say(f"    {c:16} {nulls:>9,} {'-':>9} {filled:>9,}   (of which {linked:,} point to an existing city row)")
                continue
            nulls, blank, filled, mx = one(conn, f"SELECT SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END), SUM(CASE WHEN {c} IS NOT NULL AND LTRIM(RTRIM({c})) = '' THEN 1 ELSE 0 END), "
                                                 f"SUM(CASE WHEN NULLIF(LTRIM(RTRIM({c})), '') IS NOT NULL THEN 1 ELSE 0 END), MAX(LEN({c})) FROM dbo.tblEmployee")
            say(f"    {c:16} {nulls:>9,} {blank:>9,} {filled:>9,}   {mx if mx is not None else '-':>10}")

        say("\n    The same, only for employees with a tracking row in the last 2 years (people the office actually placed):")
        recent = conn.execute(text("SELECT COUNT(DISTINCT EmployeeID) FROM dbo.tblTracking WHERE WeekEndingDate >= DATEADD(year, -2, '2026-11-13')")).scalar()
        say(f"    {recent:,} such employees")
        for c in ("EmCity", "EmState", "EmZip", "EmMobilePhone", "EmHomePhone", "EmEmail", "EmStateCityID"):
            if not perms.get(c):
                continue
            filled = conn.execute(text(
                f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE NULLIF(LTRIM(RTRIM(CAST(e.{c} AS nvarchar(200)))), '') IS NOT NULL "
                "AND e.EmployeeID IN (SELECT EmployeeID FROM dbo.tblTracking WHERE WeekEndingDate >= DATEADD(year, -2, '2026-11-13'))")).scalar()
            say(f"    {c:16} filled for {filled:,} of them")

        say("\n    Columns next to them that ARE filled (so the row itself is real, not an empty shell):")
        for c in ("EmFirstName", "EmLastName", "EmTradeID", "EmEmployeeStatusID", "EmEntryUserName", "EmEntryTimestamp", "EmLicensedIn", "EmAdminNotes", "EmSalesNotes"):
            filled = conn.execute(text(f"SELECT COUNT(EmployeeID) FROM dbo.tblEmployee WHERE NULLIF(LTRIM(RTRIM(CAST({c} AS nvarchar(200)))), '') IS NOT NULL")).scalar()
            say(f"    {c:20} {filled:>9,} filled ({100 * filled / max(total, 1):.0f}%)")

        say("\n    Comparison: the same kinds of columns elsewhere in the copy")
        pk = {"tblCustomer": "CustomerID", "tblCustomerContacts": "CustomerContactID", "tblProject": "ProjectID", "tblPullDownSalesman": "PullDownSalesmanID"}
        for table, c in (("tblCustomer", "Phone"), ("tblCustomer", "City"), ("tblCustomer", "CustEmail"), ("tblCustomerContacts", "CustomerContactCell"),
                         ("tblCustomerContacts", "CustomerContactEmail"), ("tblProject", "CustomerPhone"), ("tblPullDownSalesman", "PullDownSalesmanCell")):
            n, filled = one(conn, f"SELECT COUNT({pk[table]}), SUM(CASE WHEN NULLIF(LTRIM(RTRIM({c})), '') IS NOT NULL THEN 1 ELSE 0 END) FROM dbo.{table}")
            say(f"    {table + '.' + c:44} {filled:>9,} of {n:>9,} filled ({100 * (filled or 0) / max(n, 1):.0f}%)")

        say("\n4. Age of the data in the copy (years and dates only)")
        for table, c in (("tblEmployee", "EmEntryTimestamp"), ("tblCustomer", "CustEntryTimestamp"), ("tblProject", "ProjectEntryTimestamp"), ("tblTracking", "WeekEndingDate"), ("tblEmployeeNotes", "EmployeeNoteTimestamp")):
            mn, mx = one(conn, f"SELECT MIN({c}), MAX({c}) FROM dbo.{table}")
            say(f"    {table + '.' + c:36} from {str(mn)[:10]} to {str(mx)[:10]}")
        say("    Employees entered per year (count of EmEntryTimestamp):")
        for y, n in conn.execute(text("SELECT YEAR(EmEntryTimestamp), COUNT(EmployeeID) FROM dbo.tblEmployee WHERE EmEntryTimestamp IS NOT NULL GROUP BY YEAR(EmEntryTimestamp) ORDER BY 1")).fetchall():
            say(f"        {y}: {n:,}")
        say("    Employee notes by type (lookup labels, counts) - do staff keep phone/address details in notes instead?")
        for label, n in conn.execute(text("SELECT TOP 8 t.PullDownEmployeeNoteType, COUNT(n.EmployeeNoteID) FROM dbo.tblEmployeeNotes n LEFT JOIN dbo.tblPullDownEmployeeNoteTypes t "
                                          "ON t.PullDownEmployeeNoteTypeID = n.EmployeeNoteTypeID GROUP BY t.PullDownEmployeeNoteType ORDER BY 2 DESC")).fetchall():
            say(f"        {str(label)!r:32} {n:,}")
        phone_like = conn.execute(text("SELECT COUNT(EmployeeNoteID) FROM dbo.tblEmployeeNotes WHERE EmployeeNote LIKE '%[0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]%'")).scalar()
        say(f"    Employee notes containing something shaped like a phone number: {phone_like:,}")
        conn.rollback()

    say("\nNo record content was printed; nothing was written.")
    out = ROOT / "tools" / "prod-check" / "reports" / f"contact-check-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
