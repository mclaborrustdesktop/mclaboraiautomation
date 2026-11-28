"""The cloud side of the one-way synchronization: the mirror tables, upserts/deletes by primary key, and the record of
runs (last successful sync) that the website shows to its users.

Used by the ingest API (routers/sync.py, called by the office agent over HTTPS) and, for tests and emergencies, by the
agent's direct-database target. Every row is validated against syncspec before it is written: an unapproved column is
refused, never silently dropped, so a configuration mistake on the office side cannot leak a column into the cloud.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, Text, delete, select


class MassDeleteRefused(ValueError):
    """More deletions in one run than the guard allows: the mirror is kept as it is."""
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from . import syncspec
from .config import settings
from .webauth import AuthBase, _session

log = logging.getLogger("mclabor.sync")
BATCH_MAX = 5000


class SyncRun(AuthBase):
    """One run of the office agent, as seen from the cloud (the website's own store)."""

    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    environment: Mapped[str] = mapped_column(String(12), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), default="running")  # running | success | failed | abandoned
    mode: Mapped[str | None] = mapped_column(String(12))                  # full | incremental
    source: Mapped[str | None] = mapped_column(String(120))               # e.g. "DEV-PC\\SQLEXPRESS/McLabor" - a name, never a credential
    agent: Mapped[str | None] = mapped_column(String(60))
    tables: Mapped[int] = mapped_column(Integer, default=0)
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_deleted: Mapped[int] = mapped_column(Integer, default=0)
    source_rows: Mapped[int | None] = mapped_column(Integer)              # rows in the source after the run (for the status page)
    error: Mapped[str | None] = mapped_column(String(500))
    # deletion guard on the cloud side: one run may not delete more than MAX_RUN_DELETE_FRACTION of the mirror (or
    # MAX_RUN_DELETE_ROWS rows, whichever is larger) unless the agent was started with --allow-mass-delete
    allow_mass_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    mirror_rows_at_start: Mapped[int | None] = mapped_column(Integer)


MAX_RUN_DELETE_FRACTION = 0.10
MAX_RUN_DELETE_ROWS = 500


# ---------------------------------------------------------------- values
def _coerce(col, value: Any) -> Any:
    """JSON-transported values back into what the column type expects (both PostgreSQL and SQLite)."""
    if value is None:
        return None
    t = col.type
    try:
        if isinstance(t, Boolean):
            return bool(value) if not isinstance(value, str) else value.strip().lower() in ("1", "true", "yes", "t")
        if isinstance(t, Integer):
            return int(value)
        if isinstance(t, Numeric):
            return Decimal(str(value))
        if isinstance(t, Float):
            return float(value)
        if isinstance(t, DateTime):
            if isinstance(value, datetime):
                return value
            if isinstance(value, date):
                return datetime(value.year, value.month, value.day)
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        if isinstance(t, Date):
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            return datetime.fromisoformat(str(value)).date()
        if isinstance(t, (String, Text)):
            return str(value)
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise ValueError(f"{col.table.name}.{col.name}: value {value!r} is not a {type(t).__name__}") from exc
    return value


def prepare_rows(table: str, rows: list[dict[str, Any]]) -> tuple[Any, str, list[dict[str, Any]]]:
    """Validate a batch against the approved columns and coerce the values. Returns (table object, pk name, rows)."""
    md = syncspec.mirror_metadata()
    if table not in md.tables:
        raise ValueError(f"{table} is not an approved table for the synchronization")
    t = md.tables[table]
    pk = syncspec.primary_key(table)
    if len(rows) > BATCH_MAX:
        raise ValueError(f"a batch may hold at most {BATCH_MAX} rows")
    seen_cols: set[str] = set()
    for r in rows:
        seen_cols.update(r.keys())
    syncspec.check_columns(table, seen_cols)
    out: dict[Any, dict[str, Any]] = {}
    for r in rows:
        if r.get(pk) is None:
            raise ValueError(f"{table}: a row without {pk} cannot be synchronized")
        clean = {c.name: _coerce(c, r.get(c.name)) for c in t.columns if c.name in r or c.name == pk}
        out[clean[pk]] = clean  # the same key twice in one batch: the last one wins (no duplicate rows)
    return t, pk, list(out.values())


