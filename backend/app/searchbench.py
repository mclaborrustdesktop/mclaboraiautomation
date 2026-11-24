"""Search benchmark on a synthetic real-size dataset (see scaledata.py).

    .venv\\Scripts\\python.exe -m app.searchbench  PATH\\to\\scale.db  [users]

Part 1 times each kind of search once per run (median of 3) and reports how many SQL statements it
used and how many records it brought into memory.  Part 2 runs the searches from many threads at
once, the way 30+ office staff would.  It uses its own database connection to the file given and
never touches SQL Server or the website's own database.
"""
from __future__ import annotations

import random
import statistics
import sys
import threading
import time
import tracemalloc
from datetime import date

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from . import models as m
from . import search
from .ai import heuristic_interpret
from .database import make_engine
from .seed import week_ending


class Meter:
    """Counts SQL statements and ORM records loaded on one engine."""

    def __init__(self, engine):
        self.statements = 0
        self.records = 0
        self._lock = threading.Lock()
        event.listen(engine, "before_cursor_execute", self._stmt)
        for cls in (m.Employee, m.Customer, m.Project, m.Tracking, m.EmployeeLicense, m.CustomerContact):
            event.listen(cls, "load", self._load)

    def _stmt(self, *a):
        with self._lock:
            self.statements += 1

    def _load(self, *a):
        with self._lock:
            self.records += 1

    def reset(self):
        with self._lock:
            self.statements = self.records = 0


