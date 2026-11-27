"""Reconciliation after a sync run: the agent's source counts against the website's mirror counts."""
from app.syncagent import compare_counts

REPORT = {"per_table": {"tblEmployee": {"source_rows": 35435}, "tblCustomer": {"source_rows": 21365}}}


def test_all_match():
    remote = {"environment": "production", "counts": {"tblEmployee": 35435, "tblCustomer": 21365, "tblEmpty": 0},
              "last_run": {"status": "success", "source": "LIVE\\SQLEXPRESS/McLabor"}}
    assert compare_counts(REPORT, remote, "live\\sqlexpress/McLabor") == []


def test_every_kind_of_mismatch_is_named():
    remote = {"environment": "production", "counts": {"tblEmployee": 35000, "tblStray": 3},
              "last_run": {"status": "failed", "source": "sqlite (given)"}}
    problems = compare_counts(REPORT, remote, "LIVE\\SQLEXPRESS/McLabor")
    joined = "\n".join(problems)
    assert "tblEmployee: source 35,435 rows, website 35,000" in joined
    assert "tblCustomer: the website has no such table" in joined
    assert "tblStray: 3 rows on the website but the agent did not read that table" in joined
    assert "came from 'sqlite (given)'" in joined and "status 'failed'" in joined
