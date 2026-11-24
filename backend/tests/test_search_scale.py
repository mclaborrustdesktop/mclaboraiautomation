"""Search at scale: database-side filtering, paging, ranking and concurrency.

Uses a synthetic database one fifth the size of the real one (about 36,000 employees, 21,000 customers,
3,000 jobs, 38,000 tracking rows) built once per test run, plus the small demo database through the API.
No SQL Server is contacted. Time limits are deliberately generous so the tests are stable on a busy PC.
"""
from __future__ import annotations

import threading
import time
from datetime import date

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import sessionmaker

from app import models as m
from app import scaledata, search
from app.ai import heuristic_interpret
from app.config import settings
from app.database import make_engine
from app.seed import week_ending

SCALE = 0.2
PAGE = 50


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    path = tmp_path_factory.mktemp("scale") / "scale.db"
    counts = scaledata.build(str(path), SCALE, quiet=True)
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    search.clear_vocab_cache()
    search.clear_result_cache()
    yield {"Session": Session, "engine": engine, "counts": counts}
    engine.dispose()


class Meter:
    """Counts SQL statements and records brought into memory while active."""

    def __init__(self, engine):
        self.engine, self.statements, self.records = engine, 0, 0
        self.sql: list[str] = []

    def _stmt(self, conn, cursor, statement, *a):
        self.statements += 1
        self.sql.append(statement)

    def _load(self, *a):
        self.records += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._stmt)
        for cls in (m.Employee, m.Customer, m.Project, m.Tracking):
            event.listen(cls, "load", self._load)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._stmt)
        for cls in (m.Employee, m.Customer, m.Project, m.Tracking):
            event.remove(cls, "load", self._load)


def scalar(db, sql: str, **params) -> int:
    return db.execute(text(sql), params).scalar_one()


# ---------------------------------------------------------------- the data set
def test_dataset_is_large(big):
    c = big["counts"]
    assert c["employees"] > 30_000 and c["customers"] > 20_000 and c["projects"] > 3_000 and c["tracking"] > 35_000


# ---------------------------------------------------------------- bounded work per search
@pytest.mark.parametrize("label,call", [
    ("employees no filter", lambda db: search.search_employees(db, {}, [], 1, PAGE, sort="name")),
    ("employees by name", lambda db: search.search_employees(db, {}, ["sullivan"], 1, PAGE, strict_keywords=True)),
    ("employees trade+state+facets", lambda db: search.search_employees(db, {"trade": "Electrician", "state": "MA"}, [], 1, PAGE, with_facets=True)),
    ("customers by name", lambda db: search.search_customers(db, {}, ["harbor"], 1, PAGE, strict_keywords=True)),
    ("customers with active jobs", lambda db: search.search_customers(db, {"has_active_projects": True}, [], 1, PAGE)),
    ("jobs by site", lambda db: search.search_projects(db, {}, ["medical"], 1, PAGE, strict_keywords=True)),
])
def test_search_never_loads_more_than_a_page(big, label, call):
    with big["Session"]() as db, Meter(big["engine"]) as meter:
        t0 = time.perf_counter()
        res = call(db)
        seconds = time.perf_counter() - t0
    assert res.total > PAGE, label                 # the search matches far more than one page...
    assert len(res.items) == PAGE                  # ...but only one page is returned
    main_entity = {"employees": PAGE, "customers": PAGE, "jobs": PAGE}[label.split(" ")[0]]
    assert meter.records <= main_entity * 3, (label, meter.records)   # the page plus the records it links to, nothing else
    assert meter.statements <= 16, (label, meter.statements)
    assert seconds < 5, (label, seconds)
    # the statement that finds the page is limited in the database, not in Python
    assert any("LIMIT" in s.upper() and "OFFSET" in s.upper() for s in meter.sql), label


def test_memory_per_search_is_small(big):
    import tracemalloc

    with big["Session"]() as db:
        search.search_employees(db, {}, [], 1, PAGE)  # warm up imports/caches
        tracemalloc.start()
        res = search.search_employees(db, {"state": "MA"}, ["a"], 1, PAGE, with_facets=True)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert res.total > 5_000
    assert peak < 20 * 1024 * 1024, f"{peak / 1048576:.1f} MB used for one search"


