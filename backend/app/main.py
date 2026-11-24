from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from sqlalchemy import text

from . import search as search_service
from . import webauth
from .ai import ai_mode
from .config import settings
from .database import Base, SessionLocal, engine
from .observability import RequestContextMiddleware, configure_logging
from .production import ProductionWriteBlocked
from .routers import audit as audit_router
from .routers import auth, customers, dashboard, employees, lookups, projects, search, system, tracking, users
from .routers import sync as sync_router
from .seed import seed

configure_logging()
log = logging.getLogger("mclabor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for warning in settings.security_warnings():
        log.warning("CONFIG: %s", warning)
    if settings.is_real_data:
        problems = settings.environment_problems()
        known = webauth.demo_password_holders()
        if known:
            problems.append(f"{known} web sign-in account(s) still use the demo password. Remove the demo sign-in file or set new passwords.")
        if problems:
            raise RuntimeError(f"Refusing to start in the {settings.environment} environment: " + " ".join(problems))
        # Never create tables or seed on real data (the client's SQL Server, or the cloud database built by app.pgschema).
        if settings.is_postgres:
            log.info("Environment: %s on PostgreSQL (%s shape, %s)", settings.environment_label, "production" if settings.production_shape else "demo",
                     "SEARCH-ONLY mirror fed by the office sync agent" if settings.search_only else "read-write")
            if settings.search_only and not settings.sync_enabled:
                log.warning("CONFIG: the site is search-only but SYNC_API_KEY is not set: the office agent cannot refresh it.")
        else:
            log.info("Environment: %s on SQL Server %s (%s)", settings.environment_label, settings.db_expected_server_name, "read-write" if settings.sql_writes_allowed else "read-only")
        from .routers.users import access_summary

        seats = access_summary()
        log.info("Website access: %s authorized (%s administrators, %s users), seat limit %s", seats["authorized"], seats["administrators"], seats["users"], seats["seat_limit"] or "none")
        if seats["warning"]:
            log.warning("ACCESS: %s", seats["message"])
        yield
        return
    Base.metadata.create_all(engine)
    if settings.seed_on_startup:
        with SessionLocal() as db:
            created = seed(db)
            if created:
                log.info("Seeded demo database: %s", created)
    with SessionLocal() as db:
        made = webauth.ensure_demo_credentials(db)  # demo users only; web passwords are separate from tblOfficeStaff
        if made:
            log.info("Created %s demo web sign-in credential(s)", made)
    log.info("AI search mode: %s", ai_mode())
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Employee, customer and job management for MC Labor with AI-powered search. Demo build on synthetic data.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)
for r in (auth, users, lookups, employees, customers, projects, tracking, search, dashboard, system, audit_router, sync_router):
    app.include_router(r.router)


# These never write to the business database (sign-in and web passwords use the local web sign-in store).
_READ_ONLY_ALLOWED_POSTS = ("/api/auth/login", "/api/auth/change-password", "/password", "/api/search", "/check-duplicates", "/web-access")


def _is_business_write(request: Request) -> bool:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    path = request.url.path
    if path.startswith("/api/sync/"):
        return False  # the office agent's one-way feed into the mirror (its own key; refused unless SYNC_API_KEY is set)
    return not path.endswith(_READ_ONLY_ALLOWED_POSTS)


@app.middleware("http")
async def _production_read_only(request: Request, call_next):
    # While production writes are not approved, or while the site is a search-only mirror, edits get a clear 423.
    is_write = _is_business_write(request)
    if is_write and settings.search_only:
        return JSONResponse(status_code=423, content={"detail": f"This website is search-only. Records are added and changed in {settings.sync_source_label}; the website shows a copy that is refreshed from it."})
    if not settings.writes_allowed and is_write:
        return JSONResponse(status_code=423, content={"detail": f"Read-only mode: changes to the {settings.environment} database are not enabled."})
    response = await call_next(request)
    if is_write and response.status_code < 400:
        # a record changed: forget remembered counts, filter counts and result ids so the next search is exact
        search_service.clear_result_cache()
    return response


@app.exception_handler(ProductionWriteBlocked)
async def _write_blocked(request: Request, exc: ProductionWriteBlocked):
    return JSONResponse(status_code=423, content={"detail": str(exc)})


@app.exception_handler(OperationalError)
async def _database_busy(request: Request, exc: OperationalError):
    text = str(exc.orig).lower()
    if "hyt00" in text or "timeout" in text or "timed out" in text:
        log.warning("Query timeout on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=504, content={"detail": "That search took too long and was stopped. Add a filter (trade, state, city or ZIP) or a more specific word and try again."})
    log.error("Database error on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(status_code=503, content={"detail": "The database is not available right now. Please try again in a moment."})


@app.exception_handler(PoolTimeout)
async def _pool_busy(request: Request, exc: PoolTimeout):
    return JSONResponse(status_code=503, content={"detail": "The system is busy. Please try again in a few seconds."}, headers={"Retry-After": "3"})


@app.exception_handler(IntegrityError)
async def _integrity_error(request: Request, exc: IntegrityError):
    # Safety net: constraint violations that slipped past validation become a 409, never a 500.
    log.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(status_code=409, content={"detail": "The change conflicts with existing data (a required field is missing or a linked record does not exist)."})


@app.get("/api/health", tags=["system"])
def health():
    """Liveness: the process is up. Cheap; touches nothing."""
    return {"status": "ok", "app": settings.app_name, "ai_mode": ai_mode(), "demo": settings.is_demo, "environment": settings.environment, "access_mode": settings.access,
            "database": settings.db_backend, "writes": settings.writes_allowed, "site_mode": "search-only" if settings.search_only else "full"}


@app.get("/api/ready", tags=["system"])
def ready():
    """Readiness: may traffic be sent here? 503 until the database and the sign-in store answer. No secrets, no records."""
    checks: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.rollback()
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready", the reason goes to the log only
        log.warning("Readiness: database not reachable (%s)", type(exc).__name__)
        checks["database"] = "unavailable"
    try:
        webauth.account_count()
        checks["sign_in_store"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.warning("Readiness: sign-in store not reachable (%s)", type(exc).__name__)
        checks["sign_in_store"] = "unavailable"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ready" if ok else "not ready", "environment": settings.environment, "checks": checks})
