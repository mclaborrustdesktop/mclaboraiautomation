"""Times the website's OWN search code against the STAGING copy. Counts, timings and SQL statement counts only.

    powershell -File tools\\staging\\run-readonly.ps1 ..\\tools\\staging\\search_timing.py LABEL [runs]

Runs each search `runs` times (default 3) and reports the median and the fastest run, so that the same list can
be timed before and after a code change. Read-only: the engine refuses anything but SELECT. No record is printed.
"""
from __future__ import annotations

import datetime as dt
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import event  # noqa: E402

from app import search  # noqa: E402
from app.ai import heuristic_interpret  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402

assert settings.is_staging and not settings.sql_writes_allowed, "staging, read-only only"

label = sys.argv[1] if len(sys.argv) > 1 else "run"
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
lines: list[str] = []


def say(s: str = "") -> None:
    lines.append(s)
    print(s, flush=True)


class Meter:
    def __init__(self) -> None:
        self.statements = 0
        self.lock = threading.Lock()
        event.listen(engine, "before_cursor_execute", self._stmt)

    def _stmt(self, *a):
        with self.lock:
            self.statements += 1

    def reset(self):
        with self.lock:
            self.statements = 0


def ai(entity: str, question: str):
    def inner(db):
        intent = heuristic_interpret(entity, question, search.vocab(db, entity, question))
        fn = {"employees": search.search_employees, "customers": search.search_customers, "projects": search.search_projects}[entity]
        return fn(db, intent.filters, intent.keywords, 1, 50, with_facets=True)
    return inner


CASES = [
    ("employees: first page, by name", lambda db: search.search_employees(db, {}, [], 1, 50, sort="name")),
    ("employees: word 'smith' (list search box)", lambda db: search.search_employees(db, {}, ["smith"], 1, 50, strict_keywords=True)),
    ("employees: words 'john smith'", lambda db: search.search_employees(db, {}, ["john", "smith"], 1, 50, strict_keywords=True)),
    ("employees: word 'electric' (also matches the trade)", lambda db: search.search_employees(db, {}, ["electric"], 1, 50, strict_keywords=True)),
    ("employees: word 'foreman' (notes)", lambda db: search.search_employees(db, {}, ["foreman"], 1, 50, strict_keywords=True)),
    ("employees: digits '617' (phone)", lambda db: search.search_employees(db, {}, ["617"], 1, 50, strict_keywords=True)),
    ("employees: word 'smith', page 2 (cold)", lambda db: search.search_employees(db, {}, ["smith"], 2, 50, strict_keywords=True)),
    ("employees: word 'smith', page 2 right after page 1 (30 s memory)", lambda db: (search.search_employees(db, {}, ["smith"], 1, 50, strict_keywords=True),
                                                                                 search.search_employees(db, {}, ["smith"], 2, 50, strict_keywords=True))[1], "warm"),
    ("employees: trade filter + word 'smith'", lambda db: search.search_employees(db, {"trade": "Electrician"}, ["smith"], 1, 50, strict_keywords=True)),
    ("AI employees: 'licensed electricians' + filter counts", ai("employees", "licensed electricians")),
    ("AI employees: 'available plumbers with 5+ years experience'", ai("employees", "available plumbers with 5+ years experience")),
    ("customers: first page, by name", lambda db: search.search_customers(db, {}, [], 1, 50, sort="name")),
    ("customers: word 'electric'", lambda db: search.search_customers(db, {}, ["electric"], 1, 50, strict_keywords=True)),
    ("customers: words 'harbor electric'", lambda db: search.search_customers(db, {}, ["harbor", "electric"], 1, 50, strict_keywords=True)),
    ("customers: digits '617' (phone)", lambda db: search.search_customers(db, {}, ["617"], 1, 50, strict_keywords=True)),
    ("AI customers: 'customers in MA with active jobs' + counts", ai("customers", "customers in MA with active jobs")),
    ("jobs: word 'school'", lambda db: search.search_projects(db, {}, ["school"], 1, 50, strict_keywords=True)),
    ("AI jobs: 'active jobs in MA not manned' + counts", ai("projects", "active jobs in MA not manned")),
    ("tracking: newest 50", lambda db: search.search_tracking(db, None, None, None, None, None, 1, 50)),
]


def main() -> int:
    meter = Meter()
    say(f"Search timing [{label}] - STAGING copy {settings.db_expected_server_name}, read-only, {runs} run(s) each, median / fastest")
    say(dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    say(f"  {'search':62} {'median':>8} {'fastest':>8} {'SQL':>4} {'matches':>9}")
    total_median = 0.0
    for case in CASES:
        name, fn, warm = (case + ("",))[:3]
        times, total, stmts = [], None, 0
        for _ in range(runs):
            search.clear_result_cache()  # time the real work, not the 30-second memory of counts
            with SessionLocal() as db:
                t0 = time.perf_counter()
                try:
                    if warm:  # the case runs page 1 itself; time only the page-2 part that follows it
                        search.search_employees(db, {}, ["smith"], 1, 50, strict_keywords=True)
                        t0 = time.perf_counter()
                    meter.reset()
                    res = fn(db) if not warm else search.search_employees(db, {}, ["smith"], 2, 50, strict_keywords=True)
                except Exception as exc:  # noqa: BLE001
                    say(f"  {name:62} FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:120]}")
                    times = []
                    break
                times.append(time.perf_counter() - t0)
                db.rollback()
            stmts = meter.statements
            total = res.total if hasattr(res, "total") else res[1]
        if times:
            med = statistics.median(times)
            total_median += med
            say(f"  {name:62} {med:7.2f}s {min(times):7.2f}s {stmts:4} {total:9,}")
    say(f"  {'SUM of medians':62} {total_median:7.2f}s")
    say("No record content was printed; nothing was written.")
    out = ROOT / "tools" / "prod-check" / "reports" / f"search-timing-{label}-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