# ---------------------------------------------------------------- pagination
def test_pages_are_complete_distinct_and_repeatable(big):
    with big["Session"]() as db:
        f = {"state": "CT", "trade": "Plumber"}
        first = search.search_employees(db, f, [], 1, PAGE, sort="name")
        total = first.total
        expected = scalar(db, "SELECT COUNT(*) FROM tblEmployee e JOIN tblPullDownTrade t ON t.PullDownTradeID IN (e.EmTradeID, e.SubTrade1ID, e.SubTrade2ID) "
                              "WHERE e.EmState = 'CT' AND t.PullDownTrade = 'Plumber' AND e.EmployeeDuplicate = 0")
        assert total == expected and total > PAGE * 2
        seen: list[int] = []
        pages = (total + PAGE - 1) // PAGE
        for page in range(1, pages + 1):
            res = search.search_employees(db, f, [], page, PAGE, sort="name")
            assert res.total == total
            assert len(res.items) == (PAGE if page < pages else total - PAGE * (pages - 1))
            seen += [i["EmployeeID"] for i in res.items]
        assert len(seen) == total and len(set(seen)) == total          # every match exactly once
        again = search.search_employees(db, f, [], 2, PAGE, sort="name")
        assert [i["EmployeeID"] for i in again.items] == seen[PAGE:PAGE * 2]  # same request, same page
        names = [(i["EmLastName"].lower(), i["EmFirstName"].lower()) for i in first.items]
        assert names == sorted(names)
        beyond = search.search_employees(db, f, [], pages + 5, PAGE, sort="name")
        assert beyond.items == [] and beyond.total == total


@pytest.mark.parametrize("sort,key,reverse", [("years", lambda i: i["YearsInTrade"] or 0, True), ("rate", lambda i: i["BaseSalary"] or 0, False),
                                             ("newest", lambda i: i["EmployeeID"], True)])
def test_sorting_is_done_by_the_database(big, sort, key, reverse):
    with big["Session"]() as db:
        res = search.search_employees(db, {"state": "MA"}, [], 1, PAGE, sort=sort)
        values = [key(i) for i in res.items]
        assert values == sorted(values, reverse=reverse)
        best = scalar(db, {"years": "SELECT MAX(COALESCE(YearsInTrade,0)) FROM tblEmployee WHERE EmState='MA' AND EmployeeDuplicate=0",
                           "rate": "SELECT MIN(COALESCE(BaseSalary,0)) FROM tblEmployee WHERE EmState='MA' AND EmployeeDuplicate=0",
                           "newest": "SELECT MAX(EmployeeID) FROM tblEmployee WHERE EmState='MA' AND EmployeeDuplicate=0"}[sort])
        assert float(values[0]) == float(best)  # the true first row of the whole result, not of a sample


