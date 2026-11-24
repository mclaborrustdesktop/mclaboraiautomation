"""STAGING read-only pilot: tests the RUNNING website (http://127.0.0.1:8000) against the restored copy.

    powershell -File tools\\staging\\run-in-staging.ps1 ..\\tools\\staging\\pilot.py

Prints and saves COUNTS, TIMINGS and PASS/FAIL only - never a name, phone number or any other record content.
It signs in with a 20-minute test token made on this PC (no password is created or stored), sends only GET
requests and searches, and sends a few change requests that MUST be refused. Exit code 1 = a critical test failed.
"""
import datetime as dt
import random
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
import jwt  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.production import build_sql_server_url  # noqa: E402

BASE = "http://127.0.0.1:8000"
SLOW = 3.0
lines: list[str] = []
critical = 0
warnings = 0
timings: list[tuple[str, float]] = []


def say(s: str = "") -> None:
    lines.append(s)
    print(s, flush=True)


def ok(s: str) -> None:
    say(f"  [ OK ] {s}")


def warn(s: str) -> None:
    global warnings
    warnings += 1
    say(f"  [WARN] {s}")


def fail(s: str) -> None:
    global critical
    critical += 1
    say(f"  [FAIL] {s}")


def scalar(sql: str, **p):
    with engine.connect() as c:
        v = c.execute(text(sql), p).scalar()
        c.rollback()
        return v


def call(client: httpx.Client, label: str, method: str, path: str, **kw):
    """One timed request. Returns (status, json-or-None, seconds)."""
    t0 = time.perf_counter()
    try:
        try:
            r = client.request(method, path, **kw)
        except (httpx.ReadError, httpx.RemoteProtocolError):  # the server closed the kept-open connection: ask once more
            t0 = time.perf_counter()
            r = client.request(method, path, **kw)
    except httpx.HTTPError as exc:
        fail(f"{label}: no answer ({type(exc).__name__})")
        return 0, None, time.perf_counter() - t0
    secs = time.perf_counter() - t0
    timings.append((label, secs))
    body = None
    if r.headers.get("content-type", "").startswith("application/json"):
        body = r.json()
    if r.status_code >= 500:
        fail(f"{label}: server error {r.status_code} ({secs:.2f}s)")
    return r.status_code, body, secs


def listing(client, label, path, params=None, expect=None, critical_mismatch=False):
    status, body, secs = call(client, label, "GET", path, params=params or {})
    if status != 200 or body is None:
        if status and status < 500:
            fail(f"{label}: HTTP {status}")
        return None
    total = body["total"]
    note = ""
    if expect is not None:
        if total == expect:
            note = f" = database count {expect:,}"
        else:
            note = f" BUT a direct database count gives {expect:,}"
            (fail if critical_mismatch else warn)(f"{label}: website {total:,}{note} ({secs:.2f}s)")
            return body
    (warn if secs > SLOW else ok)(f"{label}: {total:,} match(es), {len(body['items'])} on the page{note} ({secs:.2f}s)")
    return body


def open_many(client, noun, path, key, pages):
    """Opens many individual records (from several different pages) and counts the ones that fail to open."""
    ids = []
    for params in pages:
        status, body, _ = call(client, f"{noun}: collect ids", "GET", path, params={**params, "page_size": 40})
        if status == 200 and body:
            ids += [i[key] for i in body["items"]]
    ids = list(dict.fromkeys(ids))
    bad, secs = 0, []
    for i in ids:
        t0 = time.perf_counter()
        try:
            code = client.get(f"{path}/{i}").status_code
        except httpx.HTTPError:
            code = 0
        secs.append(time.perf_counter() - t0)
        bad += code != 200
    if not ids:
        fail(f"No {noun} records could be collected to open")
        return
    line = f"Opened {len(ids)} different {noun} records: {bad} failed; typical {statistics.median(secs):.2f}s, slowest {max(secs):.2f}s"
    (fail if bad else ok)(line)
    timings.append((f"slowest {noun} record", max(secs)))


def mostly_sorted(values, reverse=False) -> float:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return 1.0
    good = sum(1 for a, b in zip(vals, vals[1:]) if (a >= b if reverse else a <= b))
    return good / (len(vals) - 1)


