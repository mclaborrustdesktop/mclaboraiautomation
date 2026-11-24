"""Search service: filtering, keyword matching, ranking, counting and paging all run in the database.

For one search the service runs a small, fixed number of parameterised statements:

  1. COUNT of the matching rows
  2. one page of rows (ORDER BY ... OFFSET/FETCH), never more than MAX_PAGE_SIZE
  3. the related lookups for those rows only (relationship loads keyed by the page's ids)
  4. optionally, facet counts (GROUP BY ... TOP n), first page of the AI search only

No statement returns more rows than a page, so memory use does not depend on the size of the
tables.  Every result row comes from the database; the AI/heuristic layer only turns a question
into filters and keywords.

Works on SQL Server 2019 (staging / production) and on the SQLite demo database.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, literal, literal_column, or_, select, tuple_
from sqlalchemy.orm import Session, selectinload

from . import models as m
from .config import settings
from .sqlutil import ci_eq, ci_order, contains, digits_only, starts_with, text_length, word_start

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_RESULT_WINDOW = 10_000  # deepest row a search may page to; beyond this the user must narrow the search
MAX_KEYWORDS = 8
FACET_VALUES = 8
ACTIVE_PROJECT_STATUS = "Active"


@dataclass
class SearchResult:
    items: list[dict[str, Any]]
    total: int
    facets: list[dict[str, Any]] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------------
def page_window(page: int, page_size: int) -> tuple[int, int]:
    """Validated (offset, limit). Keeps every request bounded no matter what the client asks for."""
    page = max(1, int(page))
    limit = max(1, min(int(page_size), MAX_PAGE_SIZE))
    offset = (page - 1) * limit
    if offset >= MAX_RESULT_WINDOW:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Only the first {MAX_RESULT_WINDOW:,} results of a search can be paged through. Add a filter or keyword to narrow it down.",
        )
    return offset, limit


def clean_keywords(keywords: list[str] | None) -> list[str]:
    out: list[str] = []
    for kw in keywords or []:
        kw = (kw or "").strip().lower()
        if kw and kw not in out:
            out.append(kw[:60])
    return out[:MAX_KEYWORDS]


def _phone_digits(kw: str) -> str | None:
    """Digits of a phone-like keyword ("617", "555-0199", "(617)"), or None for ordinary words."""
    digits = re.sub(r"\D", "", kw)
    return digits if len(digits) >= 3 and not re.search(r"[a-z]", kw) else None


def keyword_sql(keywords: list[str], text_columns: list, phone_columns: list, name_columns: list, extra=None):
    """(match-any predicate, rank expression) for the keywords.

    A row matches when at least one keyword is found in at least one column. Rank = number of keywords
    found, plus half a point for each keyword that starts a word in a name column.
    ``extra(kw)`` may return further predicates (e.g. EXISTS on a child table).
    """
    per_keyword = []
    rank = literal(0.0)
    # With ONE keyword every row that passes the WHERE matched it, so "number of keywords found" is the same for all
    # rows and ranking needs only the name bonus; the match is then evaluated once per row instead of twice.
    single = len(keywords) == 1
    for kw in keywords:
        digits = _phone_digits(kw)
        preds = [contains(col, kw) for col in text_columns]
        if digits:
            # Digits only: matching against the phone with its punctuation removed finds everything the plain
            # LIKE would (removing "(", "-" and spaces never breaks up a run of digits), so the plain LIKE on the
            # phone columns is left out - one scan of each phone column instead of two.
            preds += [digits_only(col).like(f"%{digits}%") for col in phone_columns]
        else:
            preds += [contains(col, kw) for col in phone_columns]
        if extra is not None:
            preds += list(extra(kw))
        hit = or_(*preds)
        per_keyword.append(hit)
        if not single:
            rank = rank + case((hit, 1.0), else_=0.0)
        if name_columns:
            rank = rank + case((or_(*[word_start(col, kw) for col in name_columns]), 0.5), else_=0.0)
    return or_(*per_keyword), rank


# A sub-select inside an OR ("... OR EmTradeID IN (SELECT id FROM lookup WHERE label LIKE ...)") is evaluated by SQL
# Server once per row of the big table, and measured at about two thirds of a word search on the real data
# (tools/prod-check/reports/search-diag-*.txt, variant N). Resolving the small lookup first and writing the ids
# into the statement gives the same rows at a fraction of the cost. Lists are written as integer literals, so
# they never count towards SQL Server's 2,100-parameter limit; above _INLINE_ID_LIMIT the sub-select is kept.
_INLINE_ID_LIMIT = 2000


def _lookup_ids(db: Session, id_column, *conditions) -> list[int] | None:
    """Ids whose row matches, or None when there are too many to write inline."""
    rows = db.execute(select(id_column).where(*conditions).distinct().limit(_INLINE_ID_LIMIT + 1)).all()
    if len(rows) > _INLINE_ID_LIMIT:
        return None
    return [int(r[0]) for r in rows if r[0] is not None]


def _id_in(column, ids: list[int] | None, sub_select):
    """column IN (literal ids), or the sub-select itself when the list was too long to write inline.
    An empty list renders as an always-false comparison (a filter on a value that exists nowhere matches nothing)."""
    if ids is None:
        return column.in_(sub_select)
    return column.in_([literal_column(str(i)) for i in ids])


def _filter_in(db: Session, column, id_column, *label_conditions):
    """column IN (ids of the lookup rows matching the label). A filter such as trade = 'Plumber' written this way is a
    cheap literal comparison that SQL Server evaluates BEFORE the expensive keyword LIKEs (measured: a filtered word
    search fell from 0.8 s to 0.07 s), whereas a sub-select in the same place let the LIKEs run over every row first."""
    sub = select(id_column).where(*label_conditions)
    return _id_in(column, _lookup_ids(db, id_column, *label_conditions), sub)


def _kw_hits(fields: dict[str, str | None], keywords: list[str]) -> tuple[float, list[str]]:
    """Explains, for ONE row already fetched, which keyword matched which field (shown to the user)."""
    if not keywords:
        return 0.0, []
    score = 0.0
    reasons: list[str] = []
    for kw in keywords:
        k = kw.lower()
        digits = _phone_digits(k)
        for label, text in fields.items():
            if not text:
                continue
            t = text.lower()
            if digits and "phone" in label:
                if digits in re.sub(r"\D", "", t):
                    score += 1.5
                    reasons.append(f"phone matches {kw}")
                    break
                continue
            if k in t:
                score += 1.0
                if t.startswith(k) or f" {k}" in t:
                    score += 0.5
                reasons.append(f'“{kw}” in {label}')
                break
    return score, reasons


# Short-lived memory of totals and facet counts (never of records). Keyed by environment + database + the exact
# search, so one environment can never see another's numbers.
_CACHE_MAX_ENTRIES = 1024
_result_cache: dict[tuple, tuple[float, Any]] = {}
_result_cache_lock = threading.Lock()


def clear_result_cache() -> None:
    with _result_cache_lock:
        _result_cache.clear()
        _ids_cache.clear()


def _cache_key(db: Session, kind: str, entity: str, f: dict[str, Any], keywords: list[str], strict: bool) -> tuple:
    bind = str(db.get_bind().url) if hasattr(db, "get_bind") else "recorder"
    return (settings.environment, bind, kind, entity, tuple(sorted((k, str(v)) for k, v in f.items() if v is not None)), tuple(keywords), strict)


def _cached(key: tuple, compute):
    ttl = settings.search_cache_ttl
    if ttl <= 0:
        return compute()
    now = time.monotonic()
    with _result_cache_lock:
        hit = _result_cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = compute()
    with _result_cache_lock:
        if len(_result_cache) >= _CACHE_MAX_ENTRIES:
            for old in sorted(_result_cache, key=lambda k: _result_cache[k][0])[: _CACHE_MAX_ENTRIES // 4]:
                _result_cache.pop(old, None)
        _result_cache[key] = (now, value)
    return value


def _count(db: Session, pk, conditions: list) -> int:
    return db.execute(select(func.count()).select_from(select(pk).where(*conditions).subquery())).scalar_one()


def _unique_order(order: list) -> list:
    """SQL Server refuses an ORDER BY that names the same column twice ("newest first" + the id tie-breaker)."""
    seen, out = set(), []
    for o in order:
        base = o.__clause_element__() if hasattr(o, "__clause_element__") else o
        while getattr(base, "modifier", None) is not None:  # the column underneath .desc() / .asc()
            base = base.element
        key = str(base)
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out


def _page_ids(db: Session, pk, conditions: list, order: list, offset: int, limit: int) -> tuple[list[int], int]:
    """Ids of one page AND the total number of matches, from a single pass over the table."""
    total = func.count().over().label("total_matches")
    rows = db.execute(select(pk, total).where(*conditions).order_by(*_unique_order(order)).offset(offset).limit(limit)).all()
    if rows:
        return [r[0] for r in rows], int(rows[0][1])
    return [], (_count(db, pk, conditions) if offset else 0)  # past the last page: still report the true total


# Result ids remembered per search while the counts cache is on (staging / production, read-only): the ordered ids of
# the first IDS_CACHE_LIMIT matches. Going to page 2, or running the same search again, then costs no table scan.
# Ids only - never records - and bounded: at most _IDS_CACHE_ENTRIES searches x IDS_CACHE_LIMIT integers (about 4 MB).
IDS_CACHE_LIMIT = 2000
_IDS_CACHE_ENTRIES = 256
_ids_cache: dict[tuple, tuple[float, tuple[list[int], int, bool]]] = {}


def _ids_cached(key: tuple | None):
    if key is None or settings.search_cache_ttl <= 0:
        return None
    with _result_cache_lock:
        hit = _ids_cache.get(key)
        return hit[1] if hit and time.monotonic() - hit[0] < settings.search_cache_ttl else None


def _ids_store(key: tuple | None, value: tuple[list[int], int, bool]) -> None:
    if key is None or settings.search_cache_ttl <= 0:
        return
    with _result_cache_lock:
        if len(_ids_cache) >= _IDS_CACHE_ENTRIES:
            for old in sorted(_ids_cache, key=lambda k: _ids_cache[k][0])[: _IDS_CACHE_ENTRIES // 4]:
                _ids_cache.pop(old, None)
        _ids_cache[key] = (time.monotonic(), value)


def _find_page(db: Session, pk, conditions: list, keyword_pred, keyword_rank, keywords: list[str], strict: bool, order_for,
               offset: int, limit: int, cache_key: tuple | None = None) -> tuple[list[int], int, bool, list]:
    """(page ids, total, keywords applied?, final conditions).

    Plain list search (strict): no keyword match means no results.
    AI search: if the leftover words match nothing, the filtered set is still shown.
    """
    with_kw = conditions + [keyword_pred] if keywords else conditions

    def run(off: int, lim: int) -> tuple[list[int], int, bool]:
        if keywords:
            ids, total = _page_ids(db, pk, with_kw, order_for(True), off, lim)
            if total or strict:
                return ids, total, True
        ids, total = _page_ids(db, pk, conditions, order_for(False), off, lim)
        return ids, total, False

    if cache_key is None or settings.search_cache_ttl <= 0:
        ids, total, kw_active = run(offset, limit)
        return ids, total, kw_active, (with_kw if kw_active else conditions)

    hit = _ids_cached(cache_key)
    if hit is None:
        hit = run(0, IDS_CACHE_LIMIT)
        _ids_store(cache_key, hit)
    ids_all, total, kw_active = hit
    page = ids_all[offset:offset + limit]
    complete = len(page) == limit or offset + len(page) >= total  # the page is fully inside the remembered ids
    if not complete and len(ids_all) >= IDS_CACHE_LIMIT:
        page, total, kw_active = run(offset, limit)  # deep page beyond the remembered ids: ask the database
    return page, total, kw_active, (with_kw if kw_active else conditions)


def _in_page_order(rows: list, ids: list[int], key) -> list:
    by_id = {key(r): r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


# At most this many searches run at the same moment in one server process. Others wait their turn briefly and are
# then told the system is busy - a clear answer instead of a frozen screen, and a ceiling on the load put on the database.
_search_slots = threading.BoundedSemaphore(max(1, settings.max_concurrent_searches))


class _SearchSlot:
    def __enter__(self):
        if not _search_slots.acquire(timeout=max(1, settings.search_wait_seconds)):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Many people are searching right now. Please try again in a few seconds.",
                                headers={"Retry-After": "3"})
        return self

    def __exit__(self, *exc):
        _search_slots.release()
        return False


def search_slot() -> _SearchSlot:
    return _SearchSlot()

def _facet(db: Session, key: str, label: str, value_column, base, conditions: list) -> dict[str, Any] | None:
    n = func.count().label("n")
    rows = db.execute(
        base.with_only_columns(value_column.label("v"), n).where(*conditions).where(value_column.isnot(None), value_column != "")
        .group_by(value_column).order_by(n.desc(), value_column).limit(FACET_VALUES)
    ).all()
    if len(rows) < 2:
        return None
    return {"key": key, "label": label, "values": [{"value": v, "count": int(c)} for v, c in rows]}


def _facet_wanted(key: str, f: dict[str, Any]) -> bool:
    """A filter that is already applied as an exact match has only one value left, so counting it would be a wasted pass."""
    return f.get(key) in (None, "") or key in ("trade", "customer")  # these two match more than one value


def _labels(db: Session, id_col, label_col) -> dict[Any, str]:
    """{id: label} of one small lookup table (a few dozen rows); blank labels are left out, as the per-facet SQL leaves them out."""
    return {i: str(lbl) for i, lbl in db.execute(select(id_col, label_col)).all() if lbl is not None and str(lbl) != ""}


def _facets_one_pass(db: Session, pk, conditions: list, specs: list[tuple[str, str, Any, Any]]) -> list[dict[str, Any]]:
    """All facets of a search from ONE pass over the table (SQL Server GROUPING SETS) instead of one pass per facet.

    Each spec is (key, label, column on the searched table, resolver). The database groups by the raw column (an id or
    a text value); the resolver turns a raw value into the label the user sees, or None to leave it out. Counts for
    values that resolve to the same label are added up, exactly as GROUP BY label would. Only the grouped values and
    their counts travel to the application, never a record.
    """
    cols = [col for _, _, col, _ in specs]
    stmt = (select(*cols, *[func.grouping(c).label(f"g{i}") for i, c in enumerate(cols)], func.count(pk).label("n"))
            .where(*conditions).group_by(func.grouping_sets(*[tuple_(c) for c in cols])))
    totals: list[dict[Any, int]] = [{} for _ in specs]
    for row in db.execute(stmt).all():
        n = int(row[-1])
        grouping = row[len(cols):-1]
        for i in range(len(cols)):
            if grouping[i] == 0:  # this row belongs to facet i
                raw = row[i]
                if raw is not None and raw != "":
                    totals[i][raw] = totals[i].get(raw, 0) + n
                break
    out = []
    for (key, label, _, resolve), counts in zip(specs, totals):
        by_label: dict[str, int] = {}
        for raw, n in counts.items():
            lbl = resolve(raw)
            if lbl is not None and lbl != "":
                by_label[lbl] = by_label.get(lbl, 0) + n
        if len(by_label) < 2:
            continue
        top = sorted(by_label.items(), key=lambda kv: (-kv[1], kv[0]))[:FACET_VALUES]
        out.append({"key": key, "label": label, "values": [{"value": v, "count": c} for v, c in top]})
    return out


def _full_name(first, last):
    # the space is written into the SQL text on purpose: as a bound parameter, SQL Server would not recognise the
    # SELECT and GROUP BY copies of this expression as the same thing
    return first + literal_column("' '") + last


# ----------------------------------------------------------------------------
# Vocabulary for the question parser (small lookups, cached; never whole tables)
# ----------------------------------------------------------------------------
_VOCAB_TTL_SECONDS = 600
_vocab_cache: dict[str, tuple[float, dict[str, list[str]]]] = {}
_vocab_lock = threading.Lock()


def clear_vocab_cache() -> None:
    with _vocab_lock:
        _vocab_cache.clear()


def _customers_named_in(db: Session, text: str) -> list[str]:
    """Customers whose business name appears inside the question (job search). One bounded query."""
    text = (text or "").strip().lower()
    if len(text) < 4:
        return []
    name = m.Customer.CustBusName
    haystack = literal(text)
    needle = literal("%") + (name if settings.is_sql_server else func.lower(name)) + literal("%")
    rows = db.execute(
        select(name).where(text_length(name) >= 4, haystack.like(needle)).order_by(text_length(name).desc(), name).limit(3)
    ).all()
    return [r[0] for r in rows]


def vocab(db: Session, entity: str | None = None, query: str | None = None) -> dict[str, list[str]]:
    key = str(db.get_bind().url) if hasattr(db, "get_bind") else "recorder"
    now = time.monotonic()
    with _vocab_lock:
        hit = _vocab_cache.get(key)
        base = hit[1] if hit and now - hit[0] < _VOCAB_TTL_SECONDS else None
    if base is None:
        cities = [c for (c,) in db.execute(select(m.PullDownStateCity.City).distinct()).all()]
        industries = [i for (i,) in db.execute(select(m.Customer.Industry).where(m.Customer.Industry.isnot(None)).distinct()).all() if i]
        salesmen = [
            f"{f} {l}"
            for (f, l) in db.execute(select(m.PullDownSalesman.PullDownSalesmanFName, m.PullDownSalesman.PullDownSalesmanLName)).all()
        ]
        customer_types = [t for (t,) in db.execute(select(m.PullDownCustomerType.PullDownCustomerType)).all() if t and str(t).strip()]
        base = {"cities": cities, "industries": industries, "salesmen": salesmen, "customer_types": customer_types}
        with _vocab_lock:
            _vocab_cache[key] = (now, base)
    customers = _customers_named_in(db, query or "") if entity == "projects" else []
    return {**base, "customers": customers}


# ----------------------------------------------------------------------------
# Employees
# ----------------------------------------------------------------------------
def _employee_conditions(db: Session, f: dict[str, Any]) -> list:
    E, T, Q, S = m.Employee, m.PullDownTrade, m.PullDownQualification, m.PullDownEmployeeStatus
    c: list = [E.EmployeeDuplicate == False]  # noqa: E712
    if f.get("state"):
        c.append(ci_eq(E.EmState, str(f["state"]).upper()))
    if f.get("city"):
        c.append(ci_eq(E.EmCity, f["city"]))
    if f.get("zip"):
        c.append(starts_with(E.EmZip, str(f["zip"]).strip()[:10]))
    if f.get("trade"):
        match = ci_eq(T.PullDownTrade, f["trade"])
        c.append(or_(_filter_in(db, E.EmTradeID, T.PullDownTradeID, match), _filter_in(db, E.SubTrade1ID, T.PullDownTradeID, match),
                     _filter_in(db, E.SubTrade2ID, T.PullDownTradeID, match)))
    if f.get("trade_id"):
        c.append(E.EmTradeID == int(f["trade_id"]))
    if f.get("qualification"):
        c.append(_filter_in(db, E.EmQualificationID, Q.PullDownQualificationID, ci_eq(Q.PullDownQualification, f["qualification"])))
    if f.get("status"):
        c.append(_filter_in(db, E.EmEmployeeStatusID, S.PullDownEmployeeStatusID, ci_eq(S.PullDownEmployeeStatus, f["status"])))
    if f.get("status_id"):
        c.append(E.EmEmployeeStatusID == int(f["status_id"]))
    if f.get("available") is True:
        c.append(E.PostEmployeeAsAvailable == True)  # noqa: E712
    # Written as "id IN (one sub-select)" rather than a per-row EXISTS: the database can then answer it with a single
    # pass over the child table whether or not that table has an index on the link column.
    has_license = E.EmployeeID.in_(select(m.EmployeeLicense.EmployeeID).where(m.EmployeeLicense.EmployeeID.isnot(None)))
    if f.get("licensed") is True:
        c.append(or_(has_license, E.EmLicenseNum.isnot(None)))
    elif f.get("licensed") is False:
        c.append(and_(~has_license, E.EmLicenseNum.is_(None)))
    if f.get("osha") is True:
        c.append(and_(E.OSHA10.isnot(None), E.OSHA10 != ""))
    if f.get("will_travel") is True:
        c.append(and_(E.WillTravel.isnot(None), ~ci_eq(E.WillTravel, "no")))
    if not settings.is_real_data:  # restricted columns: never filtered on with real data
        if f.get("us_citizen") is True:
            c.append(E.USCitizen == True)  # noqa: E712
        if f.get("i9_complete") is not None:
            c.append(E.I9Complete == bool(f["i9_complete"]))
    if f.get("min_years") is not None:
        c.append(E.YearsInTrade >= int(f["min_years"]))
    if f.get("max_years") is not None:
        c.append(E.YearsInTrade <= int(f["max_years"]))
    if f.get("min_rate") is not None:
        c.append(E.BaseSalary >= float(f["min_rate"]))
    if f.get("max_rate") is not None:
        c.append(E.BaseSalary <= float(f["max_rate"]))
    if f.get("license_expiring_days") is not None:
        today = date.today()
        cutoff = today + timedelta(days=int(f["license_expiring_days"]))
        c.append(or_(
            E.EmLicenseDateExpires.between(today, cutoff),
            E.EmployeeID.in_(select(m.EmployeeLicense.EmployeeID).where(m.EmployeeLicense.EmployeeLicenseExpDate.between(today, cutoff))),
        ))
    return c


def _employee_keyword_sql(db: Session, keywords: list[str]):
    E, T, Q = m.Employee, m.PullDownTrade, m.PullDownQualification

    def lookups(kw: str):
        # trade / qualification names that contain the word, resolved first (tiny tables) - see _lookup_ids
        trades = select(T.PullDownTradeID).where(contains(T.PullDownTrade, kw))
        quals = select(Q.PullDownQualificationID).where(contains(Q.PullDownQualification, kw))
        for col, sub, id_col in ((E.EmTradeID, trades, T.PullDownTradeID), (E.EmQualificationID, quals, Q.PullDownQualificationID)):
            ids = _lookup_ids(db, id_col, sub.whereclause)
            if ids:  # no matching lookup row: the OR branch would always be false, so it is simply left out
                yield _id_in(col, ids, sub)
            elif ids is None:
                yield col.in_(sub)

    return keyword_sql(
        keywords,
        text_columns=[E.EmFirstName, E.EmLastName, E.EmCity, E.EmZip, E.EmEmail, E.EmAdminNotes, E.EmSalesNotes, E.EmLicensedIn],
        phone_columns=[E.EmMobilePhone, E.EmHomePhone],
        name_columns=[E.EmFirstName, E.EmLastName],
        extra=lookups,
    )


def search_employees(db: Session, f: dict[str, Any], keywords: list[str], page: int, page_size: int, sort: str = "relevance",
                     strict_keywords: bool = False, with_facets: bool = False) -> SearchResult:
    E = m.Employee
    offset, limit = page_window(page, page_size)
    keywords = clean_keywords(keywords)
    if settings.is_real_data:  # restricted columns cannot be filtered on
        f = {k: v for k, v in f.items() if k not in ("us_citizen", "i9_complete")}
    conditions = _employee_conditions(db, f)
    kw_pred, kw_rank = _employee_keyword_sql(db, keywords) if keywords else (None, literal(0.0))
    years = func.coalesce(E.YearsInTrade, 0)

    def order_for(ranked: bool) -> list:
        chosen = {
            "name": [ci_order(E.EmLastName), ci_order(E.EmFirstName)],
            "newest": [E.EmployeeID.desc()],
            "years": [years.desc()],
            "rate": [func.coalesce(E.BaseSalary, 0)],
        }.get(sort) or ([kw_rank.desc()] if ranked else []) + [years.desc(), ci_order(E.EmLastName)]
        return chosen + [E.EmployeeID]

    with search_slot():
        ids, total, kw_active, conditions = _find_page(db, E.EmployeeID, conditions, kw_pred, kw_rank, keywords, strict_keywords, order_for, offset, limit,
                                                       cache_key=_cache_key(db, "ids", "employees", f, keywords, strict_keywords) + (sort,))
        rows = _in_page_order(list(db.execute(
            select(E)
            .options(selectinload(E.status), selectinload(E.trade), selectinload(E.sub_trade1), selectinload(E.sub_trade2),
                     selectinload(E.qualification), selectinload(E.experience), selectinload(E.licenses))
            .where(E.EmployeeID.in_(ids))
        ).scalars().all()) if ids else [], ids, lambda e: e.EmployeeID)
    last_week = _last_week_ending(db, [e.EmployeeID for e in rows])
    items = []
    for e in rows:
        score, kw_reasons = _kw_hits(
            {"name": f"{e.EmFirstName} {e.EmLastName}", "city": e.EmCity, "zip": e.EmZip, "e-mail": e.EmEmail, "phone": e.EmMobilePhone,
             "home phone": e.EmHomePhone, "admin notes": e.EmAdminNotes, "sales notes": e.EmSalesNotes, "licensed in": e.EmLicensedIn,
             "trade": e.trade.PullDownTrade if e.trade else None,
             "qualification": e.qualification.PullDownQualification if e.qualification else None},
            keywords if kw_active else [],
        )
        item = employee_summary(e, score if kw_active else None, last_week.get(e.EmployeeID))
        item["reasons"] = _employee_reasons(e, f) + kw_reasons
        items.append(item)

    facets: list[dict[str, Any]] = []
    if with_facets and total > 1:
        key = _cache_key(db, "facets", "employees", f, keywords, strict_keywords)
        if settings.supports_grouping_sets:
            def one_pass():
                trade = _labels(db, m.PullDownTrade.PullDownTradeID, m.PullDownTrade.PullDownTrade)
                qual = _labels(db, m.PullDownQualification.PullDownQualificationID, m.PullDownQualification.PullDownQualification)
                stat = _labels(db, m.PullDownEmployeeStatus.PullDownEmployeeStatusID, m.PullDownEmployeeStatus.PullDownEmployeeStatus)
                specs = [
                    ("trade", "Trade", E.EmTradeID, trade.get),
                    ("qualification", "Qualification", E.EmQualificationID, qual.get),
                    ("status", "Status", E.EmEmployeeStatusID, stat.get),
                    ("city", "City", E.EmCity, str),
                    ("state", "State", E.EmState, str),
                ]
                return _facets_one_pass(db, E.EmployeeID, conditions, [s for s in specs if _facet_wanted(s[0], f)])
            facets = _cached(key, one_pass)
        else:
            base = select(E.EmployeeID).select_from(E)
            specs = [
                ("trade", "Trade", m.PullDownTrade.PullDownTrade, base.join(m.PullDownTrade, E.EmTradeID == m.PullDownTrade.PullDownTradeID)),
                ("qualification", "Qualification", m.PullDownQualification.PullDownQualification,
                 base.join(m.PullDownQualification, E.EmQualificationID == m.PullDownQualification.PullDownQualificationID)),
                ("status", "Status", m.PullDownEmployeeStatus.PullDownEmployeeStatus,
                 base.join(m.PullDownEmployeeStatus, E.EmEmployeeStatusID == m.PullDownEmployeeStatus.PullDownEmployeeStatusID)),
                ("city", "City", E.EmCity, base),
                ("state", "State", E.EmState, base),
            ]
            facets = _cached(key, lambda: [x for x in (_facet(db, k, label, col, b, conditions) for k, label, col, b in specs if _facet_wanted(k, f)) if x])
    return SearchResult(items=items, total=total, facets=facets)


def _employee_reasons(e: m.Employee, f: dict[str, Any]) -> list[str]:
    r: list[str] = []
    if f.get("trade") or f.get("trade_id"):
        names = [t.PullDownTrade for t in (e.trade, e.sub_trade1, e.sub_trade2) if t]
        r.append(" / ".join(names[:2]) if names else "trade")
    if f.get("qualification") and e.qualification:
        r.append(e.qualification.PullDownQualification)
    if (f.get("status") or f.get("status_id")) and e.status:
        r.append(e.status.PullDownEmployeeStatus)
    if f.get("available"):
        r.append("posted available")
    if f.get("city") or f.get("state"):
        r.append(f"{e.EmCity}, {e.EmState}" if e.EmCity else (e.EmState or ""))
    if f.get("zip") and e.EmZip:
        r.append(f"ZIP {e.EmZip}")
    if f.get("min_years") is not None or f.get("max_years") is not None:
        r.append(f"{e.YearsInTrade} yrs in trade")
    if f.get("licensed") is True:
        n = len(e.licenses) or (1 if e.EmLicenseNum else 0)
        r.append(f"{n} license{'s' if n != 1 else ''}")
    if f.get("licensed") is False:
        r.append("unlicensed")
    if f.get("osha") and e.OSHA10:
        r.append(e.OSHA10)
    if f.get("will_travel") and e.WillTravel:
        r.append(f"travel: {e.WillTravel}")
    if f.get("min_rate") is not None or f.get("max_rate") is not None:
        r.append(f"${float(e.BaseSalary or 0):.2f}/hr")
    if f.get("license_expiring_days") is not None:
        dates = [l.EmployeeLicenseExpDate for l in e.licenses if l.EmployeeLicenseExpDate] + ([e.EmLicenseDateExpires] if e.EmLicenseDateExpires else [])
        soon = min((d for d in dates if d >= date.today()), default=None)
        if soon:
            r.append(f"license expires {soon.isoformat()}")
    if f.get("us_citizen"):
        r.append("US citizen")
    if f.get("i9_complete") is not None:
        r.append("I-9 complete" if e.I9Complete else "I-9 missing")
    return r


def _last_week_ending(db: Session, employee_ids: list[int]) -> dict[int, date]:
    """Most recent week worked, for the employees on the current page only."""
    if not employee_ids:
        return {}
    q = (select(m.Tracking.EmployeeID, func.max(m.Tracking.WeekEndingDate))
         .where(m.Tracking.EmployeeID.in_(employee_ids)).group_by(m.Tracking.EmployeeID))
    return {eid: d for eid, d in db.execute(q).all()}


def employee_summary(e: m.Employee, score: float | None = None, last_week: date | None = None) -> dict[str, Any]:
    return {
        "EmployeeID": e.EmployeeID,
        "EmFirstName": e.EmFirstName,
        "EmLastName": e.EmLastName,
        "full_name": e.full_name,
        "EmCity": e.EmCity,
        "EmState": e.EmState,
        "EmMobilePhone": e.EmMobilePhone,
        "EmEmail": e.EmEmail,
        "status_name": e.status.PullDownEmployeeStatus if e.status else None,
        "trade_name": e.trade.PullDownTrade if e.trade else None,
        "qualification_name": e.qualification.PullDownQualification if e.qualification else None,
        "experience_name": e.experience.PullDownExperience if e.experience else None,
        "YearsInTrade": e.YearsInTrade,
        "BaseSalary": float(e.BaseSalary) if e.BaseSalary is not None else None,
        "OSHA10": e.OSHA10,
        "PostEmployeeAsAvailable": e.PostEmployeeAsAvailable,
        "EmLicenseDateExpires": e.EmLicenseDateExpires,
        "license_count": len(e.licenses),
        "last_week_ending": last_week,
        "score": score,
        "reasons": [],
    }


# ----------------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------------
def _active_project_exists(db: Session):
    P, PS = m.Project, m.PullDownProjStatus
    active = _filter_in(db, P.ProjStatusID, PS.PullDownProjStatusID, ci_eq(PS.PullDownProjStatus, ACTIVE_PROJECT_STATUS))
    return m.Customer.CustomerID.in_(select(P.CustomerID).where(P.CustomerID.isnot(None), active))


def _customer_conditions(db: Session, f: dict[str, Any]) -> list:
    C, CS, CT, S = m.Customer, m.PullDownCustStatus, m.PullDownCustomerType, m.PullDownSalesman
    c: list = []
    if f.get("state"):
        c.append(ci_eq(C.State, str(f["state"]).upper()))
    if f.get("city"):
        c.append(ci_eq(C.City, f["city"]))
    if f.get("zip"):
        c.append(starts_with(C.Zip, str(f["zip"]).strip()[:10]))
    if f.get("status"):
        c.append(_filter_in(db, C.CustStatusID, CS.PulldownCustStatusID, ci_eq(CS.PulldownCustStatus, f["status"])))
    if f.get("status_id"):
        c.append(C.CustStatusID == int(f["status_id"]))
    if f.get("customer_type"):
        c.append(_filter_in(db, C.CustomerTypeID, CT.PullDownCustomerTypeID, ci_eq(CT.PullDownCustomerType, f["customer_type"])))
    if f.get("type_id"):
        c.append(C.CustomerTypeID == int(f["type_id"]))
    if f.get("salesman"):
        c.append(_filter_in(db, C.SalesmanID, S.PullDownSalesmanID, ci_eq(_full_name(S.PullDownSalesmanFName, S.PullDownSalesmanLName), f["salesman"])))
    if f.get("salesman_id"):
        c.append(C.SalesmanID == int(f["salesman_id"]))
    if f.get("industry"):
        c.append(ci_eq(C.Industry, f["industry"]))
    if f.get("on_hold") is not None:
        c.append(C.OnHold == bool(f["on_hold"]))
    if f.get("contract_on_file") is not None:
        c.append(C.ContractOnFile == bool(f["contract_on_file"]))
    if f.get("min_revenue") is not None:
        c.append(C.RevenuePerYear >= float(f["min_revenue"]))
    if f.get("has_active_projects") is not None:
        c.append(_active_project_exists(db) if bool(f["has_active_projects"]) else ~_active_project_exists(db))
    return c


def _customer_keyword_sql(db: Session, keywords: list[str]):
    C, K = m.Customer, m.CustomerContact

    def contacts(kw: str):
        # customers with a contact person of that name: one pass over the contacts table on its own (0.2 s on the
        # real data) instead of once per customer row inside the OR (0.8 s)
        matching = or_(contains(K.CustomerContactFName, kw), contains(K.CustomerContactLName, kw))
        sub = select(K.CustomerID).where(matching)
        ids = _lookup_ids(db, K.CustomerID, matching)
        if ids:
            yield _id_in(C.CustomerID, ids, sub)
        elif ids is None:
            yield C.CustomerID.in_(sub)

    return keyword_sql(
        keywords,
        text_columns=[C.CustBusName, C.City, C.Zip, C.Street, C.CustEmail, C.Industry, C.CustomerDescription, C.CustomerNote, C.InvoiceNote],
        phone_columns=[C.Phone],
        name_columns=[C.CustBusName],
        extra=contacts,
    )


def customer_project_counts(db: Session, customer_ids: list[int]) -> dict[int, tuple[int, int]]:
    """{customer id: (jobs, active jobs)} for the customers on the current page only."""
    if not customer_ids:
        return {}
    active = case((ci_eq(m.PullDownProjStatus.PullDownProjStatus, ACTIVE_PROJECT_STATUS), 1), else_=0)
    q = (select(m.Project.CustomerID, func.count(m.Project.ProjectID), func.sum(active))
         .outerjoin(m.PullDownProjStatus, m.Project.ProjStatusID == m.PullDownProjStatus.PullDownProjStatusID)
         .where(m.Project.CustomerID.in_(customer_ids)).group_by(m.Project.CustomerID))
    return {cid: (int(n), int(a or 0)) for cid, n, a in db.execute(q).all()}


def search_customers(db: Session, f: dict[str, Any], keywords: list[str], page: int, page_size: int, sort: str = "relevance",
                     strict_keywords: bool = False, with_facets: bool = False) -> SearchResult:
    C = m.Customer
    offset, limit = page_window(page, page_size)
    keywords = clean_keywords(keywords)
    conditions = _customer_conditions(db, f)
    kw_pred, kw_rank = _customer_keyword_sql(db, keywords) if keywords else (None, literal(0.0))
    revenue = func.coalesce(C.RevenuePerYear, 0)

    def order_for(ranked: bool) -> list:
        chosen = {
            "name": [ci_order(C.CustBusName)],
            "newest": [C.CustomerID.desc()],
            "revenue": [revenue.desc()],
        }.get(sort) or ([kw_rank.desc()] if ranked else []) + [revenue.desc(), ci_order(C.CustBusName)]
        return chosen + [C.CustomerID]

    with search_slot():
        ids, total, kw_active, conditions = _find_page(db, C.CustomerID, conditions, kw_pred, kw_rank, keywords, strict_keywords, order_for, offset, limit,
                                                       cache_key=_cache_key(db, "ids", "customers", f, keywords, strict_keywords) + (sort,))
        rows = _in_page_order(list(db.execute(
            select(C)
            .options(selectinload(C.status), selectinload(C.customer_type), selectinload(C.salesman), selectinload(C.sales_status), selectinload(C.contacts))
            .where(C.CustomerID.in_(ids))
        ).scalars().all()) if ids else [], ids, lambda c: c.CustomerID)
    counts = customer_project_counts(db, [c.CustomerID for c in rows])
    items = []
    for c in rows:
        fields = {"name": c.CustBusName, "city": c.City, "zip": c.Zip, "street": c.Street, "e-mail": c.CustEmail, "phone": c.Phone, "industry": c.Industry,
                  "description": c.CustomerDescription, "customer note": c.CustomerNote, "invoice note": c.InvoiceNote,
                  "contacts": " ".join(f"{x.CustomerContactFName} {x.CustomerContactLName}" for x in c.contacts)}
        score, kw_reasons = _kw_hits(fields, keywords if kw_active else [])
        n_projects, n_active = counts.get(c.CustomerID, (0, 0))
        item = customer_summary(c, score if kw_active else None, n_projects, n_active)
        item["reasons"] = _customer_reasons(c, f, n_active) + kw_reasons
        items.append(item)

    facets: list[dict[str, Any]] = []
    if with_facets and total > 1:
        S = m.PullDownSalesman
        key = _cache_key(db, "facets", "customers", f, keywords, strict_keywords)
        if settings.supports_grouping_sets:
            def one_pass():
                stat = _labels(db, m.PullDownCustStatus.PulldownCustStatusID, m.PullDownCustStatus.PulldownCustStatus)
                ctype = _labels(db, m.PullDownCustomerType.PullDownCustomerTypeID, m.PullDownCustomerType.PullDownCustomerType)
                reps = {i: f"{fn} {ln}" for i, fn, ln in db.execute(select(S.PullDownSalesmanID, S.PullDownSalesmanFName, S.PullDownSalesmanLName)).all()
                        if fn is not None and ln is not None}  # the per-facet SQL joins first + last name; NULL in either makes the whole label NULL
                specs = [
                    ("status", "Status", C.CustStatusID, stat.get),
                    ("customer_type", "Type", C.CustomerTypeID, ctype.get),
                    ("city", "City", C.City, str),
                    ("state", "State", C.State, str),
                    ("salesman", "Sales rep", C.SalesmanID, reps.get),
                    ("industry", "Industry", C.Industry, str),
                ]
                return _facets_one_pass(db, C.CustomerID, conditions, [s for s in specs if _facet_wanted(s[0], f)])
            facets = _cached(key, one_pass)
        else:
            base = select(C.CustomerID).select_from(C)
            specs = [
                ("status", "Status", m.PullDownCustStatus.PulldownCustStatus, base.join(m.PullDownCustStatus, C.CustStatusID == m.PullDownCustStatus.PulldownCustStatusID)),
                ("customer_type", "Type", m.PullDownCustomerType.PullDownCustomerType,
                 base.join(m.PullDownCustomerType, C.CustomerTypeID == m.PullDownCustomerType.PullDownCustomerTypeID)),
                ("city", "City", C.City, base),
                ("state", "State", C.State, base),
                ("salesman", "Sales rep", _full_name(S.PullDownSalesmanFName, S.PullDownSalesmanLName), base.join(S, C.SalesmanID == S.PullDownSalesmanID)),
                ("industry", "Industry", C.Industry, base),
            ]
            facets = _cached(key, lambda: [x for x in (_facet(db, k, label, col, b, conditions) for k, label, col, b in specs if _facet_wanted(k, f)) if x])
    return SearchResult(items=items, total=total, facets=facets)


def _customer_reasons(c: m.Customer, f: dict[str, Any], active_projects: int = 0) -> list[str]:
    r: list[str] = []
    if (f.get("status") or f.get("status_id")) and c.status:
        r.append(c.status.PulldownCustStatus)
    if (f.get("customer_type") or f.get("type_id")) and c.customer_type:
        r.append(c.customer_type.PullDownCustomerType)
    if f.get("city") or f.get("state"):
        r.append(f"{c.City}, {c.State}" if c.City else (c.State or ""))
    if f.get("zip") and c.Zip:
        r.append(f"ZIP {c.Zip}")
    if (f.get("salesman") or f.get("salesman_id")) and c.salesman:
        r.append(f"rep {c.salesman.PullDownSalesmanFName} {c.salesman.PullDownSalesmanLName}")
    if f.get("industry") and c.Industry:
        r.append(c.Industry)
    if f.get("on_hold") is not None:
        r.append("on hold" if c.OnHold else "not on hold")
    if f.get("contract_on_file") is not None:
        r.append("contract on file" if c.ContractOnFile else "no contract")
    if f.get("min_revenue") is not None:
        r.append(f"${float(c.RevenuePerYear or 0):,.0f}/yr")
    if f.get("has_active_projects") is not None:
        r.append(f"{active_projects} active jobs")
    return r


def customer_summary(c: m.Customer, score: float | None = None, project_count: int = 0, active_project_count: int = 0) -> dict[str, Any]:
    return {
        "CustomerID": c.CustomerID,
        "CustBusName": c.CustBusName,
        "City": c.City,
        "State": c.State,
        "Phone": c.Phone,
        "CustEmail": c.CustEmail,
        "status_name": c.status.PulldownCustStatus if c.status else None,
        "type_name": c.customer_type.PullDownCustomerType if c.customer_type else None,
        "salesman_name": f"{c.salesman.PullDownSalesmanFName} {c.salesman.PullDownSalesmanLName}" if c.salesman else None,
        "sales_status_name": c.sales_status.PullDownSalesStatus if c.sales_status else None,
        "Industry": c.Industry,
        "ContractOnFile": c.ContractOnFile,
        "OnHold": c.OnHold,
        "RevenuePerYear": float(c.RevenuePerYear) if c.RevenuePerYear is not None else None,
        "project_count": project_count,
        "active_project_count": active_project_count,
        "score": score,
        "reasons": [],
    }


# ----------------------------------------------------------------------------
# Projects (jobs)
# ----------------------------------------------------------------------------
def _start_window(name: str) -> tuple[date, date] | None:
    today = date.today()
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {
        "this_week": (today - timedelta(days=today.weekday()), today + timedelta(days=6 - today.weekday())),
        "this_month": (today.replace(day=1), next_month - timedelta(days=1)),
        "next_month": (next_month, (next_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)),
        "this_year": (today.replace(month=1, day=1), today.replace(month=12, day=31)),
    }.get(name)


def _project_conditions(db: Session, f: dict[str, Any]) -> list:
    P, PS = m.Project, m.PullDownProjStatus
    c: list = []
    SC, ST = m.PullDownStateCity, m.PullDownState
    if f.get("state"):
        if settings.production_shape:  # site city/state come from the city lookup there
            state_ids = select(ST.PullDownStateID).where(ST.PullDownState == str(f["state"]).upper())
            c.append(_filter_in(db, P.SiteStateCityID, SC.PullDownStateCityID, SC.StateID.in_(state_ids)))
        else:
            c.append(ci_eq(P.SiteState, str(f["state"]).upper()))
    if f.get("city"):
        if settings.production_shape:
            c.append(_filter_in(db, P.SiteStateCityID, SC.PullDownStateCityID, ci_eq(SC.City, f["city"])))
        else:
            c.append(ci_eq(P.SiteCity, f["city"]))
    if f.get("zip"):
        c.append(starts_with(P.SiteZip, str(f["zip"]).strip()[:10]))
    if f.get("status"):
        c.append(_filter_in(db, P.ProjStatusID, PS.PullDownProjStatusID, ci_eq(PS.PullDownProjStatus, f["status"])))
    if f.get("status_id"):
        c.append(P.ProjStatusID == int(f["status_id"]))
    if f.get("customer_id"):
        c.append(P.CustomerID == int(f["customer_id"]))
    if f.get("customer"):
        c.append(P.CustomerID.in_(select(m.Customer.CustomerID).where(contains(m.Customer.CustBusName, f["customer"]))))
    if f.get("manned") is not None:
        c.append(P.JobBeingManned == bool(f["manned"]))
    if f.get("ocip") is not None:
        c.append(P.OCIPJob == bool(f["ocip"]))
    if f.get("min_employees") is not None:
        c.append(P.NumberOfEmployees >= int(f["min_employees"]))
    if f.get("trade"):
        c.append(_filter_in(db, P.ProjectWCCID, m.PullDownWCC.PullDownWCCID, contains(m.PullDownWCC.PullDownWCCDesc, f["trade"].split(" ")[0][:5])))
    window = _start_window(f["start_window"]) if f.get("start_window") else None
    if window:
        c.append(P.StartDate.between(*window))
    return c


def _project_keyword_sql(db: Session, keywords: list[str]):
    P, W, SC = m.Project, m.PullDownWCC, m.PullDownStateCity

    def related(kw: str):
        # customers by name stay a sub-select: the job table is small (15,748 rows) and the customer match can be thousands of ids
        yield P.CustomerID.in_(select(m.Customer.CustomerID).where(contains(m.Customer.CustBusName, kw)))
        # the two small lookups are resolved first (see _lookup_ids); site city comes from the city lookup in production
        for col, id_col, label_col in ((P.ProjectWCCID, W.PullDownWCCID, W.PullDownWCCDesc), (P.SiteStateCityID, SC.PullDownStateCityID, SC.City)):
            sub = select(id_col).where(contains(label_col, kw))
            ids = _lookup_ids(db, id_col, sub.whereclause)
            if ids:
                yield _id_in(col, ids, sub)
            elif ids is None:
                yield col.in_(sub)

    return keyword_sql(
        keywords,
        text_columns=[P.SiteName, P.SiteStreet, P.SiteZip, P.ProjNote, P.JobNote, P.ProjOfficeNote, P.CustomerContact]
        + ([] if settings.production_shape else [P.SiteCity]),
        phone_columns=[P.CustomerPhone],
        name_columns=[P.SiteName],
        extra=related,
    )


def assigned_counts(db: Session, project_ids: list[int]) -> dict[int, int]:
    """{job id: number of different workers ever assigned} for the given jobs only."""
    if not project_ids:
        return {}
    q = (select(m.Tracking.ProjectID, func.count(func.distinct(m.Tracking.EmployeeID)))
         .where(m.Tracking.ProjectID.in_(project_ids)).group_by(m.Tracking.ProjectID))
    return {pid: int(n) for pid, n in db.execute(q).all()}


def search_projects(db: Session, f: dict[str, Any], keywords: list[str], page: int, page_size: int, sort: str = "relevance",
                    strict_keywords: bool = False, with_facets: bool = False) -> SearchResult:
    P = m.Project
    offset, limit = page_window(page, page_size)
    keywords = clean_keywords(keywords)
    conditions = _project_conditions(db, f)
    kw_pred, kw_rank = _project_keyword_sql(db, keywords) if keywords else (None, literal(0.0))
    def order_for(ranked: bool) -> list:
        chosen = {
            "name": [ci_order(P.SiteName)],
            "start": [P.StartDate.desc()],
        }.get(sort) or ([kw_rank.desc()] if ranked else [])
        return chosen + [P.ProjectID.desc()]

    with search_slot():
        ids, total, kw_active, conditions = _find_page(db, P.ProjectID, conditions, kw_pred, kw_rank, keywords, strict_keywords, order_for, offset, limit,
                                                       cache_key=_cache_key(db, "ids", "projects", f, keywords, strict_keywords) + (sort,))
        rows = _in_page_order(list(db.execute(
            select(P).options(selectinload(P.customer), selectinload(P.status), selectinload(P.wcc)).where(P.ProjectID.in_(ids))
        ).scalars().all()) if ids else [], ids, lambda p: p.ProjectID)
    assigned = assigned_counts(db, [p.ProjectID for p in rows])
    items = []
    for p in rows:
        fields = {"site": p.SiteName, "city": p.SiteCity, "zip": p.SiteZip, "street": p.SiteStreet, "customer": p.customer.CustBusName if p.customer else None,
                  "site note": p.ProjNote, "job note": p.JobNote, "office note": p.ProjOfficeNote, "contact": p.CustomerContact,
                  "contact phone": p.CustomerPhone, "WCC": p.wcc.PullDownWCCDesc if p.wcc else None}
        score, kw_reasons = _kw_hits(fields, keywords if kw_active else [])
        item = project_summary(p, score if kw_active else None, assigned.get(p.ProjectID, 0))
        item["reasons"] = _project_reasons(p, f) + kw_reasons
        items.append(item)

    facets: list[dict[str, Any]] = []
    if with_facets and total > 1:
        SC, ST = m.PullDownStateCity, m.PullDownState
        base = select(P.ProjectID).select_from(P)
        by_city = base.join(SC, P.SiteStateCityID == SC.PullDownStateCityID)
        specs = [
            ("status", "Status", m.PullDownProjStatus.PullDownProjStatus, base.join(m.PullDownProjStatus, P.ProjStatusID == m.PullDownProjStatus.PullDownProjStatusID)),
            # with real data, site city/state are grouped through the city lookup (SQL Server cannot GROUP BY a sub-select)
            ("city", "City", SC.City, by_city) if settings.production_shape else ("city", "City", P.SiteCity, base),
            ("state", "State", ST.PullDownState, by_city.join(ST, SC.StateID == ST.PullDownStateID)) if settings.production_shape else ("state", "State", P.SiteState, base),
            ("customer", "Customer", m.Customer.CustBusName, base.join(m.Customer, P.CustomerID == m.Customer.CustomerID)),
        ]
        facets = _cached(_cache_key(db, "facets", "projects", f, keywords, strict_keywords),
                         lambda: [x for x in (_facet(db, k, label, col, b, conditions) for k, label, col, b in specs if _facet_wanted(k, f)) if x])
    return SearchResult(items=items, total=total, facets=facets)


def _project_reasons(p: m.Project, f: dict[str, Any]) -> list[str]:
    r: list[str] = []
    if (f.get("status") or f.get("status_id")) and p.status:
        r.append(p.status.PullDownProjStatus)
    if f.get("city") or f.get("state"):
        r.append(f"{p.SiteCity}, {p.SiteState}" if p.SiteCity else (p.SiteState or ""))
    if f.get("zip") and p.SiteZip:
        r.append(f"ZIP {p.SiteZip}")
    if (f.get("customer") or f.get("customer_id")) and p.customer:
        r.append(p.customer.CustBusName)
    if f.get("manned") is not None:
        r.append("manned" if p.JobBeingManned else "needs crew")
    if f.get("ocip"):
        r.append("OCIP")
    if f.get("min_employees") is not None:
        r.append(f"{p.NumberOfEmployees} workers needed")
    if f.get("trade") and p.wcc:
        r.append(p.wcc.PullDownWCCDesc)
    if f.get("start_window") and p.StartDate:
        r.append(f"starts {p.StartDate.isoformat()}")
    return r


def project_summary(p: m.Project, score: float | None = None, assigned_count: int = 0) -> dict[str, Any]:
    return {
        "ProjectID": p.ProjectID,
        "CustomerID": p.CustomerID,
        "customer_name": p.customer.CustBusName if p.customer else None,
        "SiteName": p.SiteName,
        "SiteCity": p.SiteCity,
        "SiteState": p.SiteState,
        "StartDate": p.StartDate,
        "EndDate": p.EndDate,
        "status_name": p.status.PullDownProjStatus if p.status else None,
        "wcc_code": p.wcc.PullDownWCC if p.wcc else None,
        "NumberOfEmployees": p.NumberOfEmployees,
        "JobBeingManned": p.JobBeingManned,
        "ContractAmount": float(p.ContractAmount) if p.ContractAmount is not None else None,
        "assigned_count": assigned_count,
        "score": score,
        "reasons": [],
    }


# ----------------------------------------------------------------------------
# Weekly tracking
# ----------------------------------------------------------------------------
TRACKING_MAX_PAGE_SIZE = 500  # one week's grid for the office; still a hard ceiling


def search_tracking(db: Session, week_ending_date: date | None, employee_id: int | None, customer_id: int | None, project_id: int | None,
                    q: str | None, page: int, page_size: int) -> tuple[list[m.Tracking], int]:
    T = m.Tracking
    page = max(1, int(page))
    limit = max(1, min(int(page_size), TRACKING_MAX_PAGE_SIZE))
    offset = (page - 1) * limit
    if offset >= MAX_RESULT_WINDOW:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Only the first {MAX_RESULT_WINDOW:,} rows can be paged through. Choose a week or add a filter.")
    conditions: list = []
    if week_ending_date:
        conditions.append(T.WeekEndingDate == week_ending_date)
    if employee_id:
        conditions.append(T.EmployeeID == employee_id)
    if customer_id:
        conditions.append(T.CustomerID == customer_id)
    if project_id:
        conditions.append(T.ProjectID == project_id)
    for kw in clean_keywords((q or "").split()):
        conditions.append(or_(
            T.EmployeeID.in_(select(m.Employee.EmployeeID).where(or_(contains(m.Employee.EmFirstName, kw), contains(m.Employee.EmLastName, kw)))),
            T.CustomerID.in_(select(m.Customer.CustomerID).where(contains(m.Customer.CustBusName, kw))),
            T.ProjectID.in_(select(m.Project.ProjectID).where(contains(m.Project.SiteName, kw))),
        ))
    with search_slot():
        ids, total = _page_ids(db, T.TrackingID, conditions, [T.WeekEndingDate.desc(), T.TrackingID], offset, limit)
        rows = _in_page_order(list(db.execute(
            select(T)
            .options(selectinload(T.employee), selectinload(T.customer), selectinload(T.project), selectinload(T.payroll_co_on_site))
            .where(T.TrackingID.in_(ids))
        ).scalars().all()) if ids else [], ids, lambda t: t.TrackingID)
    return rows, total


def tracking_summary(t: m.Tracking) -> dict[str, Any]:
    return {
        "TrackingID": t.TrackingID,
        "CustomerID": t.CustomerID,
        "EmployeeID": t.EmployeeID,
        "ProjectID": t.ProjectID,
        "WeekEndingDate": t.WeekEndingDate,
        "AssignWeek": t.AssignWeek,
        "AssignYear": t.AssignYear,
        "employee_name": t.employee.full_name if t.employee else None,
        "customer_name": t.customer.CustBusName if t.customer else None,
        "site_name": t.project.SiteName if t.project else None,
        "payroll_on_site": t.payroll_co_on_site.PullDownPayrollCoOnSiteInitials if t.payroll_co_on_site else None,
        "PayRate": float(t.PayRate or 0),
        "BillRate": float(t.BillRate or 0),
        "TotalHours": t.TotalHours or 0,
        "RegularHours": t.RegularHours or 0,
        "OvertimeHours": t.OvertimeHours or 0,
        "InvoiceAmount": float(t.InvoiceAmount or 0),
        "EmGrossPayroll": float(t.EmGrossPayroll or 0),
        "CalcProfitMargin": t.CalcProfitMargin,
        "Grade": t.Grade,
        "DirVerified": t.DirVerified,
        "Placeholder": t.Placeholder,
    }
