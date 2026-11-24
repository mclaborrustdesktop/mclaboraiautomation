"""One-way synchronization (office SQL Server -> cloud mirror) on files: the approved spec, the agent's hash-based
reconciliation (no modification timestamps needed), inserts, updates, deletions, duplicate keys, a dry run, an
interrupted run and its recovery, the run lock, and the "last updated" status. Source = a synthetic database in the
production shape (SQLite stands in for SQL Server), mirror = a SQLite file (PostgreSQL in test_sync_postgres.py)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from app import syncagent, syncmirror, syncspec, synthdb
from app.config import settings


@pytest.fixture(scope="module")
def source_url(tmp_path_factory):
    p = tmp_path_factory.mktemp("src") / "synthetic.db"
    url = f"sqlite:///{p.as_posix()}"
    synthdb.build(url, scale=0.01, quiet=True)
    return url


def _count(url: str, table: str, where: str = "") -> int:
    e = create_engine(url, future=True)
    try:
        with e.connect() as c:
            return int(c.execute(text(f'SELECT COUNT(*) FROM "{table}" {where}')).scalar_one())
    finally:
        e.dispose()


def _exec(url: str, sql: str, **params) -> None:
    e = create_engine(url, future=True)
    try:
        with e.begin() as c:
            c.execute(text(sql), params)
    finally:
        e.dispose()


def test_spec_is_the_approved_list_without_sensitive_columns():
    approved = syncspec.approved_tables()
    assert len(approved) == 33 and {"tblEmployee", "tblEmployeeB", "tblCustomer", "tblProject", "tblTracking", "tblOfficeStaff"} <= set(approved)
    for bad in ("SSNum", "EmDOB", "BankAccountNumber", "BankRoutingNumber", "USCitizen", "I9Complete", "EmSex", "EmRaceID", "Citizenship"):
        assert bad not in approved["tblEmployee"]
    assert "OfficeStaffPassword" not in approved["tblOfficeStaff"] and "EmMobilePhone" in approved["tblEmployee"]
    with pytest.raises(ValueError, match="not approved"):
        syncspec.check_columns("tblEmployee", ["EmFirstName", "SSNum"])
    with pytest.raises(ValueError, match="not approved"):
        syncspec.check_columns("tblEmployee", ["EmFirstName", "EmDOB"])
    with pytest.raises(ValueError, match="not an approved table"):
        syncspec.check_columns("tblPayrollAdjustments", ["PayrollAdjustmentID"])
    md = syncspec.mirror_metadata()
    assert set(md.tables) == set(approved)
    assert not any(c.foreign_keys for t in md.tables.values() for c in t.columns)                       # a mirror accepts dangling ids
    assert "SSNum" not in md.tables["tblEmployee"].c and "EmDOB" not in md.tables["tblEmployee"].c      # cannot even hold them
    assert list(md.tables["tblEmployeeB"].primary_key.columns.keys()) == ["EmployeeID"]
    assert syncspec.table_order().index("tblEmployee") < syncspec.table_order().index("tblTracking")
    assert syncspec.table_order().index("tblPullDownTrade") < syncspec.table_order().index("tblEmployee")


def test_initial_sync_then_incremental_updates_inserts_deletes_duplicates(source_url, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sync_api_key", "k" * 40)
    mirror_url = f"sqlite:///{(tmp_path / 'mirror.db').as_posix()}"
    state = syncagent.State(tmp_path / "state.db")
    target = syncagent.DirectTarget(mirror_url)
    assert len(target.bootstrap()) == 33
    source = syncagent.Source(source_url)

    # 1. initial run: everything copied, nothing deleted, every source row remembered
    rep = syncagent.run(source, target, state)
    assert rep["mode"] == "full" and rep["tables"] == 33 and rep["deleted"] == 0 and rep["unchanged"] == 0
    n_emp = _count(source_url, "tblEmployee")
    assert rep["per_table"]["tblEmployee"]["source_rows"] == n_emp == _count(mirror_url, "tblEmployee") >= 1789
    assert _count(mirror_url, "tblTracking") == _count(source_url, "tblTracking") and _count(mirror_url, "tblEmployeeB") == n_emp
    assert state.row_count() == rep["source_rows"] == rep["upserted"]
    cols = {c["name"] for c in inspect(create_engine(mirror_url)).get_columns("tblEmployee")}
    assert "SSNum" not in cols and "EmDOB" not in cols and "EmMobilePhone" in cols
    st = syncmirror.status()
    assert st["applies"] and st["level"] == "fresh" and st["stale"] is False and st["last_success_at"] is not None

    # 2. a second run without changes sends nothing
    rep = syncagent.run(source, target, state)
    assert rep["mode"] == "incremental" and rep["upserted"] == 0 and rep["deleted"] == 0 and rep["unchanged"] == rep["source_rows"]

    # 3. office changes: an update, an insert, two deletions, a duplicate key in the extension table
    _exec(source_url, 'UPDATE "tblEmployee" SET "EmMobilePhone" = \'(617) 555-7777\', "EmZip" = \'02199\' WHERE "EmployeeID" = 5')
    _exec(source_url, 'INSERT INTO "tblCustomer" ("CustomerID", "CustBusName", "City", "State") VALUES (900001, \'Synthetic New Customer\', \'Boston\', \'MA\')')
    _exec(source_url, 'DELETE FROM "tblEmployeeNotes" WHERE "EmployeeNoteID" IN (1, 2)')
    _exec(source_url, 'INSERT INTO "tblEmployeeB" ("EmployeeID", "WillTravel") VALUES (7, \'Duplicate row\')')
    rep = syncagent.run(source, target, state)
    assert rep["per_table"]["tblEmployee"]["upserted"] == 1 and rep["per_table"]["tblCustomer"]["upserted"] == 1
    assert rep["per_table"]["tblEmployeeNotes"]["to_delete"] == 2 and rep["deleted"] == 2
    assert rep["per_table"]["tblEmployeeB"]["source_rows"] == n_emp                                        # the duplicate key counted once
    e = create_engine(mirror_url, future=True)
    with e.connect() as c:
        assert c.execute(text('SELECT "EmMobilePhone", "EmZip" FROM "tblEmployee" WHERE "EmployeeID" = 5')).one() == ("(617) 555-7777", "02199")
        assert c.execute(text('SELECT "CustBusName" FROM "tblCustomer" WHERE "CustomerID" = 900001')).scalar_one() == "Synthetic New Customer"
        assert c.execute(text('SELECT COUNT(*) FROM "tblEmployeeNotes" WHERE "EmployeeNoteID" IN (1, 2)')).scalar_one() == 0
        assert c.execute(text('SELECT COUNT(*) FROM "tblEmployeeB" WHERE "EmployeeID" = 7')).scalar_one() == 1                 # no duplicate row in the mirror
    e.dispose()

    # 4. dry run: changes are detected but nothing is sent or remembered
    _exec(source_url, 'UPDATE "tblEmployee" SET "EmZip" = \'99991\' WHERE "EmployeeID" IN (10, 11, 12)')
    rep = syncagent.run(source, target, state, dry_run=True)
    assert rep["per_table"]["tblEmployee"]["upserted"] == 3 and _count(mirror_url, "tblEmployee", "WHERE \"EmZip\" = '99991'") == 0

    # 5. an interrupted run: the first batch never reaches the cloud; the state is untouched; the next run completes it
    with pytest.raises(InterruptedError):
        syncagent.run(source, target, state, max_batches=0)
    assert state.running() is None and state.last_runs(1)[0][3] == "failed"
    assert _count(mirror_url, "tblEmployee", "WHERE \"EmZip\" = '99991'") == 0
    runs = syncmirror.recent_runs(3)
    assert runs[0]["status"] == "failed" and "InterruptedError" in runs[0]["error"]
    rep = syncagent.run(source, target, state)
    assert rep["per_table"]["tblEmployee"]["upserted"] == 3 and _count(mirror_url, "tblEmployee", "WHERE \"EmZip\" = '99991'") == 3
    assert syncmirror.recent_runs(1)[0]["status"] == "success"

    # 6. the agent refuses to start while another run is marked as running on this PC
    state.db.execute("INSERT INTO runs (started_at, status, mode) VALUES ('2026-11-24T06:00:00', 'running', 'incremental')")
    with pytest.raises(RuntimeError, match="in progress"):
        syncagent.run(source, target, state)
    state.db.execute("UPDATE runs SET status = 'failed' WHERE status = 'running'")

    # 7. --full forgets the state and copies everything again, idempotently (same counts, no duplicates)
    rep = syncagent.run(source, target, state, full=True)
    assert rep["mode"] == "full" and rep["upserted"] == rep["source_rows"] and _count(mirror_url, "tblEmployee") == n_emp
    source.close()
    target.close()
    state.close()


def test_mirror_refuses_unapproved_columns_and_keeps_one_row_per_key(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    e = create_engine(url, future=True)
    syncmirror.bootstrap(e)
    with pytest.raises(ValueError, match="not approved"):
        syncmirror.upsert_rows(e, "tblEmployee", [{"EmployeeID": 1, "EmFirstName": "A", "SSNum": "000-00-0000"}])
    with pytest.raises(ValueError, match="not approved"):
        syncmirror.upsert_rows(e, "tblEmployee", [{"EmployeeID": 1, "EmFirstName": "A", "EmDOB": "1990-01-01"}])
    with pytest.raises(ValueError, match="not an approved table"):
        syncmirror.upsert_rows(e, "tblPayrollAdjustments", [{"PayrollAdjustmentID": 1}])
    with pytest.raises(ValueError, match="without EmployeeID"):
        syncmirror.upsert_rows(e, "tblEmployee", [{"EmFirstName": "A"}])
    # the same key twice in one batch, then again in a later batch: one row, the last values
    assert syncmirror.upsert_rows(e, "tblEmployee", [{"EmployeeID": 1, "EmFirstName": "A", "BaseSalary": "25.50"}, {"EmployeeID": 1, "EmFirstName": "B"}]) == 1
    assert syncmirror.upsert_rows(e, "tblEmployee", [{"EmployeeID": 1, "EmFirstName": "C", "EmEntryTimestamp": "2026-11-24T08:30:00"}]) == 1
    with e.connect() as c:
        assert c.execute(text('SELECT COUNT(*), MAX("EmFirstName") FROM "tblEmployee"')).one() == (1, "C")
    assert syncmirror.delete_rows(e, "tblEmployee", [1, 2, 3]) == 1
    e.dispose()


def test_status_levels(monkeypatch):
    from datetime import datetime, timedelta

    from app.syncmirror import SyncRun
    from app.webauth import _session

    monkeypatch.setattr(settings, "sync_api_key", "k" * 40)
    with _session() as s:
        for r in s.query(SyncRun).filter(SyncRun.environment == settings.environment).all():
            s.delete(r)
        s.commit()
    assert syncmirror.status()["level"] == "never" and syncmirror.status()["stale"] is True
    with _session() as s:
        s.add(SyncRun(environment=settings.environment, status="success", started_at=datetime.utcnow() - timedelta(hours=20), finished_at=datetime.utcnow() - timedelta(hours=20)))
        s.commit()
    st = syncmirror.status()
    assert st["level"] == "aging" and st["stale"] is False and "20 hours old" in st["message"]
    with _session() as s:
        s.add(SyncRun(environment=settings.environment, status="failed", started_at=datetime.utcnow(), error="link down"))
        s.commit()
    st = syncmirror.status()
    assert st["level"] == "aging" and st["last_run"]["status"] == "failed"
    monkeypatch.setattr(settings, "sync_stale_hours", 5)
    assert syncmirror.status()["level"] == "stale" and syncmirror.status()["stale"] is True
    monkeypatch.setattr(settings, "sync_api_key", None)
    assert syncmirror.status() == {"applies": False}   # the demo has no sync
