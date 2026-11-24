from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _backend_of(url: str | URL) -> str:
    name = url.drivername if isinstance(url, URL) else url.split(":", 1)[0]
    return name.split("+", 1)[0]


def make_engine(url: str | URL | None = None):
    if url is None and settings.is_sql_server:
        from .production import build_sql_server_url

        url = build_sql_server_url()
    url = url or settings.postgres_url or settings.database_url
    backend = _backend_of(url)
    if backend.startswith("mssql") and not settings.is_sql_server:
        raise RuntimeError("A SQL Server URL was given while DATA_SOURCE is 'demo'. Use DATA_SOURCE=staging or production with that environment's settings instead of DATABASE_URL.")
    sqlite = backend.startswith("sqlite")
    postgres = backend.startswith("postgres")
    if postgres:
        # psycopg 3 is the one PostgreSQL driver this app uses; a bare postgresql:// (what hosting services hand out) is accepted
        url = str(url).replace("postgresql://", "postgresql+psycopg://", 1).replace("postgres://", "postgresql+psycopg://", 1) if isinstance(url, str) else url
        connect_args = {"connect_timeout": max(1, int(settings.db_connect_timeout)), "application_name": f"MC Labor Web {settings.environment}"}
    elif sqlite:
        connect_args = {"check_same_thread": False, "timeout": 15}
    else:
        # SQL Server: "timeout" is the login timeout in seconds (a cloud database that is paused or far away must not hang a request)
        connect_args = {"timeout": max(1, int(settings.db_connect_timeout))}
    if sqlite:
        pool = {"pool_size": 20, "max_overflow": 20, "pool_timeout": 15} if ":memory:" not in str(url) else {}
    else:
        pool = {"pool_size": settings.db_pool_size, "max_overflow": settings.db_pool_size, "pool_timeout": 15, "pool_recycle": 1800}
    engine = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True, **pool)
    url = str(url)
    if sqlite:

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            # WAL lets readers work while one user saves; busy_timeout makes
            # concurrent writers wait instead of failing with "database is locked".
            if ":memory:" not in url:
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA busy_timeout=15000")

    elif backend.startswith("mssql"):
        # Writes to the client's SQL Server stay blocked until explicitly approved.
        from .production import install_identity_check, install_write_guard

        install_write_guard(engine)
        install_identity_check(engine)  # staging may only reach the staging server, production only the live one

    elif postgres:
        # one statement may not run longer than the search limit (the same protection the SQL Server connection has)
        @event.listens_for(engine, "connect")
        def _statement_timeout(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            try:
                cur.execute(f"SET statement_timeout = {max(1, int(settings.query_timeout_seconds)) * 1000}")
            finally:
                cur.close()
            dbapi_conn.commit()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
