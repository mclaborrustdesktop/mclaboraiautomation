"""One-time database preparation, run once before starting several API workers.

    python -m app.prepare

Creates the demo tables and seeds synthetic data in a single process, so the
uvicorn workers can start with SEED_ON_STARTUP=false without racing each other.
Does nothing against the production SQL Server (no schema changes, no seeding).
"""
from __future__ import annotations

from .config import settings
from .database import Base, SessionLocal, engine
from .seed import seed


def main() -> None:
    if settings.is_sql_server:
        print("DATA_SOURCE=production: nothing to prepare (the app never changes the production schema).")
        return
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        created = seed(db)
        from . import webauth

        webauth.ensure_demo_credentials(db)
    print(f"Demo database ready{': seeded ' + str(created) if created else ' (already seeded)'}")


if __name__ == "__main__":
    main()
