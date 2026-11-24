"""Prints ONE number: the OfficeStaffID of the active staff member with the most Access permissions.
Used only as the temporary test identity for the automated pilot. No name or initials are printed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

with engine.connect() as c:
    print(c.execute(text(
        "SELECT TOP 1 s.OfficeStaffID FROM dbo.tblOfficeStaff s JOIN dbo.tblOfficeStaffPermission p ON p.OfficeStaffID = s.OfficeStaffID "
        "WHERE s.OfficeStaffActive = 1 GROUP BY s.OfficeStaffID ORDER BY COUNT(p.OfficeStaffPermissionID) DESC")).scalar())
    c.rollback()