def cases(db_factory):
    """(label, callable) pairs. Each callable opens its own session, like one web request."""

    def run(fn):
        def inner():
            with db_factory() as db:
                return fn(db)
        return inner

    def ai(entity, question):
        def inner(db):
            intent = heuristic_interpret(entity, question, search.vocab(db, entity, question))
            return {"employees": search.search_employees, "customers": search.search_customers, "projects": search.search_projects}[entity](
                db, intent.filters, intent.keywords, 1, 50, with_facets=True)
        return inner

    week = week_ending(date.today())
    return [
        ("employees: first page, no filter", run(lambda db: search.search_employees(db, {}, [], 1, 50, sort="name"))),
        ("employees: by last name 'sullivan'", run(lambda db: search.search_employees(db, {}, ["sullivan"], 1, 50, strict_keywords=True))),
        ("employees: by full name 'maria garcia'", run(lambda db: search.search_employees(db, {}, ["maria", "garcia"], 1, 50, strict_keywords=True))),
        ("employees: trade + state", run(lambda db: search.search_employees(db, {"trade": "Electrician", "state": "MA"}, [], 1, 50))),
        ("employees: trade + city + licensed + 5 yrs", run(lambda db: search.search_employees(
            db, {"trade": "Plumber", "city": "Boston", "licensed": True, "min_years": 5}, [], 1, 50))),
        ("employees: ZIP prefix 021", run(lambda db: search.search_employees(db, {"zip": "021"}, [], 1, 50))),
        ("employees: phone digits 617555", run(lambda db: search.search_employees(db, {}, ["617555"], 1, 50, strict_keywords=True))),
        ("employees: word in notes 'bilingual'", run(lambda db: search.search_employees(db, {}, ["bilingual"], 1, 50, strict_keywords=True))),
        ("employees: page 100 of a big result", run(lambda db: search.search_employees(db, {"state": "MA"}, [], 100, 50, sort="name"))),
        ("AI: 'licensed electricians in Boston who will travel'", run(ai("employees", "licensed electricians in Boston who will travel"))),
        ("AI: 'pipe fitters in Providence with 10+ years'", run(ai("employees", "pipe fitters in Providence with 10+ years"))),
        ("customers: first page, no filter", run(lambda db: search.search_customers(db, {}, [], 1, 50, sort="name"))),
        ("customers: by name 'harbor electric'", run(lambda db: search.search_customers(db, {}, ["harbor", "electric"], 1, 50, strict_keywords=True))),
        ("customers: with active jobs in MA", run(lambda db: search.search_customers(db, {"has_active_projects": True, "state": "MA"}, [], 1, 50))),
        ("AI: 'active general contractors in Boston'", run(ai("customers", "active general contractors in Boston"))),
        ("jobs: first page, newest", run(lambda db: search.search_projects(db, {}, [], 1, 50, sort="start"))),
        ("jobs: by site 'hospital'", run(lambda db: search.search_projects(db, {}, ["medical"], 1, 50, strict_keywords=True))),
        ("jobs: not manned in MA", run(lambda db: search.search_projects(db, {"manned": False, "state": "MA"}, [], 1, 50))),
        ("AI: 'active jobs in Massachusetts that are not manned'", run(ai("projects", "active jobs in Massachusetts that are not manned"))),
        ("tracking: one week, first 50", run(lambda db: search.search_tracking(db, week, None, None, None, None, 1, 50))),
        ("tracking: one week, name 'smith'", run(lambda db: search.search_tracking(db, week, None, None, None, "smith", 1, 50))),
        ("tracking: one employee's history", run(lambda db: search.search_tracking(db, None, 1234, None, None, None, 1, 50))),
    ]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    users = int(argv[2]) if len(argv) > 2 else 35
    runs = int(argv[3]) if len(argv) > 3 else 3
    engine = make_engine(f"sqlite:///{argv[1]}")
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    meter = Meter(engine)
    all_cases = cases(Session)
    search.clear_vocab_cache()

    print(f"PART 1 - one search at a time (median of {runs} run(s))", flush=True)
    print(f"  {'search':56} {'time':>8} {'SQL':>4} {'records':>8} {'matches':>9}")
    worst = 0.0
    for label, fn in all_cases:
        times = []
        for _ in range(runs):
            meter.reset()
            t0 = time.perf_counter()
            res = fn()
            times.append(time.perf_counter() - t0)
        total = res.total if hasattr(res, "total") else res[1]
        med = statistics.median(times)
        worst = max(worst, med)
        print(f"  {label:56} {med * 1000:7.0f}ms {meter.statements:4} {meter.records:8} {total:9,}", flush=True)

    if users <= 0:
        engine.dispose()
        return 0

    def crowd(title: str, searches_each: int, think: tuple[float, float]) -> int:
        lat: list[float] = []
        errors: list[str] = []
        lock = threading.Lock()
        meter.reset()

        def person(n: int):
            r = random.Random(n)
            for _ in range(searches_each):
                if think[1] > 0:
                    time.sleep(r.uniform(*think))
                label, fn = r.choice(all_cases)
                t0 = time.perf_counter()
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        errors.append(f"{label}: {type(exc).__name__}: {exc}")
                    continue
                with lock:
                    lat.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        threads = [threading.Thread(target=person, args=(i,)) for i in range(users)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        wall = time.perf_counter() - t0
        lat.sort()
        print(f"\n{title}", flush=True)
        print(f"  searches completed: {len(lat)} of {users * searches_each}; errors: {len(errors)}; {len(lat) / wall:.1f} searches per second over {wall:.0f} s")
        if lat:
            print(f"  time per search: median {statistics.median(lat) * 1000:.0f} ms, 95% under {lat[max(int(len(lat) * 0.95) - 1, 0)] * 1000:.0f} ms, slowest {lat[-1] * 1000:.0f} ms")
            print(f"  records loaded per search: {meter.records / len(lat):.0f} on average")
        for e in errors[:5]:
            print("  ERROR", e)
        return len(errors)

    import os

    print(f"\n(this PC has {os.cpu_count()} processor threads; the benchmark runs in ONE process, the website uses 4)")
    failed = crowd(f"PART 2 - {users} people working normally (a search every 2 to 6 seconds, 6 searches each)", 6, (2.0, 6.0))
    failed += crowd(f"PART 3 - stress: {users} people all pressing Search at the same instant, 3 searches each, no pauses", 3, (0.0, 0.0))

    tracemalloc.start()
    for _, fn in all_cases:
        fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"\nPART 4 - memory: running all {len(all_cases)} searches one after another used at most {peak / 1048576:.1f} MB at any moment")
    engine.dispose()
    return 1 if failed else 0

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
