"""WHY are word searches slow on SQL Server? Read-only diagnosis on the STAGING copy. Counts and timings only.

    powershell -File tools\\staging\\run-readonly.ps1 ..\\tools\\staging\\search_diag.py

1. Which indexes exist on the searched tables (metadata).
2. How wide the searched text columns are (nvarchar(max) is stored off-row and is slow to scan).
3. Whether this login may see execution plans (SHOWPLAN). Usually not - reported either way.
4. The same employee / customer word search written in several ways, each timed 3 times, to see which part
   of the current statement costs the time: the note columns, the ranking sort, the years-in-trade lookup,
   the phone-digit REPLACE chain, evaluating the match twice, or the plain scan itself.

Every statement goes through the engine's guard (SELECT only). No name, phone or note is ever fetched.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import bindparam, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402

assert settings.is_staging and not settings.sql_writes_allowed, "staging, read-only only"
lines: list[str] = []


def say(s: str = "") -> None:
    lines.append(s)
    print(s, flush=True)


def timed(conn, label: str, sql: str, params: dict | None = None, runs: int = 3) -> float | None:
    secs: list[float] = []
    n = None
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            rows = conn.execute(text(sql), params or {}).fetchall()
        except Exception as exc:  # noqa: BLE001
            say(f"    {label:70} FAILED: {str(getattr(exc, 'orig', exc)).splitlines()[0][:110]}")
            conn.rollback()
            return None
        secs.append(time.perf_counter() - t0)
        scalar = bool(rows) and len(rows[0]) == 1
        n = rows[0][0] if scalar else len(rows)
    med = statistics.median(secs)
    say(f"    {label:70} median {med:6.2f}s  fastest {min(secs):6.2f}s   ({n:,} {'match(es)' if scalar else 'row(s)'})")
    return med


EMP_TEXT = ["EmFirstName", "EmLastName", "EmCity", "EmZip", "EmEmail", "EmAdminNotes", "EmSalesNotes", "EmLicensedIn"]
EMP_PHONE = ["EmMobilePhone", "EmHomePhone"]
CUST_TEXT = ["CustBusName", "City", "Zip", "Street", "CustEmail", "Industry", "CustomerDescription", "CustomerNote", "InvoiceNote"]
CUST_PHONE = ["Phone"]
PUNCT = ["(", ")", "-", ".", " ", "+"]


def like(col: str, p: str) -> str:
    return f"{col} LIKE :{p} ESCAPE '\\'"


def digits(col: str) -> str:
    expr = col
    for ch in PUNCT:
        expr = f"REPLACE({expr}, '{ch}', '')"
    return expr


def emp_hit(p: str, cols_text=EMP_TEXT, cols_phone=EMP_PHONE, phone_digits=False, lookups=True) -> str:
    parts = [like(c, p) for c in cols_text + cols_phone]
    if phone_digits:
        parts += [f"{digits(c)} LIKE :{p}" for c in cols_phone]
    if lookups:
        parts.append(f"e.EmTradeID IN (SELECT t.PullDownTradeID FROM dbo.tblPullDownTrade t WHERE {like('t.PullDownTrade', p)})")
        parts.append(f"e.EmQualificationID IN (SELECT q.PullDownQualificationID FROM dbo.tblPullDownQualifications q WHERE {like('q.PullDownQualification', p)})")
    return "(" + " OR ".join(parts) + ")"


def emp_bonus(p: str) -> str:
    return f"(EmFirstName LIKE :{p}s ESCAPE '\\' OR EmFirstName LIKE :{p}w ESCAPE '\\' OR EmLastName LIKE :{p}s ESCAPE '\\' OR EmLastName LIKE :{p}w ESCAPE '\\')"


YEARS = "(SELECT TRY_CAST(LEFT(yit.PullDownYearsInTrade, PATINDEX('%[^0-9]%', yit.PullDownYearsInTrade + 'x') - 1) AS int) FROM dbo.tblPullDownYearsInTrade yit WHERE yit.PullDownYearsInTradeID = e.YearsInTradeID)"


def params_for(words: list[str]) -> dict:
    out = {}
    for i, w in enumerate(words):
        out[f"k{i}"] = f"%{w}%"
        out[f"k{i}s"] = f"{w}%"
        out[f"k{i}w"] = f"% {w}%"
    return out


def employee_variants(words: list[str]) -> list[tuple[str, str]]:
    ps = [f"k{i}" for i in range(len(words))]
    is_digits = all(re.fullmatch(r"\d+", w) for w in words)
    hits_full = [emp_hit(p, phone_digits=is_digits) for p in ps]
    hits_nonotes = [emp_hit(p, cols_text=[c for c in EMP_TEXT if "Notes" not in c], phone_digits=is_digits) for p in ps]
    hits_names = [emp_hit(p, cols_text=["EmFirstName", "EmLastName"], cols_phone=[], lookups=False) for p in ps]
    where_full = " OR ".join(hits_full)
    rank_full = " + ".join(f"CASE WHEN {h} THEN 1.0 ELSE 0.0 END + CASE WHEN {emp_bonus(p)} THEN 0.5 ELSE 0.0 END" for h, p in zip(hits_full, ps))
    page = "OFFSET 0 ROWS FETCH NEXT 50 ROWS ONLY"
    v = []
    v.append(("A  current shape: match in WHERE and again in rank, ORDER BY rank, years, name",
              f"SELECT e.EmployeeID, COUNT(e.EmployeeID) OVER() AS total FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({where_full}) "
              f"ORDER BY ({rank_full}) DESC, COALESCE({YEARS}, 0) DESC, e.EmLastName, e.EmployeeID {page}"))
    v.append(("B  A without the years-in-trade lookup in the sort",
              f"SELECT e.EmployeeID, COUNT(e.EmployeeID) OVER() AS total FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({where_full}) "
              f"ORDER BY ({rank_full}) DESC, e.EmLastName, e.EmployeeID {page}"))
    v.append(("C  A without any ranking (ORDER BY name only)",
              f"SELECT e.EmployeeID, COUNT(e.EmployeeID) OVER() AS total FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({where_full}) "
              f"ORDER BY e.EmLastName, e.EmployeeID {page}"))
    hit_cols = ", ".join(f"CASE WHEN {h} THEN 1 ELSE 0 END AS h{i}" for i, h in enumerate(hits_full))
    bonus_cols = ", ".join(f"CASE WHEN {emp_bonus(p)} THEN 1 ELSE 0 END AS b{i}" for i, p in enumerate(ps))
    rank_once = " + ".join(f"x.h{i} + 0.5 * x.b{i}" for i in range(len(ps)))
    any_hit = " OR ".join(f"x.h{i} = 1" for i in range(len(ps)))
    v.append(("D  match evaluated ONCE (CROSS APPLY), then filter + rank on the flags; years kept",
              f"SELECT e.EmployeeID, COUNT(e.EmployeeID) OVER() AS total FROM dbo.tblEmployee e CROSS APPLY (SELECT {hit_cols}, {bonus_cols}) x "
              f"WHERE e.EmployeeDuplicate = 0 AND ({any_hit}) ORDER BY ({rank_once}) DESC, COALESCE({YEARS}, 0) DESC, e.EmLastName, e.EmployeeID {page}"))
    v.append(("E  D with years-in-trade joined once instead of a per-row sub-select",
              f"SELECT e.EmployeeID, COUNT(e.EmployeeID) OVER() AS total FROM dbo.tblEmployee e "
              f"LEFT JOIN dbo.tblPullDownYearsInTrade yit ON yit.PullDownYearsInTradeID = e.YearsInTradeID "
              f"CROSS APPLY (SELECT {hit_cols}, {bonus_cols}) x WHERE e.EmployeeDuplicate = 0 AND ({any_hit}) "
              f"ORDER BY ({rank_once}) DESC, COALESCE(TRY_CAST(LEFT(yit.PullDownYearsInTrade, PATINDEX('%[^0-9]%', yit.PullDownYearsInTrade + 'x') - 1) AS int), 0) DESC, e.EmLastName, e.EmployeeID {page}"))
    v.append(("F  count only, full match (scan + predicate cost, no sort)",
              f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({where_full})"))
    v.append(("G  count only, without the two note columns",
              f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({' OR '.join(hits_nonotes)})"))
    v.append(("H  count only, first + last name columns only",
              f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({' OR '.join(hits_names)})"))
    if is_digits:
        v.append(("I  count only, full match but WITHOUT the phone REPLACE chain",
                  f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({' OR '.join(emp_hit(p, phone_digits=False) for p in ps)})"))
        v.append(("I2 count only, digits: REPLACE chain on phones but no plain LIKE on them (superset)",
                  f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ("
                  + " OR ".join("(" + " OR ".join([like(c, p) for c in EMP_TEXT] + [f"{digits(c)} LIKE :{p}" for c in EMP_PHONE]) + ")" for p in ps) + ")"))
    v.append(("K  count only, ONE non-indexed column (EmCity): the clustered-scan floor",
              f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({' OR '.join(like('EmCity', p) for p in ps)})"))
    v.append(("N  count only, full match without the trade/qualification lookup sub-selects",
              f"SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND ({' OR '.join(emp_hit(p, phone_digits=is_digits, lookups=False) for p in ps)})"))
    v.append(("D2 match evaluated once via a derived table (no CROSS APPLY), filter + rank on the flags",
              f"SELECT x.EmployeeID, COUNT(x.EmployeeID) OVER() AS total FROM (SELECT e.EmployeeID, e.EmLastName, e.YearsInTradeID, {hit_cols}, {bonus_cols} "
              f"FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0) x WHERE ({any_hit}) "
              f"ORDER BY ({rank_once}) DESC, COALESCE((SELECT TRY_CAST(LEFT(yit.PullDownYearsInTrade, PATINDEX('%[^0-9]%', yit.PullDownYearsInTrade + 'x') - 1) AS int) "
              f"FROM dbo.tblPullDownYearsInTrade yit WHERE yit.PullDownYearsInTradeID = x.YearsInTradeID), 0) DESC, x.EmLastName, x.EmployeeID {page}"))
    return v


def customer_variants(words: list[str]) -> list[tuple[str, str]]:
    ps = [f"k{i}" for i in range(len(words))]
    is_digits = all(re.fullmatch(r"\d+", w) for w in words)

    def hit(p, cols=CUST_TEXT, phone_digits=is_digits, contacts=True):
        parts = [like(c, p) for c in cols + CUST_PHONE]
        if phone_digits:
            parts += [f"{digits(c)} LIKE :{p}" for c in CUST_PHONE]
        if contacts:
            parts.append(f"c.CustomerID IN (SELECT k.CustomerID FROM dbo.tblCustomerContacts k WHERE {like('k.CustomerContactFName', p)} OR {like('k.CustomerContactLName', p)})")
        return "(" + " OR ".join(parts) + ")"

    v = [("F  count only, full match", f"SELECT COUNT(c.CustomerID) FROM dbo.tblCustomer c WHERE {' OR '.join(hit(p) for p in ps)}"),
         ("G  count only, without the three note/description columns",
          f"SELECT COUNT(c.CustomerID) FROM dbo.tblCustomer c WHERE {' OR '.join(hit(p, cols=[c for c in CUST_TEXT if c not in ('CustomerDescription', 'CustomerNote', 'InvoiceNote')]) for p in ps)}"),
         ("J  count only, without the contact-name sub-select", f"SELECT COUNT(c.CustomerID) FROM dbo.tblCustomer c WHERE {' OR '.join(hit(p, contacts=False) for p in ps)}"),
         ("H  count only, business name column only", f"SELECT COUNT(c.CustomerID) FROM dbo.tblCustomer c WHERE {' OR '.join(like('CustBusName', p) for p in ps)}")]
    if is_digits:
        v.append(("I  count only, full match but WITHOUT the phone REPLACE chain", f"SELECT COUNT(c.CustomerID) FROM dbo.tblCustomer c WHERE {' OR '.join(hit(p, phone_digits=False) for p in ps)}"))
    contact_where = " OR ".join(f"({like('k.CustomerContactFName', p)} OR {like('k.CustomerContactLName', p)})" for p in ps)
    v.append(("K1 contact names alone: distinct customer ids from tblCustomerContacts", f"SELECT COUNT(DISTINCT k.CustomerID) FROM dbo.tblCustomerContacts k WHERE {contact_where}"))
    v.append(("K2 full match, contacts as a correlated EXISTS instead of IN",
              f"SELECT COUNT(c.CustomerID) FROM dbo.tblCustomer c WHERE " + " OR ".join(
                  "(" + " OR ".join([like(x, p) for x in CUST_TEXT + CUST_PHONE] + ([f"{digits(x)} LIKE :{p}" for x in CUST_PHONE] if is_digits else [])
                                    + [f"EXISTS (SELECT 1 FROM dbo.tblCustomerContacts k WHERE k.CustomerID = c.CustomerID AND ({like('k.CustomerContactFName', p)} OR {like('k.CustomerContactLName', p)}))"]) + ")" for p in ps)))
    v.append(("K3 full match as a UNION: customer columns, then contact matches, counted once",
              f"SELECT COUNT(u.CustomerID) FROM (SELECT c.CustomerID FROM dbo.tblCustomer c WHERE {' OR '.join(hit(p, contacts=False) for p in ps)} "
              f"UNION SELECT k.CustomerID FROM dbo.tblCustomerContacts k WHERE {contact_where}) u"))
    return v


def main() -> int:
    say(f"Search diagnosis - STAGING copy {settings.db_expected_server_name}, read-only")
    say(dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    with engine.connect() as conn:
        say("\n1. Indexes on the searched tables (metadata)")
        try:
            rows = conn.execute(text(
                "SELECT t.name, i.name, i.type_desc, i.is_unique, i.is_primary_key, "
                "STUFF((SELECT ', ' + c.name FROM sys.index_columns ic JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
                "WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 0 ORDER BY ic.key_ordinal FOR XML PATH('')), 1, 2, ''), "
                "STUFF((SELECT ', ' + c.name FROM sys.index_columns ic JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
                "WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 1 ORDER BY c.name FOR XML PATH('')), 1, 2, '') "
                "FROM sys.tables t JOIN sys.indexes i ON i.object_id = t.object_id AND i.type > 0 "
                "WHERE t.name IN ('tblEmployee', 'tblEmployeeB', 'tblEmployeeLicenses', 'tblCustomer', 'tblCustomerContacts', 'tblProject', 'tblTracking', 'tblPullDownStateCities', 'tblPullDownTrade') "
                "ORDER BY t.name, i.index_id")).fetchall()
            for t, name, kind, uniq, pk, keys, incl in rows:
                say(f"    {t:24} {kind:14} {'PK ' if pk else '   '}{'unique ' if uniq else '       '}{name or '?':40} keys: {keys or '-'}" + (f"   includes: {incl}" if incl else ""))
            say(f"    ({len(rows)} index(es) visible to this login)")
        except Exception as exc:  # noqa: BLE001
            say(f"    not visible: {str(getattr(exc, 'orig', exc)).splitlines()[0][:120]}")
            conn.rollback()
        try:
            rows = conn.execute(text(
                "SELECT t.name, SUM(CASE WHEN p.index_id IN (0, 1) THEN p.row_count ELSE 0 END), CAST(SUM(p.reserved_page_count) * 8 / 1024.0 AS decimal(12, 1)), "
                "CAST(SUM(CASE WHEN p.index_id IN (0, 1) THEN p.lob_reserved_page_count ELSE 0 END) * 8 / 1024.0 AS decimal(12, 1)) "
                "FROM sys.tables t JOIN sys.dm_db_partition_stats p ON p.object_id = t.object_id "
                "WHERE t.name IN ('tblEmployee', 'tblEmployeeB', 'tblCustomer', 'tblCustomerContacts', 'tblProject', 'tblTracking') GROUP BY t.name ORDER BY 3 DESC")).fetchall()
            for t, n, mb, lob in rows:
                say(f"    {t:24} {n:>9,} rows  {mb:>8} MB in total, of which {lob} MB off-row text (LOB)")
        except Exception as exc:  # noqa: BLE001
            say(f"    table sizes not visible to this login ({str(getattr(exc, 'orig', exc)).splitlines()[0][:80]})")
            conn.rollback()

        say("\n2. Width of the text columns the word search reads (-1 = nvarchar(max), stored off-row)")
        cols = {"tblEmployee": EMP_TEXT + EMP_PHONE, "tblCustomer": CUST_TEXT + CUST_PHONE,
                "tblProject": ["SiteName", "SiteStreet", "SiteZip", "ProjNote", "JobNote", "ProjOfficeNote", "CustomerContact", "CustomerPhone"]}
        for table, names in cols.items():
            rows = conn.execute(text("SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = :t AND COLUMN_NAME IN :c")
                                .bindparams(bindparam("c", expanding=True)), {"t": table, "c": list(names)}).fetchall()
            say(f"    {table}: " + ", ".join(f"{c} {ty}({'max' if ln == -1 else ln})" for c, ty, ln in rows))

        say("\n3. Timings - the SAME word search written in different ways (median of 3, fastest)")
        for words in (["smith"], ["john", "smith"], ["617"], ["electric"]):
            say(f"  Employees, {'words' if len(words) > 1 else 'word'} {' '.join(words)!r}:")
            for label, sql in employee_variants(words):
                timed(conn, label, sql, params_for(words))
            conn.rollback()
        for words in (["electric"], ["617"]):
            say(f"  Customers, word {words[0]!r}:")
            for label, sql in customer_variants(words):
                timed(conn, label, sql, params_for(words))
            conn.rollback()

        say("\n4. The filter-count (facet) passes of the AI search page")
        timed(conn, "one facet pass, e.g. trade counts for 'electricians' (current: 5 such passes)",
              "SELECT t.PullDownTrade, COUNT(e.EmployeeID) FROM dbo.tblEmployee e JOIN dbo.tblPullDownTrade t ON t.PullDownTradeID = e.EmTradeID "
              "WHERE e.EmployeeDuplicate = 0 AND (e.EmTradeID IN (SELECT PullDownTradeID FROM dbo.tblPullDownTrade WHERE PullDownTrade = 'Electrician') "
              "OR e.SubTrade1ID IN (SELECT PullDownTradeID FROM dbo.tblPullDownTrade WHERE PullDownTrade = 'Electrician') OR e.SubTrade2ID IN (SELECT PullDownTradeID FROM dbo.tblPullDownTrade WHERE PullDownTrade = 'Electrician')) "
              "GROUP BY t.PullDownTrade")
        timed(conn, "all five facets in ONE pass (GROUPING SETS on the ids)",
              "SELECT e.EmTradeID, e.EmQualificationID, e.EmEmployeeStatusID, e.EmCity, e.EmState, COUNT(e.EmployeeID) FROM dbo.tblEmployee e "
              "WHERE e.EmployeeDuplicate = 0 AND (e.EmTradeID IN (SELECT PullDownTradeID FROM dbo.tblPullDownTrade WHERE PullDownTrade = 'Electrician') "
              "OR e.SubTrade1ID IN (SELECT PullDownTradeID FROM dbo.tblPullDownTrade WHERE PullDownTrade = 'Electrician') OR e.SubTrade2ID IN (SELECT PullDownTradeID FROM dbo.tblPullDownTrade WHERE PullDownTrade = 'Electrician')) "
              "GROUP BY GROUPING SETS ((e.EmTradeID), (e.EmQualificationID), (e.EmEmployeeStatusID), (e.EmCity), (e.EmState))")
        conn.rollback()

    say("\n5. Execution plans (own connection: SHOWPLAN mode must never leak into other statements)")
    with engine.connect() as conn:
        try:
            conn.exec_driver_sql("SET SHOWPLAN_XML ON")
            try:
                plan = conn.exec_driver_sql("SELECT COUNT(e.EmployeeID) FROM dbo.tblEmployee e WHERE e.EmployeeDuplicate = 0 AND e.EmLastName LIKE '%smith%'").fetchall()
            finally:
                conn.exec_driver_sql("SET SHOWPLAN_XML OFF")
            xml = plan[0][0] if plan else ""
            ops = re.findall(r'PhysicalOp="([^"]+)"', xml)
            idx = re.findall(r'Index="\[([^\]]+)\]"', xml)
            say(f"    SHOWPLAN is allowed. Last-name search plan: operators {sorted(set(ops))}, indexes used {sorted(set(idx))}")
        except Exception as exc:  # noqa: BLE001
            say(f"    not available to this login (expected): {str(getattr(exc, 'orig', exc)).splitlines()[0][:110]}")
        conn.rollback()
    say("\nNo record content was printed; nothing was written.")
    out = ROOT / "tools" / "prod-check" / "reports" / f"search-diag-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
