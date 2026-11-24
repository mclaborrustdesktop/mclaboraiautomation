from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = "sqlite:///./test_mclabor.db"
os.environ["SEED_ON_STARTUP"] = "false"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["WEB_AUTH_DATABASE_URL"] = "sqlite:///./test_web_auth.db"
os.environ["DATA_SOURCE"] = "demo"
os.environ["ACCESS_MODE"] = "login"  # the existing tests exercise the sign-in; test_access_modes.py covers the others
os.environ["MCLABOR_ENV_FILE"] = "none"  # tests (and the processes they start) never read the real backend/.env
Path("test_web_auth.db").unlink(missing_ok=True)

from app import database  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    db_file = Path("test_mclabor.db")
    if db_file.exists():
        db_file.unlink()
    eng = database.make_engine("sqlite:///./test_mclabor.db")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        seed(s)
        from app import webauth

        webauth.ensure_demo_credentials(s)
    yield eng
    eng.dispose()
    database.engine.dispose()
    try:
        db_file.unlink(missing_ok=True)
    except PermissionError:  # Windows keeps the handle briefly
        pass


@pytest.fixture(scope="session")
def client(engine):
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post("/api/auth/login", json={"username": "ADMIN", "password": settings.demo_password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
