"""The office-side synchronization agent: office SQL Server -> (one way) -> the cloud mirror.

    .venv\\Scripts\\python.exe -m app.syncagent run --api https://app.<domain> --key-env SYNC_API_KEY [--full] [--dry-run]
    .venv\\Scripts\\python.exe -m app.syncagent run --source-url sqlite:///synthetic.db --target-url sqlite:///mirror.db
    .venv\\Scripts\\python.exe -m app.syncagent status [--state <file>]

What it does, every run:
  1. opens the source READ-ONLY (the restricted login, the SELECT-only statement guard and the server identity check
     of the staging/production settings; a test may pass --source-url for a synthetic file instead);
  2. for each approved table (syncspec), reads exactly the approved columns, in primary-key order, in pages;
  3. hashes every row and compares it with the agent's own state file from the previous run: new or changed rows
     are sent, rows that disappeared from the source are deleted on the mirror, unchanged rows are not touched.
     No "last modified" column is needed and none is trusted (the office tables have no reliable one);
  4. sends batches to the cloud (HTTPS, the sync key, retries with back-off); the state file is updated only for
     batches the cloud has acknowledged, so an interrupted run is simply resumed by the next run;
  5. reports the run (started, finished, counts, error) to the cloud, which the website shows as "last updated".

Nothing ever flows back: the agent only SELECTs from the office database. Row contents are never logged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socket
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Column, MetaData, Table, select, text
from sqlalchemy import column as sa_column

from . import syncspec
from .config import settings

log = logging.getLogger("mclabor.syncagent")
AGENT_VERSION = "mclabor-sync-agent/1.0"
PAGE = 5000          # rows read from the source per page
BATCH = 1000         # rows sent to the cloud per request
RETRIES = (2, 4, 8, 16, 32)  # seconds between retries of one batch
# Deletion guard: rows that vanished from the source are deleted on the mirror ONLY when the table was read completely
# and the source did not shrink implausibly (a half-read table, a wrong database, an empty result must never wipe the
# mirror). A shrink above MAX_SHRINK of the remembered rows AND above MAX_SHRINK_ROWS rows is treated as suspicious:
# the run keeps the upserts, skips those deletions, and reports a warning; --allow-mass-delete overrides after a human check.
MAX_SHRINK = 0.10
MAX_SHRINK_ROWS = 100


# ---------------------------------------------------------------- values and hashes
def _canon(v: Any) -> Any:
    """A JSON-safe, canonical form of a value (the same on SQL Server, SQLite and PostgreSQL)."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, Decimal):
        return format(v.normalize(), "f") if v == v.to_integral() else format(v.normalize(), "f")
    if isinstance(v, float):
        return v
    if isinstance(v, datetime):
        return v.replace(tzinfo=None).isoformat(timespec="seconds") if v.microsecond == 0 else v.replace(tzinfo=None).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return str(v)


