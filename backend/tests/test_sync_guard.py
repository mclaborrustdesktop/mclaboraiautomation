"""The deletion guard: an incomplete, limited or implausibly small source read must never wipe the mirror.
Agent side (skips the deletions, keeps the upserts, warns) and cloud side (refuses a run that would delete more than
10% of the mirror unless the agent asked for it explicitly)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app import syncagent, syncmirror, synthdb
from app.config import settings


def _count(url: str, table: str) -> int:
    e = create_engine(url, future=True)
    try:
        with e.connect() as c:
            return int(c.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())
    finally:
        e.dispose()


@pytest.fixture()
def synced(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sync_api_key", "k" * 40)
    src = f"sqlite:///{(tmp_path / 'src.db').as_posix()}"
    synthdb.build(src, scale=0.01, quiet=True)
    mirror = f"sqlite:///{(tmp_path / 'mirror.db').as_posix()}"
    state = syncagent.State(tmp_path / "state.db")
    target = syncagent.DirectTarget(mirror)
    target.bootstrap()
    source = syncagent.Source(src)
    syncagent.run(source, target, state)
    yield src, mirror, state, target
    source.close()
    target.close()
    state.close()


def test_limited_or_partial_runs_never_delete(synced, tmp_path):
    src, mirror, state, target = synced
    n = _count(mirror, "tblTracking")
    limited = syncagent.Source(src, limit=50)          # reads 50 rows per table: the other rows are NOT "gone"
    rep = syncagent.run(limited, target, state)
    assert rep["deleted"] == 0 and rep["skipped_deletions"] > 0 and any("limited/partial" in w for w in rep["warnings"])
    assert _count(mirror, "tblTracking") == n
    limited.close()
    full = syncagent.Source(src)
    rep = syncagent.run(full, target, state, tables=["tblPullDownTrade"])   # a subset of tables is also partial
    assert rep["deleted"] == 0 and _count(mirror, "tblTracking") == n
    full.close()


def test_an_implausible_shrink_is_skipped_until_a_human_allows_it(synced):
    src, mirror, state, target = synced
    n_track = _count(mirror, "tblTracking")
    e = create_engine(src, future=True)
    with e.begin() as c:   # half the tracking table vanishes from the source (a wrong restore, a truncated table...)
        c.execute(text('DELETE FROM "tblTracking" WHERE "TrackingID" % 2 = 0'))
        c.execute(text('DELETE FROM "tblEmployeeNotes" WHERE "EmployeeNoteID" <= 5'))   # a normal small deletion elsewhere
    e.dispose()
    source = syncagent.Source(src)
    rep = syncagent.run(source, target, state)
    assert rep["per_table"]["tblTracking"]["to_delete"] == 0 and any("tblTracking" in w and "implausible" in w for w in rep["warnings"])
    assert rep["per_table"]["tblEmployeeNotes"]["to_delete"] == 5 and rep["deleted"] == 5     # the small, plausible deletion went through
    assert _count(mirror, "tblTracking") == n_track                                             # the mirror still has every tracking row
    assert syncmirror.recent_runs(1)[0]["status"] == "success" and "implausible" in syncmirror.recent_runs(1)[0]["error"]
    # the next run sees the same picture and still refuses; with --allow-mass-delete (after a human checked) it proceeds
    rep = syncagent.run(source, target, state)
    assert rep["per_table"]["tblTracking"]["to_delete"] == 0 and _count(mirror, "tblTracking") == n_track
    rep = syncagent.run(source, target, state, allow_mass_delete=True)
    assert rep["per_table"]["tblTracking"]["to_delete"] == n_track // 2 and _count(mirror, "tblTracking") == n_track - n_track // 2
    assert syncmirror.recent_runs(1)[0]["allow_mass_delete"] is True
    source.close()


def test_an_empty_source_table_never_empties_the_mirror(synced):
    src, mirror, state, target = synced
    n = _count(mirror, "tblCustomerNotes")
    e = create_engine(src, future=True)
    with e.begin() as c:
        c.execute(text('DELETE FROM "tblCustomerNotes"'))
    e.dispose()
    source = syncagent.Source(src)
    rep = syncagent.run(source, target, state)
    assert rep["per_table"]["tblCustomerNotes"]["source_rows"] == 0 and rep["per_table"]["tblCustomerNotes"]["to_delete"] == 0
    assert _count(mirror, "tblCustomerNotes") == n and any("tblCustomerNotes" in w for w in rep["warnings"])
    source.close()


def test_cloud_side_budget_refuses_mass_deletion_even_from_a_misbehaving_agent(synced):
    src, mirror, state, target = synced
    n_emp = _count(mirror, "tblEmployee")
    total = sum(max(0, v) for v in syncmirror.row_counts(target.engine).values())
    run_id = target.begin_run("incremental", "misbehaving agent")                      # guard in place: at most 10% of the mirror (min 500)
    budget = max(syncmirror.MAX_RUN_DELETE_ROWS, int(total * syncmirror.MAX_RUN_DELETE_FRACTION))
    ids = list(range(1, n_emp + 1))
    assert len(ids) > budget
    with pytest.raises(syncmirror.MassDeleteRefused, match="more than the guard allows"):
        target.delete(run_id, "tblEmployee", ids)
    assert _count(mirror, "tblEmployee") == n_emp                                          # nothing was deleted
    assert target.delete(run_id, "tblEmployee", ids[:10]) == 10                            # a small deletion is fine
    with pytest.raises(syncmirror.MassDeleteRefused):
        target.delete(run_id, "tblEmployee", ids[10:10 + budget])                          # cumulative across batches
    target.finish_run(run_id, "failed", error="test")
    run_id = target.begin_run("incremental", "agent with --allow-mass-delete", allow_mass_delete=True)
    assert target.delete(run_id, "tblEmployee", ids[10:10 + budget]) == budget
    target.finish_run(run_id, "success", deleted=budget)