# ---------------------------------------------------------------- writes
def bootstrap(engine) -> list[str]:
    """Create the mirror tables that do not exist yet (never drops, never alters). Returns the table names."""
    md = syncspec.mirror_metadata()
    md.create_all(engine, checkfirst=True)
    return [t.name for t in md.sorted_tables]


def upsert_rows(engine, table: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    t, pk, clean = prepare_rows(table, rows)
    cols = [c.name for c in t.columns]
    # every row carries every column so the statement has one shape (missing = NULL, which is what the source has)
    full = [{c: r.get(c) for c in cols} for r in clean]
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(engine.dialect.name)
    if insert is None:  # pragma: no cover - the mirror is PostgreSQL (SQLite for tests)
        raise RuntimeError(f"unsupported mirror database: {engine.dialect.name}")
    per_stmt = max(1, 30000 // max(1, len(cols)))  # bound-parameter limits (SQLite 32,766; PostgreSQL 65,535)
    with engine.begin() as conn:
        for i in range(0, len(full), per_stmt):
            stmt = insert(t).values(full[i:i + per_stmt])
            stmt = stmt.on_conflict_do_update(index_elements=[pk], set_={c: stmt.excluded[c] for c in cols if c != pk})
            conn.execute(stmt)
    return len(full)


def delete_rows(engine, table: str, ids: list[Any], run_id: int | None = None) -> int:
    if not ids:
        return 0
    md = syncspec.mirror_metadata()
    if table not in md.tables:
        raise ValueError(f"{table} is not an approved table for the synchronization")
    if run_id is not None:
        _check_delete_budget(run_id, len(ids))
    t = md.tables[table]
    pk = t.c[syncspec.primary_key(table)]
    n = 0
    with engine.begin() as conn:
        for i in range(0, len(ids), 1000):
            n += conn.execute(delete(t).where(pk.in_([int(x) for x in ids[i:i + 1000]]))).rowcount
    if run_id is not None:
        with _session() as s:
            run = s.get(SyncRun, run_id)
            if run is not None:
                run.rows_deleted = (run.rows_deleted or 0) + n
                s.commit()
    return n


def _check_delete_budget(run_id: int, requested: int) -> None:
    with _session() as s:
        run = s.get(SyncRun, run_id)
        if run is None:
            raise KeyError(run_id)
        if run.allow_mass_delete:
            return
        budget = max(MAX_RUN_DELETE_ROWS, int((run.mirror_rows_at_start or 0) * MAX_RUN_DELETE_FRACTION))
        if (run.rows_deleted or 0) + requested > budget:
            raise MassDeleteRefused(f"run {run_id} would delete {(run.rows_deleted or 0) + requested} rows, more than the guard allows ({budget} = "
                                    f"{MAX_RUN_DELETE_FRACTION:.0%} of the mirror's {run.mirror_rows_at_start or 0} rows, minimum {MAX_RUN_DELETE_ROWS}). "
                                    "The mirror was left as it is. Check the office database; rerun the agent with --allow-mass-delete if this is right.")


def row_counts(engine) -> dict[str, int]:
    from sqlalchemy import func

    md = syncspec.mirror_metadata()
    out = {}
    with engine.connect() as conn:
        for t in md.sorted_tables:
            try:
                out[t.name] = int(conn.execute(select(func.count()).select_from(t)).scalar_one())
            except Exception:  # noqa: BLE001 - table not created yet
                out[t.name] = -1
    return out


# ---------------------------------------------------------------- runs (the website's own store)
def start_run(mode: str, source: str | None, agent: str | None, allow_mass_delete: bool = False, mirror_rows: int | None = None) -> int:
    """Opens a run. Refuses (ValueError) a source other than SYNC_EXPECTED_SOURCE, or other than the source of this mirror's
    earlier successful runs, so that records from two systems (synthetic and real, or two servers) are never mixed."""
    announced = (source or "").strip()
    expected = (settings.sync_expected_source or "").strip()
    if expected and announced.lower() != expected.lower():
        raise ValueError(f"this website only accepts data from '{expected}' (SYNC_EXPECTED_SOURCE); the agent announced '{announced or '?'}'")
    with _session() as s:
        prior = s.execute(select(SyncRun.source).where(SyncRun.environment == settings.environment, SyncRun.status == "success", SyncRun.source.is_not(None))
                          .order_by(SyncRun.id.desc()).limit(1)).scalar()
        if prior and announced and prior.strip().lower() != announced.lower() and announced.lower() != expected.lower():
            # The one allowed change: the owner re-points SYNC_EXPECTED_SOURCE (e.g. from the office PC's snapshot to the live
            # server, the same database continued). The agent keeps its state file, so changed rows are updated and rows gone
            # since the snapshot are deleted; two unrelated systems are still never mixed.
            raise ValueError(f"this mirror holds data from '{prior}'; a run from '{announced}' is refused so that two systems are never mixed")
        # a run that never finished (agent crashed, link dropped) is marked abandoned when the next one starts
        for old in s.execute(select(SyncRun).where(SyncRun.environment == settings.environment, SyncRun.status == "running")).scalars():
            old.status, old.finished_at, old.error = "abandoned", datetime.utcnow(), "a later run started before this one finished"
        run = SyncRun(environment=settings.environment, mode=mode, source=(source or "")[:120] or None, agent=(agent or "")[:60] or None,
                      allow_mass_delete=bool(allow_mass_delete), mirror_rows_at_start=mirror_rows)
        s.add(run)
        s.commit()
        return run.id


def finish_run(run_id: int, status: str, tables: int = 0, upserted: int = 0, deleted: int = 0, source_rows: int | None = None, error: str | None = None) -> None:
    with _session() as s:
        run = s.get(SyncRun, run_id)
        if run is None:
            raise KeyError(run_id)
        run.status = "success" if status == "success" else "failed"
        run.finished_at = datetime.utcnow()
        run.tables, run.rows_upserted, run.rows_deleted, run.source_rows = tables, upserted, max(deleted, run.rows_deleted or 0), source_rows
        run.error = (error or "")[:500] or None
        s.commit()


def run_is_open(run_id: int) -> bool:
    with _session() as s:
        run = s.get(SyncRun, run_id)
        return run is not None and run.status == "running" and run.environment == settings.environment


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    with _session() as s:
        rows = s.execute(select(SyncRun).where(SyncRun.environment == settings.environment).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(limit)).scalars().all()
        return [{"id": r.id, "started_at": r.started_at, "finished_at": r.finished_at, "status": r.status, "mode": r.mode, "source": r.source, "agent": r.agent,
                 "tables": r.tables, "rows_upserted": r.rows_upserted, "rows_deleted": r.rows_deleted, "source_rows": r.source_rows, "error": r.error,
                 "allow_mass_delete": r.allow_mass_delete, "mirror_rows_at_start": r.mirror_rows_at_start} for r in rows]


def status() -> dict[str, Any]:
    """What the website shows: when the information was last refreshed and whether that is too long ago."""
    if not settings.search_only and not settings.sync_enabled:
        return {"applies": False}
    with _session() as s:
        last_ok = s.execute(select(SyncRun).where(SyncRun.environment == settings.environment, SyncRun.status == "success")
                            .order_by(SyncRun.finished_at.desc()).limit(1)).scalars().first()
        last = s.execute(select(SyncRun).where(SyncRun.environment == settings.environment).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(1)).scalars().first()
        last_ok_at = last_ok.finished_at if last_ok else None
        last_any = {"status": last.status, "started_at": last.started_at, "error": last.error} if last else None
    now = datetime.utcnow()
    age_h = (now - last_ok_at).total_seconds() / 3600 if last_ok_at else None
    stale_after = max(1, int(settings.sync_stale_hours))
    level = "never" if last_ok_at is None else ("stale" if age_h > 2 * stale_after else "aging" if age_h > stale_after else "fresh")
    return {
        "applies": True, "search_only": settings.search_only, "source": settings.sync_source_label,
        "last_success_at": last_ok_at, "age_hours": round(age_h, 1) if age_h is not None else None, "stale_after_hours": stale_after,
        "level": level, "stale": level in ("stale", "never"),
        "next_expected_at": (last_ok_at + timedelta(hours=stale_after)) if last_ok_at else None,
        "last_run": last_any,
        "message": (f"Information from {settings.sync_source_label} has not been loaded yet." if level == "never" else
                    f"Information from {settings.sync_source_label} is {age_h:.0f} hours old (last update {last_ok_at:%Y-%m-%d %H:%M} UTC). It may be outdated." if level in ("stale", "aging") else
                    None),
    }
