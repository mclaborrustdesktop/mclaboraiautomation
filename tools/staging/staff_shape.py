"""Staff table: counts only (how many active, how the administrator flag is stored, how many permissions)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

with engine.connect() as c:
    for label, sql in (
        ("active flag", "SELECT CAST(OfficeStaffActive AS nvarchar(20)), COUNT(*) FROM dbo.tblOfficeStaff GROUP BY OfficeStaffActive"),
        ("Profile values", "SELECT CAST(Profile AS nvarchar(50)), COUNT(*) FROM dbo.tblOfficeStaff GROUP BY Profile ORDER BY 2 DESC"),
        ("Profile column type", "SELECT DATA_TYPE, 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'tblOfficeStaff' AND COLUMN_NAME = 'Profile'"),
        ("permission rows / staff with permissions / features", "SELECT CAST(COUNT(*) AS nvarchar(20)) + ' / ' + CAST(COUNT(DISTINCT OfficeStaffID) AS nvarchar(20)), (SELECT COUNT(FeatureID) FROM dbo.tblFeature) FROM dbo.tblOfficeStaffPermission"),
        ("feature object names used by the website", "SELECT ObjectName, 1 FROM dbo.tblFeature WHERE ObjectName IN ('employees.view','customers.view','projects.view','tracking.view','ai.search')"),
        ("sample of feature object names (lookup)", "SELECT TOP 40 f.ObjectName + ' | ' + ISNULL(f.FeatureTitle, ''), COUNT(p.OfficeStaffPermissionID) FROM dbo.tblFeature f "
         "LEFT JOIN dbo.tblOfficeStaffPermission p ON p.FeatureID = f.FeatureID GROUP BY f.ObjectName, f.FeatureTitle ORDER BY 2 DESC"),
        ("active staff: how many permissions each has (no names)", "SELECT CAST(n AS nvarchar(10)) + ' permission(s)', COUNT(*) FROM (SELECT s.OfficeStaffID, COUNT(p.OfficeStaffPermissionID) n "
         "FROM dbo.tblOfficeStaff s LEFT JOIN dbo.tblOfficeStaffPermission p ON p.OfficeStaffID = s.OfficeStaffID WHERE s.OfficeStaffActive = 1 GROUP BY s.OfficeStaffID) x GROUP BY n ORDER BY n DESC"),
        ("staff titles (job titles, counts)", "SELECT TOP 12 OfficeStaffTitle, COUNT(*) FROM dbo.tblOfficeStaff WHERE OfficeStaffActive = 1 GROUP BY OfficeStaffTitle ORDER BY 2 DESC"),
    ):
        print(label)
        for v, n in c.execute(text(sql)).fetchall():
            print(f"    {v!r:40} {n}")
    c.rollback()