def row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------- state (the agent's own file)
class State:
    """SQLite file with one line per synchronized row (table, key, hash) and the history of runs on this PC."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS rows (table_name TEXT NOT NULL, pk INTEGER NOT NULL, hash TEXT NOT NULL, PRIMARY KEY (table_name, pk))")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, status TEXT, mode TEXT, "
                        "upserted INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0, error TEXT, cloud_run_id INTEGER)")

    def hashes(self, table: str) -> dict[int, str]:
        return {int(pk): h for pk, h in self.db.execute("SELECT pk, hash FROM rows WHERE table_name = ?", (table,))}

    def remember(self, table: str, pairs: list[tuple[int, str]]) -> None:
        self.db.executemany("INSERT INTO rows (table_name, pk, hash) VALUES (?, ?, ?) ON CONFLICT(table_name, pk) DO UPDATE SET hash = excluded.hash",
                            [(table, pk, h) for pk, h in pairs])

    def forget(self, table: str, pks: list[int]) -> None:
        self.db.executemany("DELETE FROM rows WHERE table_name = ? AND pk = ?", [(table, pk) for pk in pks])

    def clear(self) -> None:
        self.db.execute("DELETE FROM rows")

    def start_run(self, mode: str, cloud_run_id: int | None) -> int:
        cur = self.db.execute("INSERT INTO runs (started_at, status, mode, cloud_run_id) VALUES (?, 'running', ?, ?)", (datetime.utcnow().isoformat(timespec="seconds"), mode, cloud_run_id))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, upserted: int, deleted: int, error: str | None) -> None:
        self.db.execute("UPDATE runs SET finished_at = ?, status = ?, upserted = ?, deleted = ?, error = ? WHERE id = ?",
                        (datetime.utcnow().isoformat(timespec="seconds"), status, upserted, deleted, (error or "")[:500] or None, run_id))

    def running(self) -> dict | None:
        row = self.db.execute("SELECT id, started_at FROM runs WHERE status = 'running' ORDER BY id DESC LIMIT 1").fetchone()
        return {"id": row[0], "started_at": row[1]} if row else None

    def last_runs(self, n: int = 10) -> list[tuple]:
        return self.db.execute("SELECT id, started_at, finished_at, status, mode, upserted, deleted, error FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def row_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM rows").fetchone()[0])

    def close(self) -> None:
        self.db.close()


def default_state_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MCLabor" / "sync"
    return base / f"state-{settings.environment}.db"


# ---------------------------------------------------------------- source (read-only)
class Source:
    def __init__(self, url: str | None = None, limit: int | None = None):
        from .database import make_engine

        if url:
            self.engine = make_engine(url)
            self.label = url.split("://", 1)[0] + " (given)"
        else:
            if not settings.is_sql_server:
                raise RuntimeError("The agent reads the office SQL Server: run it with DATA_SOURCE=staging or production settings (or pass --source-url for a test file).")
            if settings.sql_writes_allowed:
                raise RuntimeError("The sync agent must run with writes DISABLED for its environment.")
            self.engine = make_engine()  # read-only guard + server identity check (production.py)
            self.label = f"{settings.db_expected_server_name}/{settings.db_name}"
        self.limit = limit

    def read(self, table: str, columns: list[str]) -> Iterator[list[dict[str, Any]]]:
        """Pages of rows with exactly the approved columns, ordered by the key (keyset paging: no OFFSET on big tables)."""
        pk = syncspec.primary_key(table)
        t = Table(table, MetaData(), *[Column(c) for c in columns])
        last = None
        sent = 0
        with self.engine.connect() as conn:
            while True:
                stmt = select(*[t.c[c] for c in columns]).order_by(t.c[pk]).limit(PAGE)
                if last is not None:
                    stmt = stmt.where(t.c[pk] > last)
                rows = [dict(r._mapping) for r in conn.execute(stmt).all()]
                conn.rollback()
                if not rows:
                    return
                if self.limit is not None:
                    rows = rows[: max(0, self.limit - sent)]
                    sent += len(rows)
                if rows:
                    yield rows
                if len(rows) < PAGE or (self.limit is not None and sent >= self.limit):
                    return
                last = rows[-1][pk]

    def close(self) -> None:
        self.engine.dispose()


# ---------------------------------------------------------------- targets
class DirectTarget:
    """Writes straight into a mirror database (tests; or an emergency with a public database URL)."""

    def __init__(self, url: str):
        from .database import make_engine
        from . import syncmirror

        if url.startswith("mssql") or settings.is_office_host(url):
            raise RuntimeError("The mirror is never an office server.")
        self.engine = make_engine(url)
        self.mirror = syncmirror

    def bootstrap(self) -> list[str]:
        return self.mirror.bootstrap(self.engine)

    def begin_run(self, mode: str, source: str, allow_mass_delete: bool = False) -> int:
        return self.mirror.start_run(mode, source, AGENT_VERSION, allow_mass_delete=allow_mass_delete, mirror_rows=sum(max(0, n) for n in self.mirror.row_counts(self.engine).values()))

    def upsert(self, run_id: int, table: str, rows: list[dict[str, Any]]) -> int:
        return self.mirror.upsert_rows(self.engine, table, rows)

    def delete(self, run_id: int, table: str, ids: list[int]) -> int:
        return self.mirror.delete_rows(self.engine, table, ids, run_id=run_id)

    def finish_run(self, run_id: int, status: str, **stats) -> None:
        self.mirror.finish_run(run_id, status, **stats)

    def close(self) -> None:
        self.engine.dispose()


class ApiTarget:
    """Sends batches to the website's ingest API (routers/sync.py) with the sync key and, behind Cloudflare Access,
    a service token. ``client`` may be any httpx-like client (the tests pass the app's test client)."""

    def __init__(self, base_url: str, key: str, cf_client_id: str | None = None, cf_client_secret: str | None = None, client=None, timeout: float = 120.0):
        import httpx

        self.base = base_url.rstrip("/")
        headers = {"X-Sync-Key": key, "User-Agent": AGENT_VERSION}
        if cf_client_id and cf_client_secret:
            headers["CF-Access-Client-Id"] = cf_client_id
            headers["CF-Access-Client-Secret"] = cf_client_secret
        self.headers = headers
        self.client = client or httpx.Client(timeout=timeout)

    def _post(self, path: str, body: dict | None = None) -> dict:
        last: Exception | None = None
        for attempt, wait in enumerate((0,) + RETRIES):
            if wait:
                time.sleep(wait)
            try:
                r = self.client.post(f"{self.base}{path}", json=body or {}, headers=self.headers)
            except Exception as exc:  # noqa: BLE001 - network: retry
                last = exc
                log.warning("sync: %s failed (%s), retry %d/%d", path, type(exc).__name__, attempt + 1, len(RETRIES))
                continue
            if r.status_code < 300:
                return r.json() if r.content else {}
            if r.status_code in (408, 425, 429, 500, 502, 503, 504):
                last = RuntimeError(f"{path}: HTTP {r.status_code}")
                log.warning("sync: %s -> HTTP %s, retry %d/%d", path, r.status_code, attempt + 1, len(RETRIES))
                continue
            raise RuntimeError(f"{path}: HTTP {r.status_code}: {r.text[:300]}")  # a 4xx is a configuration problem: do not retry
        raise RuntimeError(f"{path}: gave up after {len(RETRIES)} retries ({last})")

    def bootstrap(self) -> list[str]:
        return self._post("/api/sync/bootstrap").get("tables", [])

    def begin_run(self, mode: str, source: str, allow_mass_delete: bool = False) -> int:
        return int(self._post("/api/sync/runs", {"mode": mode, "source": source, "agent": AGENT_VERSION, "allow_mass_delete": allow_mass_delete})["run_id"])

    def _get(self, path: str) -> dict:
        r = self.client.get(f"{self.base}{path}", headers=self.headers)
        if r.status_code != 200:
            raise RuntimeError(f"GET {path} -> HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def upsert(self, run_id: int, table: str, rows: list[dict[str, Any]]) -> int:
        return int(self._post(f"/api/sync/runs/{run_id}/upsert", {"table": table, "rows": rows}).get("upserted", len(rows)))

    def delete(self, run_id: int, table: str, ids: list[int]) -> int:
        return int(self._post(f"/api/sync/runs/{run_id}/delete", {"table": table, "ids": ids}).get("deleted", len(ids)))

    def finish_run(self, run_id: int, status: str, **stats) -> None:
        self._post(f"/api/sync/runs/{run_id}/finish", {"status": status, **stats})

    def close(self) -> None:
        self.client.close()


# ---------------------------------------------------------------- the run
class SyncReport(dict):
    pass


def run(source: Source, target, state: State, full: bool = False, dry_run: bool = False, tables: list[str] | None = None, max_batches: int | None = None,
        allow_mass_delete: bool = False) -> SyncReport:
    """One synchronization. Returns counts; raises after recording a failed run when something goes wrong."""
    approved = syncspec.approved_tables()
    order = [t for t in syncspec.table_order() if not tables or t in tables]
    if state.running():
        raise RuntimeError(f"Another run appears to be in progress since {state.running()['started_at']} (state {state.path}). Use --force if it crashed.")
    if full:
        state.clear()
    mode = "full" if full or state.row_count() == 0 else "incremental"
    cloud_run = None if dry_run else target.begin_run(mode, source.label, allow_mass_delete=allow_mass_delete)
    local_run = state.start_run(mode, cloud_run)
    report = SyncReport(mode=mode, tables=0, upserted=0, deleted=0, unchanged=0, source_rows=0, batches=0, per_table={}, warnings=[], skipped_deletions=0)
    t0 = time.perf_counter()
    batches_sent = 0
    partial_read = source.limit is not None or bool(tables)  # a limited or partial run never deletes anything
    try:
        deletions: list[tuple[str, list[int]]] = []
        for table in order:
            cols = approved[table]
            pk = syncspec.primary_key(table)
            known = state.hashes(table)
            seen: set[int] = set()
            pending: list[dict[str, Any]] = []
            pending_hashes: list[tuple[int, str]] = []
            up = unchanged = n_source = 0

            def flush():
                nonlocal up, batches_sent
                if not pending:
                    return
                if max_batches is not None and batches_sent >= max_batches:
                    raise InterruptedError(f"stopped on purpose after {batches_sent} batches (test)")
                if not dry_run:
                    target.upsert(cloud_run, table, pending)
                    state.remember(table, pending_hashes)  # only after the cloud acknowledged the batch
                batches_sent += 1
                up += len(pending)
                pending.clear()
                pending_hashes.clear()

            for page in source.read(table, cols):
                for raw in page:
                    row = {c: _canon(raw.get(c)) for c in cols}
                    key = int(row[pk])
                    if key in seen:
                        continue  # a duplicate key in the source (tblEmployeeB has had them): the first row wins
                    seen.add(key)
                    n_source += 1
                    h = row_hash(row)
                    if known.get(key) == h:
                        unchanged += 1
                        continue
                    pending.append(row)
                    pending_hashes.append((key, h))
                    if len(pending) >= BATCH:
                        flush()
            flush()
            gone = sorted(set(known) - seen)
            if gone:
                shrink = len(gone) / max(1, len(known))
                if partial_read:
                    report["warnings"].append(f"{table}: {len(gone)} row(s) missing from a limited/partial read: deletions skipped")
                    report["skipped_deletions"] += len(gone)
                    gone = []
                elif n_source == 0 or (shrink > MAX_SHRINK and len(gone) > MAX_SHRINK_ROWS and not allow_mass_delete):
                    report["warnings"].append(f"{table}: the source has {n_source} rows where {len(known)} were remembered ({len(gone)} gone, {shrink:.0%}): "
                                              "deletions skipped as implausible. Check the source; rerun with --allow-mass-delete if it is right.")
                    report["skipped_deletions"] += len(gone)
                    gone = []
                else:
                    deletions.append((table, gone))
            report["per_table"][table] = {"source_rows": n_source, "upserted": up, "unchanged": unchanged, "to_delete": len(gone)}
            report["tables"] += 1
            report["upserted"] += up
            report["unchanged"] += unchanged
            report["source_rows"] += n_source
            log.info("sync: %-36s source %7d  sent %6d  unchanged %7d  gone %5d", table, n_source, up, unchanged, len(gone))
        # deletions last, children first, so a parent is never removed before its children
        for table, gone in reversed(deletions):
            for i in range(0, len(gone), BATCH):
                chunk = gone[i:i + BATCH]
                if not dry_run:
                    target.delete(cloud_run, table, chunk)
                    state.forget(table, chunk)
                report["deleted"] += len(chunk)
        report["batches"] = batches_sent
        report["seconds"] = round(time.perf_counter() - t0, 1)
        warning = "; ".join(report["warnings"])[:500] or None
        for w in report["warnings"]:
            log.warning("sync: %s", w)
        if not dry_run:
            target.finish_run(cloud_run, "success", tables=report["tables"], upserted=report["upserted"], deleted=report["deleted"], source_rows=report["source_rows"], error=warning)
        state.finish_run(local_run, "success" if not dry_run else "dry-run", report["upserted"], report["deleted"], warning)
        log.info("sync: %s run done in %ss: %d tables, %d sent, %d deleted, %d unchanged%s", mode, report["seconds"], report["tables"], report["upserted"], report["deleted"], report["unchanged"],
                 f", {report['skipped_deletions']} deletions SKIPPED (see warnings)" if report["skipped_deletions"] else "")
        return report
    except BaseException as exc:
        msg = f"{type(exc).__name__}: {exc}"[:500]
        state.finish_run(local_run, "failed", report["upserted"], report["deleted"], msg)
        if cloud_run is not None:
            try:
                target.finish_run(cloud_run, "failed", tables=report["tables"], upserted=report["upserted"], deleted=report["deleted"], error=msg)
            except Exception:  # noqa: BLE001 - the cloud may be the thing that failed
                pass
        log.error("sync: run FAILED after %d batches: %s", batches_sent, msg)
        raise


# ---------------------------------------------------------------- CLI
def _key_from(args) -> str:
    if args.key_file:
        return Path(args.key_file).read_text(encoding="utf-8").strip()
    key = os.environ.get(args.key_env or "SYNC_API_KEY", "")
    if not key:
        raise SystemExit(f"The sync key is not set ({args.key_env or 'SYNC_API_KEY'}).")
    return key


def compare_counts(report: dict, remote: dict, expect_source: str | None = None) -> list[str]:
    """Reconciliation after a run: every approved table's source count (what the agent read) must equal the website's
    mirror count, the website must hold no table the agent did not send, and its last run must come from the expected
    source. Returns the list of problems (empty = all match)."""
    problems: list[str] = []
    per_table = report.get("per_table") or {}
    counts = remote.get("counts") or {}
    for table, info in sorted(per_table.items()):
        src = int(info.get("source_rows") or 0)
        got = counts.get(table)
        if got is None:
            problems.append(f"{table}: the website has no such table")
        elif int(got) != src:
            problems.append(f"{table}: source {src:,} rows, website {int(got):,}")
    for table, n in sorted(counts.items()):
        if table not in per_table and int(n or 0) > 0:
            problems.append(f"{table}: {int(n):,} rows on the website but the agent did not read that table")
    last = remote.get("last_run") or {}
    if expect_source and (last.get("source") or "").strip().lower() != expect_source.strip().lower():
        problems.append(f"the website's last run came from '{last.get('source')}', expected '{expect_source}'")
    if last and last.get("status") not in ("success", None):
        problems.append(f"the website's last run ended with status '{last.get('status')}'")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.syncagent", description="One-way synchronization: office SQL Server -> cloud mirror")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="synchronize now")
    r.add_argument("--source-url", help="a test source instead of the environment's SQL Server (sqlite:///...)")
    r.add_argument("--target-url", help="write straight into a mirror database (tests / emergencies)")
    r.add_argument("--api", help="the website's address, e.g. https://app.example.com")
    r.add_argument("--key-env", default="SYNC_API_KEY", help="environment variable holding the sync key")
    r.add_argument("--key-file", help="file holding the sync key (one line)")
    r.add_argument("--cf-client-id", default=os.environ.get("CF_ACCESS_CLIENT_ID"))
    r.add_argument("--cf-client-secret-env", default="CF_ACCESS_CLIENT_SECRET")
    r.add_argument("--state", help="the agent's state file (default %LOCALAPPDATA%\\MCLabor\\sync\\state-<env>.db)")
    r.add_argument("--full", action="store_true", help="forget the state and send everything again")
    r.add_argument("--dry-run", action="store_true", help="read and compare, send nothing")
    r.add_argument("--force", action="store_true", help="ignore a run marked as still running (after a crash)")
    r.add_argument("--allow-mass-delete", action="store_true", help="delete on the mirror even when a table shrank by more than 10%% (after checking the source)")
    r.add_argument("--tables", help="comma-separated subset of the approved tables")
    r.add_argument("--limit", type=int, help="rows per table (tests)")
    r.add_argument("--bootstrap", action="store_true", help="create the mirror tables first")
    r.add_argument("--log-file")
    r.add_argument("--report-file", help="write the full run report (per-table counts) as JSON here, for reconciliation")
    s = sub.add_parser("status", help="show the agent's last runs")
    s.add_argument("--state")
    c = sub.add_parser("reconcile", help="compare a run report's source counts with the website's mirror counts")
    c.add_argument("--api", required=True)
    c.add_argument("--key-env", default="SYNC_API_KEY")
    c.add_argument("--key-file")
    c.add_argument("--report-file", required=True)
    c.add_argument("--expect-source", help="the source label the website must report for its last run (e.g. the live server)")
    args = ap.parse_args(argv[1:])

    handlers = [logging.StreamHandler(sys.stdout)]
    if getattr(args, "log_file", None):
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)

    if args.cmd == "reconcile":
        report = json.loads(Path(args.report_file).read_text(encoding="utf-8"))
        target = ApiTarget(args.api, _key_from(args))
        try:
            remote = target._get("/api/sync/counts")
        finally:
            target.close()
        problems = compare_counts(report, remote, args.expect_source)
        for line in problems:
            print("  MISMATCH:", line)
        print(f"reconciliation: {len(report.get('per_table', {}))} tables compared with the website ({remote.get('environment')}): "
              f"{'ALL MATCH' if not problems else str(len(problems)) + ' problem(s)'}")
        return 0 if not problems else 1

    state = State(args.state or default_state_path())
    if args.cmd == "status":
        print(f"state file: {state.path}  rows remembered: {state.row_count():,}")
        for row in state.last_runs():
            print("  ", *row)
        return 0

    if args.force:
        state.db.execute("UPDATE runs SET status = 'failed', error = 'forced' WHERE status = 'running'")
    source = target = None
    try:
        if args.target_url:
            target = DirectTarget(args.target_url)
        elif args.api:
            secret = os.environ.get(args.cf_client_secret_env) if args.cf_client_id else None
            target = ApiTarget(args.api, _key_from(args), args.cf_client_id, secret)
        else:
            raise RuntimeError("Give --api <website address> (normal use) or --target-url (tests).")
        source = Source(args.source_url, limit=args.limit)
        if args.bootstrap:
            log.info("sync: mirror tables: %s", ", ".join(target.bootstrap()))
        rep = run(source, target, state, full=args.full, dry_run=args.dry_run, tables=args.tables.split(",") if args.tables else None, allow_mass_delete=args.allow_mass_delete)
        print(json.dumps({k: v for k, v in rep.items() if k != "per_table"}))
        if getattr(args, "report_file", None):
            Path(args.report_file).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_file).write_text(json.dumps({**rep, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source.label}, indent=1), encoding="utf-8")
        return 2 if rep["warnings"] else 0  # 2 = completed with skipped deletions: look at the log
    except Exception as exc:  # noqa: BLE001
        print(f"SYNC FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        for closable in (source, target):
            if closable is not None:
                closable.close()
        state.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
