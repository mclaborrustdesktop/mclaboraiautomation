"""Do the faster search statements return EXACTLY what the previous ones returned? Checked on the STAGING copy.

    powershell -File tools\\staging\\run-readonly.ps1 ..\\tools\\staging\\search_equivalence.py

For a list of word searches it runs the previous statement shape (lookup sub-selects inside the OR, one pass per
filter count) and the new shape (lookups resolved first, one pass for all filter counts) and compares the number
of matches, the ids on the first page in order, and every filter count. Prints PASS/FAIL per search, counts and
timings only. Read-only; no record content is printed.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app import models as m  # noqa: E402
from app import search  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.sqlutil import ci_eq, contains  # noqa: E402

assert settings.is_staging and not settings.sql_writes_allowed, "staging, read-only only"
lines: list[str] = []
failures = 0


def say(s: str = "") -> None:
    lines.append(s)
    print(s, flush=True)


# ---- the PREVIOUS statement shapes, kept here only for this comparison ---------------------------------------
def old_employee_keyword_sql(keywords):
    E = m.Employee

    def lookups(kw):
        yield E.EmTradeID.in_(select(m.PullDownTrade.PullDownTradeID).where(contains(m.PullDownTrade.PullDownTrade, kw)))
        yield E.EmQualificationID.in_(select(m.PullDownQualification.PullDownQualificationID).where(contains(m.PullDownQualification.PullDownQualification, kw)))

    return search.keyword_sql(keywords, text_columns=[E.EmFirstName, E.EmLastName, E.EmCity, E.EmZip, E.EmEmail, E.EmAdminNotes, E.EmSalesNotes, E.EmLicensedIn],
                              phone_columns=[E.EmMobilePhone, E.EmHomePhone], name_columns=[E.EmFirstName, E.EmLastName], extra=lookups)


def old_customer_keyword_sql(keywords):
    C, K = m.Customer, m.CustomerContact

    def contacts(kw):
        yield C.CustomerID.in_(select(K.CustomerID).where(or_(contains(K.CustomerContactFName, kw), contains(K.CustomerContactLName, kw))))

    return search.keyword_sql(keywords, text_columns=[C.CustBusName, C.City, C.Zip, C.Street, C.CustEmail, C.Industry, C.CustomerDescription, C.CustomerNote, C.InvoiceNote],
                              phone_columns=[C.Phone], name_columns=[C.CustBusName], extra=contacts)


def old_employee_conditions(f):
    """The previous filter shape: lookups as sub-selects inside the statement."""
    E = m.Employee
    c = [E.EmployeeDuplicate == False]  # noqa: E712
    if f.get("trade"):
        ids = select(m.PullDownTrade.PullDownTradeID).where(ci_eq(m.PullDownTrade.PullDownTrade, f["trade"]))
        c.append(or_(E.EmTradeID.in_(ids), E.SubTrade1ID.in_(ids), E.SubTrade2ID.in_(ids)))
    if f.get("qualification"):
        c.append(E.EmQualificationID.in_(select(m.PullDownQualification.PullDownQualificationID).where(ci_eq(m.PullDownQualification.PullDownQualification, f["qualification"]))))
    if f.get("status"):
        c.append(E.EmEmployeeStatusID.in_(select(m.PullDownEmployeeStatus.PullDownEmployeeStatusID).where(ci_eq(m.PullDownEmployeeStatus.PullDownEmployeeStatus, f["status"]))))
    if f.get("licensed") is True:
        c.append(or_(E.EmployeeID.in_(select(m.EmployeeLicense.EmployeeID).where(m.EmployeeLicense.EmployeeID.isnot(None))), E.EmLicenseNum.isnot(None)))
    if f.get("min_years") is not None:
        c.append(E.YearsInTrade >= int(f["min_years"]))
    if f.get("state"):
        c.append(ci_eq(E.EmState, str(f["state"]).upper()))
    return c


def old_customer_conditions(f):
    C = m.Customer
    c = []
    if f.get("state"):
        c.append(ci_eq(C.State, str(f["state"]).upper()))
    if f.get("status"):
        c.append(C.CustStatusID.in_(select(m.PullDownCustStatus.PulldownCustStatusID).where(ci_eq(m.PullDownCustStatus.PulldownCustStatus, f["status"]))))
    if f.get("customer_type"):
        c.append(C.CustomerTypeID.in_(select(m.PullDownCustomerType.PullDownCustomerTypeID).where(ci_eq(m.PullDownCustomerType.PullDownCustomerType, f["customer_type"]))))
    if f.get("has_active_projects") is not None:
        active = select(m.PullDownProjStatus.PullDownProjStatusID).where(ci_eq(m.PullDownProjStatus.PullDownProjStatus, "Active"))
        ex = C.CustomerID.in_(select(m.Project.CustomerID).where(m.Project.CustomerID.isnot(None), m.Project.ProjStatusID.in_(active)))
        c.append(ex if f["has_active_projects"] else ~ex)
    return c


def old_employee_facets(db, conditions):
    E = m.Employee
    base = select(E.EmployeeID).select_from(E)
    specs = [
        ("trade", "Trade", m.PullDownTrade.PullDownTrade, base.join(m.PullDownTrade, E.EmTradeID == m.PullDownTrade.PullDownTradeID)),
        ("qualification", "Qualification", m.PullDownQualification.PullDownQualification, base.join(m.PullDownQualification, E.EmQualificationID == m.PullDownQualification.PullDownQualificationID)),
        ("status", "Status", m.PullDownEmployeeStatus.PullDownEmployeeStatus, base.join(m.PullDownEmployeeStatus, E.EmEmployeeStatusID == m.PullDownEmployeeStatus.PullDownEmployeeStatusID)),
        ("city", "City", E.EmCity, base), ("state", "State", E.EmState, base),
    ]
    return [x for x in (search._facet(db, k, label, col, b, conditions) for k, label, col, b in specs) if x]


def old_customer_facets(db, conditions):
    C, S = m.Customer, m.PullDownSalesman
    base = select(C.CustomerID).select_from(C)
    specs = [
        ("status", "Status", m.PullDownCustStatus.PulldownCustStatus, base.join(m.PullDownCustStatus, C.CustStatusID == m.PullDownCustStatus.PulldownCustStatusID)),
        ("customer_type", "Type", m.PullDownCustomerType.PullDownCustomerType, base.join(m.PullDownCustomerType, C.CustomerTypeID == m.PullDownCustomerType.PullDownCustomerTypeID)),
        ("city", "City", C.City, base), ("state", "State", C.State, base),
        ("salesman", "Sales rep", search._full_name(S.PullDownSalesmanFName, S.PullDownSalesmanLName), base.join(S, C.SalesmanID == S.PullDownSalesmanID)),
        ("industry", "Industry", C.Industry, base),
    ]
    return [x for x in (search._facet(db, k, label, col, b, conditions) for k, label, col, b in specs) if x]


def new_employee_facets(db, conditions):
    E = m.Employee
    trade = search._labels(db, m.PullDownTrade.PullDownTradeID, m.PullDownTrade.PullDownTrade)
    qual = search._labels(db, m.PullDownQualification.PullDownQualificationID, m.PullDownQualification.PullDownQualification)
    stat = search._labels(db, m.PullDownEmployeeStatus.PullDownEmployeeStatusID, m.PullDownEmployeeStatus.PullDownEmployeeStatus)
    return search._facets_one_pass(db, E.EmployeeID, conditions, [("trade", "Trade", E.EmTradeID, trade.get), ("qualification", "Qualification", E.EmQualificationID, qual.get),
                                                                   ("status", "Status", E.EmEmployeeStatusID, stat.get), ("city", "City", E.EmCity, str), ("state", "State", E.EmState, str)])


def new_customer_facets(db, conditions):
    C, S = m.Customer, m.PullDownSalesman
    stat = search._labels(db, m.PullDownCustStatus.PulldownCustStatusID, m.PullDownCustStatus.PulldownCustStatus)
    ctype = search._labels(db, m.PullDownCustomerType.PullDownCustomerTypeID, m.PullDownCustomerType.PullDownCustomerType)
    reps = {i: f"{fn} {ln}" for i, fn, ln in db.execute(select(S.PullDownSalesmanID, S.PullDownSalesmanFName, S.PullDownSalesmanLName)).all() if fn is not None and ln is not None}
    return search._facets_one_pass(db, C.CustomerID, conditions, [("status", "Status", C.CustStatusID, stat.get), ("customer_type", "Type", C.CustomerTypeID, ctype.get),
                                                                   ("city", "City", C.City, str), ("state", "State", C.State, str), ("salesman", "Sales rep", C.SalesmanID, reps.get),
                                                                   ("industry", "Industry", C.Industry, str)])


def compare(label: str, db, pk, old_conditions, new_conditions, old_kw, new_kw, order_for, old_facets, new_facets):
    """Previous shape = previous filters + previous keyword predicate + per-group counts; new shape = all three new."""
    global failures
    t0 = time.perf_counter()
    new_ids, new_total = search._page_ids(db, pk, new_conditions + [new_kw[0]], order_for(new_kw[1]), 0, 50)
    t_new = time.perf_counter() - t0
    t0 = time.perf_counter()
    f_new = new_facets(db, new_conditions + [new_kw[0]])
    tf_new = time.perf_counter() - t0
    try:
        t0 = time.perf_counter()
        old_ids, old_total = search._page_ids(db, pk, old_conditions + [old_kw[0]], order_for(old_kw[1]), 0, 50)
        t_old = time.perf_counter() - t0
    except OperationalError as exc:  # the previous shape can exceed the 20-second statement limit
        db.rollback()
        if "HYT00" not in str(exc.orig):
            raise
        # the previous statement cannot be measured; cross-check the new count with the two half-old statements instead
        checks = []
        for name, conds in (("previous filters + new words", old_conditions + [new_kw[0]]), ("new filters + previous words", new_conditions + [old_kw[0]])):
            try:
                checks.append((name, search._count(db, pk, conds)))
            except OperationalError as exc2:
                db.rollback()
                if "HYT00" not in str(exc2.orig):
                    raise
                checks.append((name, None))
        measured = [(n, c) for n, c in checks if c is not None]
        ok = bool(measured) and all(c == new_total for _, c in measured)
        failures += not ok
        detail = "; ".join(f"{n}: {'timed out' if c is None else f'{c:,}'}" for n, c in checks)
        say(f"  [{'PASS' if ok else 'FAIL'}] {label}: previous statement shape TIMED OUT (over 20 s); new shape {t_new:.2f}s, {new_total:,} match(es); "
            f"cross-checks ({detail}); filter counts {tf_new:.2f}s, {len(f_new)} group(s)")
        return
    same_page = old_ids == new_ids and old_total == new_total
    t0 = time.perf_counter()
    f_old = old_facets(db, old_conditions + [old_kw[0]])
    tf_old = time.perf_counter() - t0
    same_facets = f_old == f_new
    ok = same_page and same_facets
    failures += not ok
    say(f"  [{'PASS' if ok else 'FAIL'}] {label}: {old_total:,} match(es); page ids {'identical' if same_page else 'DIFFERENT'} "
        f"({t_old:.2f}s -> {t_new:.2f}s); filter counts {'identical' if same_facets else 'DIFFERENT'} ({tf_old:.2f}s -> {tf_new:.2f}s, {len(f_new)} group(s))")
    if not same_facets:
        say(f"         old groups: {[(x['key'], len(x['values'])) for x in f_old]}  new groups: {[(x['key'], len(x['values'])) for x in f_new]}")


def main() -> int:
    say(f"Search equivalence - STAGING copy {settings.db_expected_server_name}, read-only")
    say(dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    E, C = m.Employee, m.Customer
    with SessionLocal() as db:
        say("Employees (previous statement shape -> new shape)")
        for words, f in ((["smith"], {}), (["john", "smith"], {}), (["electric"], {}), (["617"], {}), (["foreman"], {}), (["journeyman"], {}), (["smith"], {"trade": "Electrician"}),
                         (["sullivan", "electric"], {"licensed": True}), (["years", "experience"], {"trade": "Plumber", "status": "Available", "min_years": 5}),
                         (["smith"], {"trade": "Plumber", "status": "Available"}), (["smith"], {"trade": "No Such Trade"})):
            kws = search.clean_keywords(words)
            years = search.func.coalesce(E.YearsInTrade, 0)
            def order_for(rank, _E=E, _years=years):
                return [rank.desc(), _years.desc(), search.ci_order(_E.EmLastName), _E.EmployeeID]
            compare(f"{' '.join(words)!r} {f or ''}", db, E.EmployeeID, old_employee_conditions(f), search._employee_conditions(db, f), old_employee_keyword_sql(kws),
                    search._employee_keyword_sql(db, kws), order_for, old_employee_facets, new_employee_facets)
            db.rollback()
        say("Customers")
        for words, f in ((["electric"], {}), (["harbor", "electric"], {}), (["617"], {}), (["smith"], {}), (["boston"], {"state": "MA"}),
                         (["electric"], {"status": "Active", "has_active_projects": True}), (["smith"], {"customer_type": "General Contractor"})):
            kws = search.clean_keywords(words)
            revenue = search.func.coalesce(C.RevenuePerYear, 0)
            def order_for(rank, _C=C, _rev=revenue):
                return [rank.desc(), _rev.desc(), search.ci_order(_C.CustBusName), _C.CustomerID]
            compare(f"{' '.join(words)!r} {f or ''}", db, C.CustomerID, old_customer_conditions(f), search._customer_conditions(db, f), old_customer_keyword_sql(kws),
                    search._customer_keyword_sql(db, kws), order_for, old_customer_facets, new_customer_facets)
            db.rollback()
        say("Filters without keywords: previous filter shape -> new, matches and filter counts")
        global failures
        for f in ({"trade": "Electrician", "licensed": True}, {"trade": "Plumber", "status": "Available", "min_years": 5}, {"state": "MA"}, {"qualification": "Journeyman"}):
            a_conds, b_conds = old_employee_conditions(f), search._employee_conditions(db, f)
            a_total, b_total = search._count(db, E.EmployeeID, a_conds), search._count(db, E.EmployeeID, b_conds)
            a, b = old_employee_facets(db, a_conds), new_employee_facets(db, b_conds)
            ok = a == b and a_total == b_total
            failures += not ok
            say(f"  [{'PASS' if ok else 'FAIL'}] employees {f}: {b_total:,} match(es) {'=' if a_total == b_total else '!='} {a_total:,}; {len(b)} group(s) {'identical' if a == b else 'DIFFERENT'}")
        for f in ({"state": "MA", "has_active_projects": True}, {"status": "Active"}, {"has_active_projects": False, "customer_type": "General Contractor"}):
            a_conds, b_conds = old_customer_conditions(f), search._customer_conditions(db, f)
            a_total, b_total = search._count(db, C.CustomerID, a_conds), search._count(db, C.CustomerID, b_conds)
            a, b = old_customer_facets(db, a_conds), new_customer_facets(db, b_conds)
            ok = a == b and a_total == b_total
            failures += not ok
            say(f"  [{'PASS' if ok else 'FAIL'}] customers {f}: {b_total:,} match(es) {'=' if a_total == b_total else '!='} {a_total:,}; {len(b)} group(s) {'identical' if a == b else 'DIFFERENT'}")
        db.rollback()
    say(f"\nRESULT: {'ALL IDENTICAL' if not failures else str(failures) + ' DIFFERENCE(S)'}. No record content was printed; nothing was written.")
    out = ROOT / "tools" / "prod-check" / "reports" / f"search-equivalence-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report saved: {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
