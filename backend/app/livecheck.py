"""Live search test for the first approved read-only connection.

    .venv\\Scripts\\python.exe -m app.livecheck            (production, read-only - needs backend/.env)
    .venv\\Scripts\\python.exe -m app.livecheck --demo     (same test on the demo data)

Run it AFTER tools\\prod-check\\check_readonly.py reports "READ-ONLY CONNECTION VERIFIED".
It runs the website's real employee, customer, trade and job searches and prints only
counts and timings - never a name, phone number or any other record content.

Safety: it refuses to run if production writes are enabled; the engine's statement guard
still blocks anything that is not a SELECT; it does not start or change the website.
"""
from __future__ import annotations

import sys
import time

from sqlalchemy import func, select, text

from .config import settings

SLOW_SECONDS = 3.0


def run(out=print) -> int:
    from . import models as m
    from . import search
    from .ai import heuristic_interpret
    from .database import SessionLocal

    problems = 0
    warnings = 0

    def timed(label: str, fn):
        nonlocal problems, warnings
        t0 = time.perf_counter()
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            problems += 1
            out(f"  [FAIL] {label}: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
            return None
        secs = time.perf_counter() - t0
        flag = "WARN" if secs > SLOW_SECONDS else " OK "
        warnings += secs > SLOW_SECONDS
        out(f"  [{flag}] {label}: {value if not hasattr(value, 'total') else str(value.total) + ' match(es)'}  ({secs:.2f}s)")
        return value

    with SessionLocal() as db:
        out("1. Table sizes (counts only)")
        sizes = {}
        for label, col in (("employees", m.Employee.EmployeeID), ("customers", m.Customer.CustomerID), ("jobs", m.Project.ProjectID),
                           ("trades", m.PullDownTrade.PullDownTradeID), ("cities", m.PullDownStateCity.PullDownStateCityID)):
            sizes[label] = timed(label, lambda col=col: db.execute(select(func.count(col))).scalar_one())

        if settings.is_sql_server:
            out("1b. Database settings the search relies on")
            collation = timed("collation", lambda: db.execute(text("SELECT CAST(DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS nvarchar(128))")).scalar())
            if collation and "_CS" in collation.upper():
                warnings += 1
                out("  [WARN] The database is case-sensitive: searches will only match text typed in the same upper/lower case.")
            timed("indexes on the four main tables (count)", lambda: db.execute(text(
                "SELECT COUNT(*) FROM sys.indexes i JOIN sys.objects o ON o.object_id = i.object_id "
                "WHERE o.name IN ('tblEmployee', 'tblCustomer', 'tblProject', 'tblTracking') AND i.type > 0")).scalar())

        out("2. Lookups used by the search")
        trade = timed("most common trade (name of a trade, not a person)", lambda: db.execute(
            select(m.PullDownTrade.PullDownTrade).join(m.Employee, m.Employee.EmTradeID == m.PullDownTrade.PullDownTradeID)
            .group_by(m.PullDownTrade.PullDownTrade).order_by(func.count().desc()).limit(1)).scalar())
        state = timed("most common employee state", lambda: db.execute(
            select(m.Employee.EmState).where(m.Employee.EmState.isnot(None)).group_by(m.Employee.EmState).order_by(func.count().desc()).limit(1)).scalar())
        vocab = timed("search vocabulary (cities, industries, sales reps, customer names) loaded", lambda: {k: len(v) for k, v in search.vocab(db).items()})

        out("3. Searches (the website's own search code)")
        timed("employees: first page of everyone, by name", lambda: search.search_employees(db, {}, [], 1, 50, sort="name"))
        timed("employees: page 20 of everyone", lambda: search.search_employees(db, {}, [], 20, 50, sort="name"))
        if trade:
            timed(f"employees: trade = {trade}", lambda: search.search_employees(db, {"trade": trade}, [], 1, 25))
        if trade and state:
            timed(f"employees: trade = {trade}, state = {state}, licensed, 5+ years", lambda: search.search_employees(
                db, {"trade": trade, "state": state, "licensed": True, "min_years": 5}, [], 1, 25))
            timed(f"employees: will travel, state = {state}", lambda: search.search_employees(db, {"will_travel": True, "state": state}, [], 1, 25))
        timed("employees: keyword search", lambda: search.search_employees(db, {}, ["electric"], 1, 50, strict_keywords=True))
        timed("employees: two-word name search", lambda: search.search_employees(db, {}, ["john", "smith"], 1, 50, strict_keywords=True))
        timed("employees: phone digits 617", lambda: search.search_employees(db, {}, ["617"], 1, 50, strict_keywords=True))
        if trade:
            timed(f"employees: trade = {trade} with filter counts (as the AI search page does)", lambda: search.search_employees(db, {"trade": trade}, [], 1, 50, with_facets=True))
        timed("customers: all", lambda: search.search_customers(db, {}, [], 1, 25, sort="name"))
        timed("customers: with active jobs", lambda: search.search_customers(db, {"has_active_projects": True}, [], 1, 25))
        timed("jobs: all", lambda: search.search_projects(db, {}, [], 1, 25))
        timed("weekly tracking: newest 50 rows", lambda: f"{search.search_tracking(db, None, None, None, None, None, 1, 50)[1]} row(s)")
        timed("jobs: not manned", lambda: search.search_projects(db, {"manned": False}, [], 1, 25))
        if state:
            timed(f"jobs: state = {state}", lambda: search.search_projects(db, {"state": state}, [], 1, 25))

        out("4. Plain-English question -> filters (built-in parser, nothing sent outside this PC)")
        if trade:
            full_vocab = search.vocab(db) if vocab is not None else {"cities": [], "industries": [], "salesmen": [], "customers": []}
            question = f"licensed {trade.lower()}s in {state or 'MA'} who will travel"
            intent = heuristic_interpret("employees", question, full_vocab)
            out(f"         \"{question}\" -> {intent.filters}")
            timed("employees: that question", lambda: search.search_employees(db, intent.filters, intent.keywords, 1, 25))
        db.rollback()

    out("")
    out(f"RESULT: {'PROBLEMS FOUND' if problems else 'OK'} - {problems} failure(s), {warnings} warning(s). No records were printed and nothing was written.")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    demo = "--demo" in argv
    if settings.is_sql_server:
        if demo:
            print(f"--demo was given but backend/.env selects {settings.environment}. Nothing was run.")
            return 2
        if settings.sql_writes_allowed:
            print(f"Writes are enabled for {settings.environment}. This test only runs while the database is read-only. Nothing was run.")
            return 2
        print(f"Live search test: {settings.environment_label} on {settings.db_expected_server_name} (READ-ONLY)")
    elif not demo:
        print("backend/.env selects the demo environment (DATA_SOURCE=staging or production is needed), so there is nothing live to test.")
        print("Use --demo to run the same test on the demo data.")
        return 2
    else:
        print("Search test on the DEMO data")
    return run()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
