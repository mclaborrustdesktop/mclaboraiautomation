"""The ingest API never mixes two sources: SYNC_EXPECTED_SOURCE, and the source of the mirror's earlier successful runs."""
import pytest

from app import syncmirror
from app.config import settings


@pytest.fixture
def runs(client):
    with syncmirror._session() as s:
        s.query(syncmirror.SyncRun).delete()
        s.commit()
    yield
    with syncmirror._session() as s:
        s.query(syncmirror.SyncRun).delete()
        s.commit()


def test_a_mirror_sticks_to_the_source_of_its_successful_runs(runs):
    run_id = syncmirror.start_run("full", "sqlite (given)", "agent-test")
    syncmirror.finish_run(run_id, "success", tables=1, upserted=1)
    with pytest.raises(ValueError, match="never mixed"):
        syncmirror.start_run("incremental", "LIVE\\SQLEXPRESS/McLabor", "agent-test")
    assert syncmirror.start_run("incremental", "sqlite (given)", "agent-test") > run_id     # same source: fine
    assert syncmirror.start_run("incremental", "SQLITE (given)", "agent-test") > run_id     # case does not matter


def test_the_expected_source_setting_refuses_everything_else(runs, monkeypatch):
    monkeypatch.setattr(settings, "sync_expected_source", "LIVE\\SQLEXPRESS/McLabor")
    with pytest.raises(ValueError, match="SYNC_EXPECTED_SOURCE"):
        syncmirror.start_run("full", "sqlite (given)", "agent-test")
    with pytest.raises(ValueError, match="SYNC_EXPECTED_SOURCE"):
        syncmirror.start_run("full", None, "agent-test")
    assert syncmirror.start_run("full", "live\\sqlexpress/McLabor", "agent-test") >= 1
