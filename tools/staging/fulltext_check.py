"""Is full-text search installed on the STAGING instance? One read-only metadata query (SERVERPROPERTY)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

with engine.connect() as c:
    row = c.execute(text(
        "SELECT CAST(SERVERPROPERTY('IsFullTextInstalled') AS int) AS fulltext_installed, CAST(SERVERPROPERTY('Edition') AS nvarchar(100)) AS edition, "
        "CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(30)) AS version, CAST(DATABASEPROPERTYEX(DB_NAME(), 'IsFulltextEnabled') AS int) AS db_fulltext_enabled, "
        "CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) AS server")).mappings().one()
    print(dict(row))
    c.rollback()
