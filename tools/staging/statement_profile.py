"""Per-statement timings of one search (SQL shape and seconds only; no parameters, no rows printed)."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import event  # noqa: E402

from app import search  # noqa: E402
from app.ai import heuristic_interpret  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402

assert settings.is_staging and not settings.sql_writes_allowed
question = sys.argv[1] if len(sys.argv) > 1 else "available plumbers with 5+ years experience"
timings: list[tuple[float, str]] = []


@event.listens_for(engine, "before_cursor_execute")
def _b(conn, cursor, statement, parameters, context, executemany):
    context._t0 = time.perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _a(conn, cursor, statement, parameters, context, executemany):
    timings.append((time.perf_counter() - context._t0, re.sub(r"\s+", " ", statement)[:160]))


with SessionLocal() as db:
    search.vocab(db, "employees", question)  # warm the vocabulary
    for _ in range(2):
        timings.clear()
        search.clear_result_cache()
        intent = heuristic_interpret("employees", question, search.vocab(db, "employees", question))
        t0 = time.perf_counter()
        res = search.search_employees(db, intent.filters, intent.keywords, 1, 50, with_facets=True)
        total = time.perf_counter() - t0
        db.rollback()
    print(f"{question!r} -> filters {intent.filters} words {intent.keywords}: {res.total:,} match(es) in {total:.2f}s, {len(timings)} statement(s)")
    for secs, sql in sorted(timings, reverse=True)[:8]:
        print(f"  {secs:5.2f}s  {sql}")