def test_page_size_and_depth_are_limited(big, client, admin_headers):
    with big["Session"]() as db:
        res = search.search_employees(db, {}, [], 1, 100_000)
        assert len(res.items) == search.MAX_PAGE_SIZE
        with pytest.raises(Exception) as e:
            search.search_employees(db, {}, [], search.MAX_RESULT_WINDOW // PAGE + 1, PAGE)
        assert "narrow it down" in str(e.value.detail)
    r = client.get("/api/employees", headers=admin_headers)
    assert r.status_code == 200 and r.json()["page_size"] == 50                       # default page size
    assert len(r.json()["items"]) == min(50, r.json()["total"])
    assert client.get("/api/employees", params={"page_size": 5000}, headers=admin_headers).status_code == 422
    assert client.get("/api/employees", params={"page": 100000}, headers=admin_headers).status_code == 422
    r = client.post("/api/search", json={"entity": "employees", "query": "electricians"}, headers=admin_headers)
    assert r.json()["page_size"] == 50
    assert client.post("/api/search", json={"entity": "employees", "query": "electricians", "page_size": 5000}, headers=admin_headers).status_code == 422


# ---------------------------------------------------------------- filtering
def test_filters_match_independent_counts(big):
    with big["Session"]() as db:
        cases = [
            ({"state": "ma"}, "EmState = 'MA'"),
            ({"city": "boston"}, "LOWER(EmCity) = 'boston'"),
            ({"zip": "021"}, "EmZip LIKE '021%'"),
            ({"state": "MA", "min_years": 10, "max_rate": 40}, "EmState = 'MA' AND YearsInTrade >= 10 AND BaseSalary <= 40"),
            ({"available": True, "osha": True}, "PostEmployeeAsAvailable = 1 AND OSHA10 IS NOT NULL AND OSHA10 <> ''"),
            ({"licensed": True, "state": "RI"}, "EmState = 'RI' AND (EmLicenseNum IS NOT NULL OR EmployeeID IN (SELECT EmployeeID FROM tblEmployeeLicenses))"),
            ({"licensed": False, "state": "RI"}, "EmState = 'RI' AND EmLicenseNum IS NULL AND EmployeeID NOT IN (SELECT EmployeeID FROM tblEmployeeLicenses)"),
            ({"will_travel": True}, "WillTravel IS NOT NULL AND LOWER(WillTravel) <> 'no'"),
        ]
        for f, where in cases:
            res = search.search_employees(db, f, [], 1, PAGE)
            assert res.total == scalar(db, f"SELECT COUNT(*) FROM tblEmployee WHERE EmployeeDuplicate = 0 AND {where}"), f
            assert res.total > 0, f
        res = search.search_employees(db, {"state": "MA", "city": "Boston", "zip": "02"}, [], 1, PAGE)
        assert all(i["EmState"] == "MA" and i["EmCity"] == "Boston" for i in res.items)

        assert search.search_customers(db, {"state": "MA", "on_hold": True}, [], 1, PAGE).total == scalar(db, "SELECT COUNT(*) FROM tblCustomer WHERE State='MA' AND OnHold=1")
        assert search.search_customers(db, {"zip": "03"}, [], 1, PAGE).total == scalar(db, "SELECT COUNT(*) FROM tblCustomer WHERE Zip LIKE '03%'")
        active = "SELECT COUNT(*) FROM tblCustomer c WHERE {neg} EXISTS (SELECT 1 FROM tblProject p JOIN tblPullDownProjStatus s ON s.PullDownProjStatusID = p.ProjStatusID WHERE p.CustomerID = c.CustomerID AND s.PullDownProjStatus = 'Active')"
        assert search.search_customers(db, {"has_active_projects": True}, [], 1, PAGE).total == scalar(db, active.format(neg=""))
        assert search.search_customers(db, {"has_active_projects": False}, [], 1, PAGE).total == scalar(db, active.format(neg="NOT"))

        assert search.search_projects(db, {"state": "MA", "manned": False}, [], 1, PAGE).total == scalar(db, "SELECT COUNT(*) FROM tblProject WHERE SiteState='MA' AND JobBeingManned=0")
        assert search.search_projects(db, {"zip": "04", "ocip": True}, [], 1, PAGE).total == scalar(db, "SELECT COUNT(*) FROM tblProject WHERE SiteZip LIKE '04%' AND OCIPJob=1")


def test_keyword_search_runs_in_the_database(big):
    with big["Session"]() as db:
        res = search.search_employees(db, {}, ["sullivan"], 1, PAGE, strict_keywords=True)
        assert res.total == scalar(db, "SELECT COUNT(*) FROM tblEmployee WHERE EmployeeDuplicate = 0 AND (EmLastName LIKE '%sullivan%' OR EmFirstName LIKE '%sullivan%' "
                                       "OR EmEmail LIKE '%sullivan%' OR EmCity LIKE '%sullivan%' OR EmAdminNotes LIKE '%sullivan%' OR EmSalesNotes LIKE '%sullivan%')")
        assert all("sullivan" in (i["full_name"] + (i["EmEmail"] or "")).lower() for i in res.items)
        assert all(i["reasons"] for i in res.items)

        # two words: people matching both come first
        res = search.search_employees(db, {}, ["maria", "garcia"], 1, PAGE, strict_keywords=True)
        assert res.items[0]["full_name"].lower() == "maria garcia"
        both = [i for i in res.items if i["full_name"].lower() == "maria garcia"]
        assert len(both) == min(PAGE, scalar(db, "SELECT COUNT(*) FROM tblEmployee WHERE EmployeeDuplicate=0 AND EmFirstName='Maria' AND EmLastName='Garcia'"))

        # phone in any format
        emp = db.execute(select(m.Employee).where(m.Employee.EmployeeDuplicate == False, m.Employee.EmMobilePhone.isnot(None)).limit(1)).scalar_one()  # noqa: E712
        digits = "".join(ch for ch in emp.EmMobilePhone if ch.isdigit())
        for q in (digits, emp.EmMobilePhone, f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"):
            got = search.search_employees(db, {}, q.split(), 1, PAGE, strict_keywords=True)
            assert emp.EmployeeID in [i["EmployeeID"] for i in got.items], q

        # LIKE wildcards typed by a user are treated as plain text
        assert search.search_employees(db, {}, ["%"], 1, PAGE, strict_keywords=True).total == 0
        assert search.search_employees(db, {}, ["zzqx_notaname"], 1, PAGE, strict_keywords=True).total == 0
        # AI search keeps the filtered set when its leftover words match nothing
        assert search.search_employees(db, {"state": "MA"}, ["zzqxnotaword"], 1, PAGE, strict_keywords=False).total > 1000

        cust = search.search_customers(db, {}, ["harbor", "electric"], 1, PAGE, strict_keywords=True)
        assert cust.total > PAGE and "harbor" in cust.items[0]["CustBusName"].lower() and "electric" in cust.items[0]["CustBusName"].lower()
        jobs = search.search_projects(db, {}, ["medical"], 1, PAGE, strict_keywords=True)
        assert jobs.total == scalar(db, "SELECT COUNT(*) FROM tblProject WHERE SiteName LIKE '%medical%'") and all("medical" in i["SiteName"].lower() for i in jobs.items)


def test_natural_language_and_trade_synonyms_still_work(big):
    with big["Session"]() as db:
        for question, trade in (("pipe fitters in Providence with 10+ years", "Pipefitter"), ("sparkies in Boston", None), ("licensed electricians in Boston who will travel", "Electrician"),
                                ("sheet metal workers in zip 02118", "Sheet Metal Worker")):
            intent = heuristic_interpret("employees", question, search.vocab(db, "employees", question))
            if trade:
                assert intent.filters.get("trade") == trade, question
                res = search.search_employees(db, intent.filters, intent.keywords, 1, PAGE, with_facets=True)
                assert all(trade in " / ".join(i["reasons"]) or i["trade_name"] == trade for i in res.items), question
        intent = heuristic_interpret("employees", "electricians in zip 02118", search.vocab(db))
        assert intent.filters["zip"] == "02118" and intent.filters["trade"] == "Electrician" and "02118" not in intent.keywords
        assert "zip" not in heuristic_interpret("customers", "customers with revenue over 50000", search.vocab(db)).filters

        # a customer named in a job question is found with one bounded query, not by loading every customer
        name = db.execute(select(m.Customer.CustBusName).where(func.length(m.Customer.CustBusName) > 12).limit(1)).scalar_one()
        with Meter(big["engine"]) as meter:
            v = search.vocab(db, "projects", f"active jobs for {name.lower()}")
        assert name in v["customers"] and len(v["customers"]) <= 3 and meter.statements <= 4


def test_facet_counts_are_exact_and_first_page_only(big, client, admin_headers):
    with big["Session"]() as db:
        res = search.search_employees(db, {"state": "MA"}, [], 1, PAGE, with_facets=True)
        trade = next(f for f in res.facets if f["key"] == "trade")
        top = trade["values"][0]
        assert top["count"] == scalar(db, "SELECT COUNT(*) FROM tblEmployee e JOIN tblPullDownTrade t ON t.PullDownTradeID = e.EmTradeID "
                                          "WHERE e.EmState='MA' AND e.EmployeeDuplicate=0 AND t.PullDownTrade = :t", t=top["value"])
        assert len(trade["values"]) <= search.FACET_VALUES
        assert not any(f["key"] == "state" for f in res.facets)  # already filtered: not counted again
        assert search.search_employees(db, {"state": "MA"}, [], 1, PAGE).facets == []
    first = client.post("/api/search", json={"entity": "employees", "query": "electricians", "page": 1}, headers=admin_headers).json()
    assert client.post("/api/search", json={"entity": "employees", "filters": first["ai"]["filters"], "keywords": [], "page": 2}, headers=admin_headers).json()["facets"] in ([], None)


def test_counts_cache_is_off_in_demo_and_scoped_when_on(big, monkeypatch):
    assert settings.search_cache_ttl == 0
    monkeypatch.setattr(settings, "search_cache_seconds", 30)
    search.clear_result_cache()
    with big["Session"]() as db:
        with Meter(big["engine"]) as a:
            one = search.search_employees(db, {"state": "NH"}, [], 1, PAGE, with_facets=True)
        with Meter(big["engine"]) as b:
            two = search.search_employees(db, {"state": "NH"}, [], 1, PAGE, with_facets=True)
        assert one.facets == two.facets and b.statements < a.statements          # filter counts reused
        assert [i["EmployeeID"] for i in one.items] == [i["EmployeeID"] for i in two.items]  # records always read fresh
        assert search.search_employees(db, {"state": "CT"}, [], 1, PAGE, with_facets=True).facets != one.facets
    search.clear_result_cache()


# ---------------------------------------------------------------- tracking
def test_tracking_list_filters_and_pages_in_the_database(big):
    week = week_ending(date.today())
    with big["Session"]() as db, Meter(big["engine"]) as meter:
        rows, total = search.search_tracking(db, week, None, None, None, None, 1, PAGE)
        assert total == scalar(db, "SELECT COUNT(*) FROM tblTracking WHERE WeekEndingDate = :w", w=week.isoformat()) and len(rows) == min(PAGE, total)
        assert meter.records <= PAGE * 4 and meter.statements <= 8
        rows, total = search.search_tracking(db, None, None, None, None, "smith", 1, PAGE)
        assert total > 0 and all("smith" in (t.employee.full_name + t.customer.CustBusName + t.project.SiteName).lower() for t in rows)
        assert [t.WeekEndingDate for t in rows] == sorted((t.WeekEndingDate for t in rows), reverse=True)
        rows, _ = search.search_tracking(db, None, None, None, None, None, 1, 100_000)
        assert len(rows) == search.TRACKING_MAX_PAGE_SIZE


# ---------------------------------------------------------------- concurrency
def test_35_people_searching_at_once(big):
    Session = big["Session"]
    jobs = [
        lambda db: search.search_employees(db, {}, ["sullivan"], 1, PAGE, strict_keywords=True),
        lambda db: search.search_employees(db, {"trade": "Electrician", "state": "MA"}, [], 1, PAGE, with_facets=True),
        lambda db: search.search_employees(db, {"zip": "021"}, [], 2, PAGE, sort="name"),
        lambda db: search.search_customers(db, {}, ["harbor"], 1, PAGE, strict_keywords=True),
        lambda db: search.search_customers(db, {"has_active_projects": True, "state": "MA"}, [], 1, PAGE),
        lambda db: search.search_projects(db, {"manned": False}, ["medical"], 1, PAGE),
        lambda db: search.search_tracking(db, week_ending(date.today()), None, None, None, None, 1, PAGE),
    ]

    def signature(res):
        if isinstance(res, tuple):
            return (res[1], tuple(t.TrackingID for t in res[0]))
        return (res.total, tuple(next(iter(i.values())) for i in res.items))

    with Session() as db:
        expected = [signature(fn(db)) for fn in jobs]

    results: list[tuple[int, tuple]] = []
    errors: list[str] = []
    lock = threading.Lock()

    def person(n: int):
        for k in range(4):
            idx = (n + k) % len(jobs)
            try:
                with Session() as db:
                    sig = signature(jobs[idx](db))
                with lock:
                    results.append((idx, sig))
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}")

    with Meter(big["engine"]) as meter:
        t0 = time.perf_counter()
        threads = [threading.Thread(target=person, args=(i,)) for i in range(35)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        seconds = time.perf_counter() - t0
    assert errors == []
    assert len(results) == 35 * 4
    assert all(sig == expected[idx] for idx, sig in results)     # everyone got the same, correct answer
    assert meter.records <= 35 * 4 * PAGE * 4                    # nobody pulled a whole table into memory
    assert seconds < 120


def test_too_many_simultaneous_searches_get_a_clear_answer(big, monkeypatch):
    monkeypatch.setattr(search, "_search_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(settings, "search_wait_seconds", 1)
    held = search.search_slot()
    held.__enter__()
    try:
        with big["Session"]() as db, pytest.raises(Exception) as e:
            search.search_employees(db, {}, [], 1, PAGE)
        assert e.value.status_code == 503 and "try again" in e.value.detail
    finally:
        held.__exit__(None, None, None)
    with big["Session"]() as db:
        assert search.search_employees(db, {}, [], 1, PAGE).total > 0  # the slot was released


# ---------------------------------------------------------------- results are real records
def test_every_result_is_a_real_database_record(client, admin_headers, engine):
    for entity, table, pk, question in (("employees", "tblEmployee", "EmployeeID", "licensed electricians in Boston"), ("customers", "tblCustomer", "CustomerID", "active general contractors"),
                                        ("projects", "tblProject", "ProjectID", "active jobs that are not manned")):
        body = client.post("/api/search", json={"entity": entity, "query": question}, headers=admin_headers).json()
        ids = [i[pk] for i in body["items"]]
        assert ids and body["total"] >= len(ids)
        with engine.connect() as conn:
            found = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {pk} IN ({','.join(str(int(i)) for i in ids)})")).scalar_one()
        assert found == len(set(ids)), entity
        assert body["ai"]["mode"] in ("heuristic", "manual")  # the question was turned into filters; the rows came from the database