def main() -> int:
    assert settings.is_staging and not settings.sql_writes_allowed, "staging, read-only only"
    say("MC Labor - STAGING read-only pilot")
    say(dt.datetime.now().strftime("%Y-%m-%d %H:%M") + f"   website {BASE}   database {settings.db_expected_server_name} / {settings.db_name}")

    # ---------------------------------------------------------------- 1
    say("\n1. Is the running website in STAGING and read-only?")
    anon = httpx.Client(base_url=BASE, timeout=40)
    status, health, _ = call(anon, "health", "GET", "/api/health")
    if not health or health.get("environment") != "staging" or health.get("database") != "sqlserver":
        fail(f"The website is not serving STAGING (it answered: {health}). Stopping.")
        return finish()
    ok(f"Website reports environment = staging, database = sqlserver, question parser = {health.get('ai_mode')} (nothing leaves this PC)")
    if health.get("ai_mode") != "heuristic":
        fail("An outside AI service is switched on. It must be off in staging.")
    status, _, _ = call(anon, "no sign-in", "GET", "/api/employees")
    (ok if status == 401 else fail)(f"Without signing in, the employee list answers {status} (expected 401)")

    # The test identity is the staff number given in WEB_ADMINS when the website was started for this pilot.
    admin_id = next((int(a) for a in settings.web_admin_set if a.isdigit()), None)
    if admin_id is None or scalar("SELECT COUNT(OfficeStaffID) FROM dbo.tblOfficeStaff WHERE OfficeStaffActive = 1 AND OfficeStaffID = :i", i=admin_id) != 1:
        fail("WEB_ADMINS does not name an active staff number to run the test as.")
        return finish()
    now = dt.datetime.now(dt.timezone.utc)
    token = jwt.encode({"sub": str(admin_id), "env": "staging", "iat": now, "exp": now + dt.timedelta(minutes=20)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    web = httpx.Client(base_url=BASE, timeout=40, headers={"Authorization": f"Bearer {token}"})

    status, sysinfo, _ = call(web, "system status", "GET", "/api/system/status")
    (ok if status == 200 else fail)(f"System status page answers {status}")
    status, _, secs = call(web, "dashboard", "GET", "/api/dashboard")
    (ok if status == 200 and secs <= SLOW else warn if status == 200 else fail)(f"Dashboard: HTTP {status} ({secs:.2f}s)")
    status, lookups, secs = call(web, "lookups", "GET", "/api/lookups")
    (ok if status == 200 else fail)(f"Drop-down lists: HTTP {status} ({secs:.2f}s)")

    # ---------------------------------------------------------------- 2
    say("\n2. Employees (filter, sort, pages) - website compared with a direct count in the database")
    trade_id = scalar("SELECT PullDownTradeID FROM dbo.tblPullDownTrade WHERE PullDownTrade = 'Electrician'")
    avail_id = scalar("SELECT PullDownEmployeeStatusID FROM dbo.tblPullDownEmployeeStatus WHERE PullDownEmployeeStatus = 'Available'")
    p1 = listing(web, "all employees, by name", "/api/employees", expect=scalar("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee WHERE EmployeeDuplicate = 0"), critical_mismatch=True)
    listing(web, "trade = Electrician", "/api/employees", {"trade_id": trade_id},
            expect=scalar("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee WHERE EmployeeDuplicate = 0 AND EmTradeID = :t", t=trade_id))
    listing(web, "status = Available", "/api/employees", {"status_id": avail_id},
            expect=scalar("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee WHERE EmployeeDuplicate = 0 AND EmEmployeeStatusID = :s", s=avail_id))
    listing(web, "trade = Electrician + status = Available", "/api/employees", {"trade_id": trade_id, "status_id": avail_id},
            expect=scalar("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee WHERE EmployeeDuplicate = 0 AND EmEmployeeStatusID = :s AND EmTradeID = :t", s=avail_id, t=trade_id))
    listing(web, "licensed only", "/api/employees", {"licensed": "true"})
    listing(web, "5+ years in trade", "/api/employees", {"min_years": 5})
    listing(web, "state = MA", "/api/employees", {"state": "MA"}, expect=scalar("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee WHERE EmployeeDuplicate = 0 AND EmState = 'MA'"))
    by_word = listing(web, "search box: a common last name", "/api/employees", {"q": "smith"})
    floor = scalar("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee WHERE EmployeeDuplicate = 0 AND EmLastName LIKE '%smith%'")
    if by_word is not None:
        (ok if by_word["total"] >= floor else fail)(f"    that search found at least everyone whose last name contains the word ({floor:,})")
    listing(web, "search box: first + last name", "/api/employees", {"q": "john smith"})
    listing(web, "search box: word in notes", "/api/employees", {"q": "foreman"})
    listing(web, "newest first", "/api/employees", {"sort": "newest"})
    listing(web, "most experienced first", "/api/employees", {"sort": "years"})
    p2 = listing(web, "page 2", "/api/employees", {"page": 2})
    listing(web, "page 100", "/api/employees", {"page": 100})
    big = listing(web, "200 per page (the maximum)", "/api/employees", {"page_size": 200})
    status, _, _ = call(web, "201 per page", "GET", "/api/employees", params={"page_size": 201})
    (ok if status == 422 else warn)(f"201 per page is refused (HTTP {status}, expected 422)")
    status, body, secs = call(web, "beyond 10,000 results", "GET", "/api/employees", params={"page": 300})
    (ok if status in (200, 400, 422) else warn)(f"Page 300 (past the 10,000-result window): HTTP {status} ({secs:.2f}s)")
    if p1 and p2:
        ids1, ids2 = [i["EmployeeID"] for i in p1["items"]], [i["EmployeeID"] for i in p2["items"]]
        (ok if len(ids1) == 50 and len(ids2) == 50 and not set(ids1) & set(ids2) else fail)(f"Pages 1 and 2 hold {len(ids1)} + {len(ids2)} different people, no one twice")
        if "EmLastName" in p1["items"][0]:
            share = mostly_sorted([(i.get("EmLastName") or "").lower() for i in p1["items"]])
            (ok if share >= 0.9 else warn)(f"Page 1 is in last-name order ({share:.0%} of neighbours in order)")
    if big:
        (ok if len(big["items"]) == 200 else fail)(f"200-per-page returned {len(big['items'])} rows")
    emp_id = p1["items"][0]["EmployeeID"] if p1 and p1["items"] else None
    if emp_id:
        status, rec, secs = call(web, "one employee record", "GET", f"/api/employees/{emp_id}")
        (ok if status == 200 else fail)(f"Opening one employee record: HTTP {status} ({secs:.2f}s)")
        if rec:
            leaked = [k for k in rec if k.lower() in ("emdob", "uscitizen", "i9complete", "ssnum", "bankaccountnumber", "bankroutingnumber") and rec[k] not in (None, "")]
            (fail if leaked else ok)("Restricted fields in that record: " + (", ".join(leaked) if leaked else "none (date of birth, SSN, bank, work-eligibility are absent)"))

    open_many(web, "employee", "/api/employees", "EmployeeID", [{}, {"page": 900}, {"sort": "newest"}, {"status_id": avail_id}, {"licensed": "true"}, {"min_years": 5}])

    # ---------------------------------------------------------------- 3
    say("\n3. Customers")
    c1 = listing(web, "all customers, by name", "/api/customers", expect=scalar("SELECT COUNT(CustomerID) FROM dbo.tblCustomer"), critical_mismatch=True)
    listing(web, "state = MA", "/api/customers", {"state": "MA"}, expect=scalar("SELECT COUNT(CustomerID) FROM dbo.tblCustomer WHERE State = 'MA'"))
    listing(web, "state = CT", "/api/customers", {"state": "CT"}, expect=scalar("SELECT COUNT(CustomerID) FROM dbo.tblCustomer WHERE State = 'CT'"))
    listing(web, "city = Boston", "/api/customers", {"city": "Boston"}, expect=scalar("SELECT COUNT(CustomerID) FROM dbo.tblCustomer WHERE City = 'Boston'"))
    listing(web, "ZIP starts 021", "/api/customers", {"zip": "021"})
    listing(web, "on hold", "/api/customers", {"on_hold": "true"})
    cw = listing(web, "search box: electric", "/api/customers", {"q": "electric"})
    floor = scalar("SELECT COUNT(CustomerID) FROM dbo.tblCustomer WHERE CustBusName LIKE '%electric%'")
    if cw is not None:
        (ok if cw["total"] >= floor else fail)(f"    that search found at least every customer whose name contains the word ({floor:,})")
    listing(web, "search box: phone area code 617", "/api/customers", {"q": "617"})
    listing(web, "newest first", "/api/customers", {"sort": "newest"})
    listing(web, "highest revenue first", "/api/customers", {"sort": "revenue"})
    c2 = listing(web, "page 2", "/api/customers", {"page": 2})
    if c1 and c2:
        a, b = [i["CustomerID"] for i in c1["items"]], [i["CustomerID"] for i in c2["items"]]
        (ok if len(a) == 50 and len(b) == 50 and not set(a) & set(b) else fail)(f"Pages 1 and 2 hold {len(a)} + {len(b)} different customers")
    if c1 and c1["items"]:
        status, _, secs = call(web, "one customer record", "GET", f"/api/customers/{c1['items'][0]['CustomerID']}")
        (ok if status == 200 else fail)(f"Opening one customer record: HTTP {status} ({secs:.2f}s)")

    open_many(web, "customer", "/api/customers", "CustomerID", [{}, {"page": 1500}, {"sort": "newest"}, {"sort": "revenue"}, {"state": "CT"}])

    # ---------------------------------------------------------------- 4
    say("\n4. Jobs")
    active_id = scalar("SELECT PullDownProjStatusID FROM dbo.tblPullDownProjStatus WHERE PullDownProjStatus = 'Active'")
    j1 = listing(web, "all jobs, newest start first", "/api/projects", expect=scalar("SELECT COUNT(ProjectID) FROM dbo.tblProject"), critical_mismatch=True)
    listing(web, "status = Active", "/api/projects", {"status_id": active_id}, expect=scalar("SELECT COUNT(ProjectID) FROM dbo.tblProject WHERE ProjStatusID = :s", s=active_id))
    listing(web, "state = MA", "/api/projects", {"state": "MA"}, expect=scalar(
        "SELECT COUNT(ProjectID) FROM dbo.tblProject p JOIN dbo.tblPullDownStateCities c ON c.PullDownStateCityID = p.SiteStateCityID "
        "JOIN dbo.tblPullDownStates s ON s.PullDownStateID = c.StateID WHERE s.PullDownState = 'MA'"))
    listing(web, "city = Boston", "/api/projects", {"city": "Boston"}, expect=scalar(
        "SELECT COUNT(ProjectID) FROM dbo.tblProject p JOIN dbo.tblPullDownStateCities c ON c.PullDownStateCityID = p.SiteStateCityID WHERE c.City = 'Boston'"))
    listing(web, "not being manned", "/api/projects", {"manned": "false"})
    listing(web, "search box: school", "/api/projects", {"q": "school"})
    listing(web, "by site name", "/api/projects", {"sort": "name"})
    j2 = listing(web, "page 2", "/api/projects", {"page": 2})
    if j1 and j2:
        a, b = [i["ProjectID"] for i in j1["items"]], [i["ProjectID"] for i in j2["items"]]
        (ok if not set(a) & set(b) else fail)(f"Pages 1 and 2 hold {len(a)} + {len(b)} different jobs")
        starts = [i.get("StartDate") for i in j1["items"]]
        share = mostly_sorted(starts, reverse=True)
        (ok if share >= 0.9 else warn)(f"Page 1 is in start-date order, newest first ({share:.0%})")
    if j1 and j1["items"]:
        pid, cid = j1["items"][0]["ProjectID"], j1["items"][0].get("CustomerID")
        status, _, secs = call(web, "one job record", "GET", f"/api/projects/{pid}")
        (ok if status == 200 else fail)(f"Opening one job record: HTTP {status} ({secs:.2f}s)")
        if cid:
            listing(web, "jobs of one customer", "/api/projects", {"customer_id": cid}, expect=scalar("SELECT COUNT(ProjectID) FROM dbo.tblProject WHERE CustomerID = :c", c=cid))

    open_many(web, "job", "/api/projects", "ProjectID", [{}, {"page": 200}, {"sort": "name"}, {"status_id": active_id}, {"manned": "false"}])

    # ---------------------------------------------------------------- 5
    say("\n5. Weekly tracking")
    status, weeks, secs = call(web, "list of weeks", "GET", "/api/tracking/weeks")
    (ok if status == 200 else fail)(f"List of weeks: HTTP {status} ({secs:.2f}s)")
    listing(web, "all tracking rows, first page", "/api/tracking", expect=scalar("SELECT COUNT(TrackingID) FROM dbo.tblTracking"))
    last_week = scalar("SELECT MAX(WeekEndingDate) FROM dbo.tblTracking WHERE WeekEndingDate <= '2026-11-13'")
    if last_week:
        d = str(last_week)[:10]
        t1 = listing(web, f"week ending {d}", "/api/tracking", {"week_ending_date": d, "page_size": 500},
                     expect=scalar("SELECT COUNT(TrackingID) FROM dbo.tblTracking WHERE CAST(WeekEndingDate AS date) = :d", d=d))
        if t1 and t1["items"]:
            eid = t1["items"][0].get("EmployeeID")
            if eid:
                listing(web, "one employee's tracking history", "/api/tracking", {"employee_id": eid},
                        expect=scalar("SELECT COUNT(TrackingID) FROM dbo.tblTracking WHERE EmployeeID = :e", e=eid))
        listing(web, f"week ending {d} + search word", "/api/tracking", {"week_ending_date": d, "q": "electric"})

    # ---------------------------------------------------------------- 6
    say("\n6. Plain-English questions (understood on this PC; only the filters are shown, no records)")
    questions = [
        ("employees", "licensed electricians"),
        ("employees", "available plumbers with 5+ years experience"),
        ("employees", "carpenters in MA who will travel"),
        ("employees", "pipe fitters with osha 10"),
        ("customers", "customers in MA with active jobs"),
        ("customers", "general contractors in CT"),
        ("customers", "customers on hold in Boston"),
        ("projects", "active jobs in MA not manned"),
        ("projects", "jobs in Hartford starting this month"),
    ]
    for entity, question in questions:
        status, body, secs = call(web, f"question: {question}", "POST", "/api/search", json={"entity": entity, "query": question})
        if status != 200 or not body:
            if 0 < status < 500:
                fail(f"\"{question}\": HTTP {status}")
            continue
        info = body["ai"]
        (warn if secs > SLOW else ok)(f"\"{question}\" -> {info['filters']} words {info['keywords']}: {body['total']:,} match(es), {len(body.get('facets') or [])} filter-count groups ({secs:.2f}s)")
    status, body, secs = call(web, "question, page 2", "POST", "/api/search", json={"entity": "employees", "query": "licensed electricians", "page": 2})
    if status == 200 and body:
        ok(f"\"licensed electricians\", page 2: {len(body['items'])} rows ({secs:.2f}s)")

    # ---------------------------------------------------------------- 7
    say("\n7. Changes must be impossible")
    for label, method, path, payload in (
        ("create an employee", "POST", "/api/employees", {"EmFirstName": "Pilot", "EmLastName": "Test"}),
        ("edit an employee", "PUT", f"/api/employees/{emp_id or 1}", {"EmFirstName": "Pilot"}),
        ("delete an employee", "DELETE", f"/api/employees/{emp_id or 1}", None),
        ("create a customer", "POST", "/api/customers", {"CustBusName": "Pilot Test"}),
        ("add a customer note", "POST", "/api/customers/1/notes", {"CustomerNote": "pilot"}),
        ("create a job", "POST", "/api/projects", {"SiteName": "Pilot"}),
        ("add tracking", "POST", "/api/tracking", {}),
        ("create a user", "POST", "/api/users", {}),
    ):
        status, body, _ = call(web, f"blocked: {label}", method, path, json=payload)
        (ok if status == 423 else fail)(f"Website refuses to {label}: HTTP {status} (expected 423 Read-only mode)")

    say("   Directly in SQL Server with the website's login, going AROUND the website's own safety check")
    say("   (each statement is written to affect zero rows, and is rolled back):")
    raw = create_engine(build_sql_server_url(), future=True)
    attempts = (
        ("UPDATE an employee", "UPDATE dbo.tblEmployee SET EmFirstName = EmFirstName WHERE 1 = 0"),
        ("DELETE a customer", "DELETE FROM dbo.tblCustomer WHERE 1 = 0"),
        ("INSERT a customer note", "INSERT INTO dbo.tblCustomerNotes (CustomerID, CustomerNote) SELECT CustomerID, CustomerNote FROM dbo.tblCustomerNotes WHERE 1 = 0"),
        ("UPDATE tracking hours", "UPDATE dbo.tblTracking SET TotalHours = TotalHours WHERE 1 = 0"),
        ("read SSN column", "SELECT TOP 0 SSNum FROM dbo.tblEmployee"),
        ("read bank account column", "SELECT TOP 0 BankAccountNumber FROM dbo.tblEmployee"),
        ("read date-of-birth column", "SELECT TOP 0 EmDOB FROM dbo.tblEmployee"),
        ("read staff password column", "SELECT TOP 0 OfficeStaffPassword FROM dbo.tblOfficeStaff"),
        ("read every employee column (SELECT *)", "SELECT TOP 0 * FROM dbo.tblEmployee"),
    )
    for label, sql in attempts:
        with raw.connect() as conn:
            try:
                conn.exec_driver_sql(sql)
                conn.rollback()
                fail(f"SQL Server ALLOWED: {label}")
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                msg = str(getattr(exc, "orig", exc))
                denied = "permission was denied" in msg or "(229)" in msg or "(230)" in msg or "read-only" in msg.lower() or "(3906)" in msg
                (ok if denied else warn)(f"SQL Server refuses to {label}" + ("" if denied else f" (unexpected reason: {msg[:120]})"))
    raw.dispose()
    before = scalar("SELECT COUNT(EmployeeID) FROM dbo.tblEmployee"), scalar("SELECT COUNT(CustomerID) FROM dbo.tblCustomer"), scalar("SELECT COUNT(ProjectID) FROM dbo.tblProject"), scalar("SELECT COUNT(TrackingID) FROM dbo.tblTracking")
    (ok if before == (178993, 106828, 15748, 192225) else warn)(f"Row counts after the test: employees {before[0]:,}, customers {before[1]:,}, jobs {before[2]:,}, tracking {before[3]:,} (same as before the pilot: 178,993 / 106,828 / 15,748 / 192,225)")

    # ---------------------------------------------------------------- 8
    say("\n8. 35 people searching at the same time (a search every 2 to 6 seconds, 6 searches each)")
    mix = [
        ("/api/employees", {}), ("/api/employees", {"trade_id": trade_id}), ("/api/employees", {"q": "smith"}), ("/api/employees", {"q": "john smith"}),
        ("/api/employees", {"status_id": avail_id}), ("/api/employees", {"page": 7}), ("/api/customers", {}), ("/api/customers", {"state": "MA"}),
        ("/api/customers", {"q": "electric"}), ("/api/projects", {}), ("/api/projects", {"status_id": active_id}), ("/api/tracking", {}),
    ]
    results: list[tuple[int, float]] = []
    lock = threading.Lock()

    def person(seed: int) -> None:
        rnd = random.Random(seed)
        with httpx.Client(base_url=BASE, timeout=60, headers={"Authorization": f"Bearer {token}"}) as c:
            time.sleep(rnd.uniform(0, 3))
            for _ in range(6):
                path, params = rnd.choice(mix)
                t0 = time.perf_counter()
                try:
                    code = c.get(path, params=params).status_code
                except httpx.HTTPError:
                    code = 0
                with lock:
                    results.append((code, time.perf_counter() - t0))
                time.sleep(rnd.uniform(2, 6))

    threads = [threading.Thread(target=person, args=(n,)) for n in range(35)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    secs = sorted(s for _, s in results)
    errors = sum(1 for code, _ in results if code != 200)
    busy = sum(1 for code, _ in results if code == 503)
    p95 = secs[int(len(secs) * 0.95) - 1]
    line = f"{len(results)} searches, {errors} not answered normally ({busy} 'busy, try again'); typical {statistics.median(secs):.2f}s, 95% within {p95:.2f}s, slowest {secs[-1]:.2f}s"
    (fail if errors > len(results) * 0.1 else warn if errors or p95 > 5 else ok)(line)

    return finish()


def finish() -> int:
    say("\nSlowest single requests")
    for label, secs in sorted(timings, key=lambda x: -x[1])[:8]:
        say(f"    {secs:6.2f}s  {label}")
    say("")
    say(f"RESULT: {'CRITICAL FAILURE - return to DEMO' if critical else 'PASSED'} - {critical} critical failure(s), {warnings} warning(s). No record content was printed; nothing was written.")
    out = ROOT / "tools" / "prod-check" / "reports" / f"staging-pilot-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report saved: {out}")
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
