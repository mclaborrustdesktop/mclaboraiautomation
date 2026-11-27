"""Ingest endpoints for the office synchronization agent, and the "last updated" status the website shows.

The agent is not a person: it proves itself with the sync key (and, behind Cloudflare Access, a service token that
Cloudflare has already checked). These endpoints exist only when SYNC_API_KEY is set and the backend's database is
the PostgreSQL mirror (never SQL Server). They accept only approved tables and columns (syncspec).
"""
from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from .. import models as m
from .. import search as search_service
from .. import syncmirror
from ..config import settings
from ..database import engine
from ..security import get_current_user, require_admin

log = logging.getLogger("mclabor.sync")
router = APIRouter(prefix="/api/sync", tags=["sync"])


def require_agent(request: Request) -> None:
    if not settings.sync_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    offered = request.headers.get("X-Sync-Key", "")
    if not offered or not hmac.compare_digest(offered.encode(), settings.sync_api_key.strip().encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sync key missing or wrong")
    if settings.access == "gateway" and (settings.gateway_platform or "").strip().lower() == "cloudflare-access":
        # the agent comes through Cloudflare with a service token; its token has a common_name instead of an e-mail
        from .. import cloudflare_access

        token = request.headers.get("Cf-Access-Jwt-Assertion") or request.cookies.get("CF_Authorization")
        try:
            cloudflare_access.verify(token, require_email=False)
        except cloudflare_access.AccessTokenInvalid:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This address is only reachable through the company gateway.")


class RunIn(BaseModel):
    mode: str = Field("incremental", pattern="^(full|incremental)$")
    source: str | None = Field(None, max_length=120)
    agent: str | None = Field(None, max_length=60)
    allow_mass_delete: bool = False  # lifts the cloud-side deletion guard for this run (the agent's --allow-mass-delete)


class UpsertIn(BaseModel):
    table: str = Field(..., max_length=60)
    rows: list[dict[str, Any]] = Field(..., max_length=syncmirror.BATCH_MAX)


class DeleteIn(BaseModel):
    table: str = Field(..., max_length=60)
    ids: list[int] = Field(..., max_length=syncmirror.BATCH_MAX)


class FinishIn(BaseModel):
    status: str = Field(..., pattern="^(success|failed)$")
    tables: int = 0
    upserted: int = 0
    deleted: int = 0
    source_rows: int | None = None
    error: str | None = Field(None, max_length=500)


def _open(run_id: int) -> None:
    if not syncmirror.run_is_open(run_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run {run_id} is not open (finished, abandoned or unknown). Start a new run.")


@router.post("/bootstrap", dependencies=[Depends(require_agent)])
def bootstrap():
    """Create the mirror tables that do not exist yet (approved columns only, no foreign keys)."""
    return {"tables": syncmirror.bootstrap(engine), "counts": syncmirror.row_counts(engine)}


@router.post("/runs", dependencies=[Depends(require_agent)])
def start_run(body: RunIn):
    mirror_rows = sum(max(0, n) for n in syncmirror.row_counts(engine).values())
    if body.allow_mass_delete:
        log.warning("sync run started WITH the deletion guard lifted (allow_mass_delete) by agent %s", body.agent)
    try:
        run_id = syncmirror.start_run(body.mode, body.source, body.agent, allow_mass_delete=body.allow_mass_delete, mirror_rows=mirror_rows)
    except ValueError as exc:
        log.warning("sync run refused: %s", exc)
        raise HTTPException(status.HTTP_409_CONFLICT, f"Run refused: {exc}")
    return {"run_id": run_id}


@router.post("/runs/{run_id}/upsert", dependencies=[Depends(require_agent)])
def upsert(run_id: int, body: UpsertIn):
    _open(run_id)
    try:
        n = syncmirror.upsert_rows(engine, body.table, body.rows)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return {"upserted": n}


@router.post("/runs/{run_id}/delete", dependencies=[Depends(require_agent)])
def delete(run_id: int, body: DeleteIn):
    _open(run_id)
    try:
        n = syncmirror.delete_rows(engine, body.table, body.ids, run_id=run_id)
    except syncmirror.MassDeleteRefused as exc:
        log.error("sync: %s", exc)
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))  # a 4xx: the agent stops the run instead of retrying
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return {"deleted": n}


@router.post("/runs/{run_id}/finish", dependencies=[Depends(require_agent)])
def finish(run_id: int, body: FinishIn):
    _open(run_id)
    syncmirror.finish_run(run_id, body.status, tables=body.tables, upserted=body.upserted, deleted=body.deleted, source_rows=body.source_rows, error=body.error)
    if body.status == "success":
        search_service.clear_result_cache()
        search_service.clear_vocab_cache()
    log.info("sync run %s finished: %s (%s upserted, %s deleted)", run_id, body.status, body.upserted, body.deleted)
    return {"ok": True}


@router.get("/counts", dependencies=[Depends(require_agent)])
def counts():
    """Row count per mirror table and the source of the last successful run: what the office agent compares its own
    source counts with after a run (reconciliation). Counts only, never a row."""
    last = syncmirror.recent_runs(1)
    return {"environment": settings.environment, "counts": syncmirror.row_counts(engine),
            "last_run": {"status": last[0]["status"], "source": last[0]["source"], "finished_at": last[0]["finished_at"]} if last else None}


@router.get("/status")
def sync_status(_: m.OfficeStaff = Depends(get_current_user)):
    """When the information was last refreshed from the office system, and whether it is outdated (every signed-in user)."""
    return syncmirror.status()


@router.get("/runs")
def runs(limit: int = Query(20, ge=1, le=200), _: m.OfficeStaff = Depends(require_admin)):
    """Recent runs of the office agent (administrators), with the mirror's row counts."""
    return {"items": syncmirror.recent_runs(limit), "counts": syncmirror.row_counts(engine) if settings.sync_enabled else {}}
