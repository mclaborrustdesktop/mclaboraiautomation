"""A synthetic McLabor-SHAPED database for a cloud staging rehearsal with NO real records.

    .venv\\Scripts\\python.exe -m app.synthdb "mssql+pyodbc://user:pw@vm-name,1433/McLaborSynthetic?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes" [scale]
    .venv\\Scripts\\python.exe -m app.synthdb "sqlite:///C:/temp/synthetic.db" 0.05

Creates the 33 tables the website uses (`tools/prod-check/required_schema.json`) with every approved column, in the
PRODUCTION shape (YearsInTradeID, tblEmployeeB.WillTravel, SiteStateCityID - not the demo's convenience columns),
with the column types of the client's schema export, the real primary keys and foreign keys, plus the restricted
columns (SSN, bank, date of birth ...) as empty columns so the same grants script applies. Then fills them with
invented, seeded pseudo-random rows at `scale` x the real row counts. Everything is made up: names, phone numbers,
addresses, notes. It refuses to run against the office servers (OFFICE_HOSTS / backend/office-hosts.txt) and against an existing table.
"""
from __future__ import annotations

import json
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Identity, Integer, MetaData, Numeric, String, Table, Text, create_engine, func, inspect, select
from sqlalchemy.engine import make_url

from .ai import TRADE_SYNONYMS
from .config import BACKEND_DIR, settings
from .production import load_structure_csv
from .scaledata import COMPANY_A, COMPANY_B, FIRST, LAST, NOTES, REAL_COUNTS, SITES, STREETS
from .seed import FEATURES

REQUIRED = BACKEND_DIR.parent / "tools" / "prod-check" / "required_schema.json"
FORBIDDEN_HOSTS = {"localhost", "127.0.0.1", "."}  # plus settings.office_host_set (never in the code)
TEXT_MAX = {"EmSalesNotes", "EmAdminNotes", "CustEmail", "CustomerNote", "InvoiceNote", "CollectionsNote", "ProjNote", "ProjOfficeNote", "JobNote",
            "EmployeeNote", "HoursNote", "EmployeeLicenseNotes", "CustomerContactNotes", "FeatureDescription"}
CHUNK = 2000


# ---------------------------------------------------------------- schema
def _sa_type(column: str, sql_type: str):
    t = (sql_type or "nvarchar").lower()
    if column in TEXT_MAX or t in ("ntext", "text"):
        return Text()
    if t in ("int", "smallint", "tinyint", "bigint"):
        return Integer()
    if t == "bit":
        return Boolean()
    if t in ("money", "smallmoney"):
        return Numeric(19, 4)
    if t in ("decimal", "numeric"):
        return Numeric(18, 4)
    if t in ("float", "real"):
        return Float()
    if t in ("datetime", "datetime2", "smalldatetime", "datetimeoffset"):
        return DateTime()
    if t == "date":
        return Date()
    if t == "uniqueidentifier":
        return String(36)
    return String(255)


def build_metadata() -> MetaData:
    """The 33 tables with approved + restricted columns, typed from the schema export, keyed like the ORM models."""
    from . import models  # noqa: F401 - registers the ORM tables (for primary keys and foreign keys)
    from .database import Base

    required = json.loads(REQUIRED.read_text(encoding="utf-8"))
    structure = load_structure_csv(Path(settings.schema_csv_dir) / "McLabor_Database_structure.csv")
    orm = {t.name: t for t in Base.metadata.sorted_tables}
    md = MetaData()
    wanted = {t: set(cols) | set(required.get("sensitive_columns", {}).get(t, [])) for t, cols in required["tables"].items()}
    for name, cols in wanted.items():
        pk = {c.name for c in orm[name].primary_key.columns} if name in orm else set()
        fks = {}
        if name in orm:
            for c in orm[name].columns:
                for fk in c.foreign_keys:
                    if fk.column.table.name in wanted and fk.column.name in wanted[fk.column.table.name]:
                        fks[c.name] = f"{fk.column.table.name}.{fk.column.name}"
        csv_types = structure.get(name.lower(), {})
        columns = []
        for col in sorted(cols, key=lambda c: (c not in pk, c)):
            kind = _sa_type(col, csv_types.get(col.lower(), "nvarchar"))
            if col in pk:
                columns.append(Column(col, Integer(), Identity(always=False), primary_key=True))
            elif col in fks:
                columns.append(Column(col, Integer(), ForeignKey(fks[col]), nullable=True))
            else:
                columns.append(Column(col, kind, nullable=True))
        Table(name, md, *columns)
    return md


# ---------------------------------------------------------------- data
def _phone(r: random.Random) -> str:
    return f"({r.choice([617, 508, 781, 978, 413, 860, 203, 401, 603])}) 555-{r.randint(100, 9999):04d}"


def _rows(scale: float, seed: int = 20261123) -> dict[str, list[dict]]:
    r = random.Random(seed)
    now = datetime(2026, 11, 20, 12, 0, 0)
    out: dict[str, list[dict]] = {}

    def table(name, rows):
        out[name] = rows

    divisions = ["Electrical", "Mechanical", "General"]
    table("tblPullDownDivisions", [{"PullDownDivisionID": i, "PullDownDivision": d, "PullDownDivisionSort": i, "PullDownDivisionActive": True} for i, d in enumerate(divisions, 1)])
    trades = list(TRADE_SYNONYMS)
    table("tblPullDownTrade", [{"PullDownTradeID": i, "PullDownTrade": t, "PullDownTradeSwitch": None, "PullDownTradeSort": i, "PullDownTradeDivisionID": 1 + (i % 3)} for i, t in enumerate(trades, 1)])
    states = [("MA", "Massachusetts"), ("CT", "Connecticut"), ("RI", "Rhode Island"), ("NH", "New Hampshire"), ("NY", "New York"), ("ME", "Maine"), ("VT", "Vermont")]
    table("tblPullDownStates", [{"PullDownStateID": i, "PullDownState": c, "PullDownStateName": n, "PullDownStateSort": i} for i, (c, n) in enumerate(states, 1)])
    cities = [("MA", c) for c in ("Boston", "Worcester", "Springfield", "Cambridge", "Lowell", "Brockton", "Quincy", "Lynn", "New Bedford", "Newton", "Framingham", "Waltham", "Haverhill", "Malden", "Plymouth")]
    cities += [("CT", c) for c in ("Hartford", "New Haven", "Stamford", "Bridgeport", "Waterbury", "Norwalk", "Danbury", "Manchester")]
    cities += [("RI", c) for c in ("Providence", "Warwick", "Cranston", "Pawtucket")] + [("NH", c) for c in ("Manchester", "Nashua", "Concord", "Portsmouth")]
    cities += [("NY", c) for c in ("Albany", "Troy", "Schenectady")] + [("ME", "Portland"), ("VT", "Burlington")]
    state_id = {c: i for i, (c, _) in enumerate(states, 1)}
    table("tblPullDownStateCities", [{"PullDownStateCityID": i, "StateID": state_id[s], "City": c, "PullDownStateCitySort": i, "PullDownStateCityActive": True} for i, (s, c) in enumerate(cities, 1)])
    emp_status = ["Available", "On Assignment", "Active", "Inactive", "Applicant", "Do Not Use"]
    table("tblPullDownEmployeeStatus", [{"PullDownEmployeeStatusID": i, "PullDownEmployeeStatus": s, "PullDownEmployeeStatusSort": i} for i, s in enumerate(emp_status, 1)])
    quals = ["Master", "Journeyman", "Apprentice", "Helper", "Foreman"]
    table("tblPullDownQualifications", [{"PullDownQualificationID": i, "PullDownQualification": q, "PullDownQualificationSort": i, "PullDownQualificationDivisionID": 1} for i, q in enumerate(quals, 1)])
    table("tblPullDownExperience", [{"PullDownExperienceID": i, "PullDownExperience": e, "PullDownExperienceSort": i} for i, e in enumerate(["Entry", "Intermediate", "Senior"], 1)])
    table("tblPullDownLicenseTypes", [{"PullDownLicenseTypeID": i, "PullDownLicenseType": t, "PullDownLicenseTypeSort": i, "PullDownLicenseTypeActive": True} for i, t in enumerate(["Master License", "Journeyman License", "Apprentice Permit"], 1)])
    cust_status = ["Active", "Inactive", "Prospect", "Collections", "Do Not Use"]
    table("tblPullDownCustStatus", [{"PulldownCustStatusID": i, "PulldownCustStatus": s, "PulldownCustStatusSort": i} for i, s in enumerate(cust_status, 1)])
    cust_types = ["General Contractors", "Electrical Contractors", "Plumbing Contractors", "HVAC Contractors", "Mechanical Contractors", "Property Managers", "Developers"]
    table("tblPullDownCustomerTypes", [{"PullDownCustomerTypeID": i, "PullDownCustomerType": t, "PullDownCustomerTypeSort": i, "PullDownCustomerTypeDivisionID": 3} for i, t in enumerate(cust_types, 1)])
    table("tblPullDownSalesStatus", [{"PullDownSalesStatusID": i, "PullDownSalesStatus": s, "PullDownSalesStatusSort": i} for i, s in enumerate(["Lead", "Quoted", "Won", "Lost"], 1)])
    proj_status = ["Active", "Pending", "On Hold", "Completed", "Cancelled"]
    table("tblPullDownProjStatus", [{"PullDownProjStatusID": i, "PullDownProjStatus": s, "PullDownProjStatusSort": i} for i, s in enumerate(proj_status, 1)])
    wcc = [("5190", "Electrical Wiring"), ("5183", "Plumbing"), ("5537", "HVAC Installation"), ("5645", "Carpentry"), ("5221", "Concrete"), ("5022", "Masonry"), ("5551", "Roofing"), ("5538", "Sheet Metal"), ("5059", "Iron and Steel Erection"), ("5474", "Painting")]
    table("tblPullDownWCC", [{"PullDownWCCID": i, "PullDownWCC": c, "PullDownWCCDesc": d, "PullDownWCCSort": i, "PullDownWCCActive": True, "PullDownWCCDivisionID": 1 + (i % 3)} for i, (c, d) in enumerate(wcc, 1)])
    payroll = [("MC Labor Services", "MLS"), ("MC Labor Payroll", "MLP")]
    table("tblPullDownContractWith_PayrollCo", [{"PullDownContractWith_PayrollCoID": i, "PullDownContractWith_PayrollCoName": n, "PullDownContractWith_PayrollCoInitials": s, "PullDownContractWith_PayrollCoSort": i} for i, (n, s) in enumerate(payroll, 1)])
    table("tblPullDownPayrollCoOnSite", [{"PullDownPayrollCoOnSiteID": i, "PullDownPayrollCoOnSiteName": n, "PullDownPayrollCoOnSiteInitials": s, "PullDownPayrollCoOnSiteSort": i, "PullDownPayrollCoOnSiteActive": True} for i, (n, s) in enumerate(payroll, 1)])
    table("tblPullDownStatusFlag", [{"PullDownStatusFlagID": i, "PullDownStatusFlag": f, "PullDownStatusFlagDesc": d, "PullDownStatusFlagSort": i} for i, (f, d) in enumerate([("W", "Worked"), ("S", "Sick"), ("H", "Holiday"), ("N", "No show")], 1)])
    years = ["Less than 1 year", "1 year", "2 years", "3 years", "5 years", "7 years", "10 years", "15 years", "20 years", "25+ years"]
    table("tblPullDownYearsInTrade", [{"PullDownYearsInTradeID": i, "PullDownYearsInTrade": y} for i, y in enumerate(years, 1)])
    table("tblPullDownCustomerContactTitles", [{"PullDownCustomerContactTitleID": i, "PullDownCustomerContactTitle": t, "PullDownCustomerContactTitleSort": i} for i, t in enumerate(["Owner", "Project Manager", "Estimator", "Office Manager", "Foreman"], 1)])
    table("tblPullDownEmployeeNoteTypes", [{"PullDownEmployeeNoteTypeID": i, "PullDownEmployeeNoteType": t, "PullDownEmployeeNoteTypeSort": i} for i, t in enumerate(["Quick Note", "Main Note", "Salesman Comment", "Regular Day No Show", "Review"], 1)])
    table("tblFeature", [{"FeatureID": i, "ObjectName": obj, "FeatureTitle": title, "FeatureDescription": desc, "FeatureSort": i, "FeatureActive": True, "ControlName": None} for i, (obj, title, desc) in enumerate(FEATURES, 1)])

    staff_names = [("Alex", "Rivera"), ("Jordan", "Chen"), ("Sam", "Okafor"), ("Taylor", "Nguyen"), ("Morgan", "Patel"), ("Casey", "Dubois"), ("Riley", "Haddad"), ("Drew", "Kowalski"),
                   ("Jamie", "Santos"), ("Avery", "Lindqvist"), ("Quinn", "Moreau"), ("Reese", "Bakker")]
    titles = ["Office Manager", "Recruiter", "Sales Representative", "Dispatcher", "Payroll Specialist", "Accounting", "Safety Coordinator"]
    staff = []
    for i, (f, l) in enumerate(staff_names, 1):
        ini = (f[0] + l[:2]).upper()
        staff.append({"OfficeStaffID": i, "OfficeStaffFirstName": f, "OfficeStaffLastName": l, "OfficeStaffFullName": f"{f} {l}", "Initials": ini, "OfficeStaffTitle": titles[i % len(titles)],
                      "OfficeStaffEmail": f"{f.lower()}.{l.lower()}@example.com", "OfficeStaffActive": i <= 10, "OfficeStaffCanDelete": i <= 2, "Profile": False,
                      "OfficeStaffEmployeeResearch": False, "OfficeStaffHideHours": i % 4 == 0, "OfficeStaffTrackingReportEmailReceive": i % 3 == 0, "OfficeStaffPassword": None})
    table("tblOfficeStaff", staff)
    initials = [s["Initials"] for s in staff if s["OfficeStaffActive"]]
    perms, pid = [], 1
    for s in staff[:6]:
        for fid in range(1, len(FEATURES) + 1):
            perms.append({"OfficeStaffPermissionID": pid, "OfficeStaffID": s["OfficeStaffID"], "FeatureID": fid}); pid += 1
    table("tblOfficeStaffPermission", perms)
    table("tblOfficeStaffActivity", [{"OfficeStaffActivityID": i, "OfficeStaffID": r.randint(1, 10), "OfficeStaffActivityObjectName": r.choice(["login", "employee.view", "customer.view"]),
                                      "OfficeStaffActivityObjectID": r.randint(1, 100), "OfficeStaffActivityTimestampStart": now - timedelta(hours=i)} for i in range(1, 41)])
    table("tblPullDownSalesman", [{"PullDownSalesmanID": i, "PullDownSalesmanFName": staff[i - 1]["OfficeStaffFirstName"], "PullDownSalesmanLName": staff[i - 1]["OfficeStaffLastName"], "PullDownSalesmanTitle": "Sales",
                                   "PullDownSalesmanEmail": staff[i - 1]["OfficeStaffEmail"], "PullDownSalesmanCell": _phone(r), "PullDownSalesmanSort": i, "OfficeStaffID": i, "PullDownSalesmanActive": True} for i in range(1, 7)])

    n_emp = max(50, int(REAL_COUNTS["employees"] * scale))
    n_cust = max(30, int(REAL_COUNTS["customers"] * scale))
    n_proj = max(20, int(REAL_COUNTS["projects"] * scale))
    n_track = max(100, int(REAL_COUNTS["tracking"] * scale))
    city_ids = list(range(1, len(cities) + 1))

    employees, emp_b = [], []
    for i in range(1, n_emp + 1):
        cid = r.choice(city_ids)
        st, city = cities[cid - 1]
        first, last = r.choice(FIRST), r.choice(LAST)
        licensed = r.random() < 0.3
        employees.append({
            "EmployeeID": i, "EmFirstName": first, "EmLastName": last, "EmMiddle": r.choice(["A", "J", "M", None, None]), "EmStreet": f"{r.randint(1, 999)} {r.choice(STREETS)}",
            "EmStateCityID": cid, "EmCity": city, "EmState": st, "EmZip": f"{r.randint(1001, 6999):05d}", "EmHomePhone": _phone(r) if r.random() < 0.3 else None, "EmMobilePhone": _phone(r),
            "EmEmail": f"{first.lower()}.{last.lower().replace(chr(39), '')}{i}@example.com", "EmEmployeeStatusID": r.randint(1, len(emp_status)) if r.random() < 0.6 else None,
            "EmQualificationID": r.randint(1, len(quals)), "EmTradeID": r.randint(1, len(trades)), "SubTrade1ID": r.randint(1, len(trades)) if r.random() < 0.2 else None, "SubTrade2ID": None,
            "EmExperienceID": r.randint(1, 3), "YearsInTradeID": r.randint(1, len(years)) if r.random() < 0.7 else None, "EmLicenseNum": f"L{r.randint(10000, 99999)}" if licensed else None,
            "EmLicenseDateExpires": now + timedelta(days=r.randint(-200, 700)) if licensed else None, "EmLicensedIn": st if licensed else None, "OSHA10": r.choice(["OSHA 10", "OSHA 30", None, None]),
            "BaseSalary": round(r.uniform(18, 65), 2), "EmHowReferredID": None, "EmReferredBy": None, "ReferrerEmployeeID": None, "EmContractWith_PayrollCoID": r.randint(1, 2),
            "JobApplComplete": r.random() < 0.8, "EmApplComplete": r.random() < 0.8, "Recruiter": False, "PostEmployeeAsAvailable": r.random() < 0.25, "EmployeeNoCommunication": r.random() < 0.02,
            "EmAdminNotes": r.choice(NOTES) if r.random() < 0.1 else None, "EmSalesNotes": r.choice(NOTES) if r.random() < 0.05 else None, "EmEntryUserName": r.choice(initials),
            "EmEntryTimestamp": now - timedelta(days=r.randint(0, 4000)), "EmployeeDuplicate": r.random() < 0.01,
        })
        emp_b.append({"EmployeeBID": i, "EmployeeID": i, "WillTravel": r.choice(["Yes", "No", "Regional", None])})
    table("tblEmployee", employees)
    table("tblEmployeeB", emp_b)
    table("tblEmployeeLicenses", [{"EmployeeLicenseID": i, "EmployeeID": r.randint(1, n_emp), "EmployeeLicenseStateID": r.randint(1, len(states)), "EmployeeLicenseTradeID": r.randint(1, len(trades)),
                                   "EmployeeLicenseTypeID": r.randint(1, 3), "EmployeeLicenseNumber": f"LIC{r.randint(1000, 99999)}", "EmployeeLicenseExpDate": now + timedelta(days=r.randint(-300, 900)),
                                   "EmployeeLicenseCopyOnFile": r.choice(["Yes", "No"]), "EmployeeLicenseNotes": None} for i in range(1, n_emp // 4 + 1)])
    table("tblEmployeeNotes", [{"EmployeeNoteID": i, "EmployeeID": r.randint(1, n_emp), "EmployeeNote": r.choice([n for n in NOTES if n]), "EmployeeNoteUserName": r.choice(initials),
                                "EmployeeNoteTimestamp": now - timedelta(days=r.randint(0, 2000)), "EmployeeNoteTypeID": r.randint(1, 5), "EmployeeNoteCustomerID": None} for i in range(1, n_emp // 3 + 1)])

    industries = ["Healthcare Facilities", "Commercial Construction", "Residential", "Education", "Industrial", "Retail", "Hospitality", "Public Works"]
    customers = []
    for i in range(1, n_cust + 1):
        cid = r.choice(city_ids)
        st, city = cities[cid - 1]
        customers.append({
            "CustomerID": i, "CustBusName": f"{r.choice(COMPANY_A)} {r.choice(COMPANY_B)} {i}", "Street": f"{r.randint(1, 999)} {r.choice(STREETS)}", "StateCityID": cid, "City": city, "State": st,
            "Zip": f"{r.randint(1001, 6999):05d}", "Phone": _phone(r) if r.random() < 0.65 else None, "CustEmail": f"office{i}@example.com" if r.random() < 0.2 else None, "CustFaxNum": None,
            "CustWebSiteHLink": None, "CustStatusID": r.randint(1, len(cust_status)), "CustomerTypeID": r.randint(1, len(cust_types)), "SalesmanID": r.randint(1, 6), "SalesStatusID": r.randint(1, 4),
            "CustContractWith_PayrollCoID": r.randint(1, 2), "ContractOnFile": r.random() < 0.6, "ContractDate": now - timedelta(days=r.randint(0, 3000)), "CreditLimit": r.choice([5000, 10000, 25000, None]),
            "RevenuePerYear": round(r.uniform(5000, 3_000_000), 2), "LaborRateAFrom": 30.0, "LaborRateATo": 45.0, "LaborRateBFrom": 45.0, "LaborRateBTo": 65.0, "BillRateOTMultiplier": 1.5,
            "Industry": r.choice(industries), "EmployeeSize": r.choice(["1-10", "11-50", "51-200", None]), "CustomerDescription": r.choice(NOTES), "CustomerNote": r.choice(NOTES), "InvoiceNote": None,
            "CollectionsNote": None, "OnHold": r.random() < 0.05, "FutureSales": r.random() < 0.2, "FutureCall": None, "CustomerLicenseNumber": None, "CustEntryUserName": r.choice(initials),
            "CustEntryTimestamp": now - timedelta(days=r.randint(0, 4000)),
        })
    table("tblCustomer", customers)
    table("tblCustomerContacts", [{"CustomerContactID": i, "CustomerID": r.randint(1, n_cust), "CustomerContactPriority": r.randint(1, 3), "CustomerContactFName": r.choice(FIRST), "CustomerContactLName": r.choice(LAST),
                                   "CustomerContactTitleID": r.randint(1, 5), "CustomerContactEmail": f"contact{i}@example.com" if r.random() < 0.6 else None, "CustomerContactCell": _phone(r) if r.random() < 0.3 else None,
                                   "CustomerContactOfficePhone": _phone(r) if r.random() < 0.5 else None, "CustomerContactNotes": None, "CustomerContactUserName": r.choice(initials),
                                   "CustomerContactTimestamp": now - timedelta(days=r.randint(0, 3000))} for i in range(1, n_cust // 2 + 1)])
    table("tblCustomerNotes", [{"CustomerNoteID": i, "CustomerID": r.randint(1, n_cust), "CustomerNote": r.choice([n for n in NOTES if n]), "CustomerNoteUserName": r.choice(initials),
                                "CustomerNoteTimestamp": now - timedelta(days=r.randint(0, 3000)), "CustomerNoteActive": True} for i in range(1, n_cust // 3 + 1)])

    projects = []
    for i in range(1, n_proj + 1):
        cid = r.choice(city_ids)
        start = now.date() + timedelta(days=r.randint(-1500, 120))
        projects.append({
            "ProjectID": i, "CustomerID": r.randint(1, n_cust), "SiteName": f"{r.choice(SITES)} {i}", "SiteStreet": f"{r.randint(1, 999)} {r.choice(STREETS)}", "SiteStateCityID": cid,
            "SiteZip": f"{r.randint(1001, 6999):05d}", "StartDate": start, "EndDate": start + timedelta(days=r.randint(20, 400)), "ProjStatusID": r.randint(1, len(proj_status)),
            "ProjectWCCID": r.randint(1, len(wcc)), "ProjNote": r.choice(NOTES), "ProjOfficeNote": None, "JobNote": r.choice(NOTES), "ProjStartTime": "7:00 AM", "OCIPJob": r.random() < 0.1,
            "RateJob": r.random() < 0.3, "ShiftDifferential": False, "JobBeingManned": r.random() < 0.6, "GCOnSite": r.random() < 0.5, "ARateQty": r.randint(0, 5), "BRateQty": r.randint(0, 3), "CRateQty": 0,
            "NumberOfEmployees": r.randint(1, 12) if r.random() < 0.2 else None, "ContractAmount": round(r.uniform(5000, 500000), 2), "ContractTotalPayments": 0, "ContractBalanceOwed": 0,
            "CustomerContact": f"{r.choice(FIRST)} {r.choice(LAST)}", "CustomerPhone": _phone(r) if r.random() < 0.05 else None, "CustomerEmail": None, "ParentProjectID": None,
            "ProjectEntryUserName": r.choice(initials), "ProjectEntryTimestamp": now - timedelta(days=r.randint(0, 3000)),
        })
    table("tblProject", projects)
    proj_customer = {p["ProjectID"]: p["CustomerID"] for p in projects}
    friday = date(2026, 11, 20)
    tracking = []
    for i in range(1, n_track + 1):
        pid = r.randint(1, n_proj)
        we = friday - timedelta(weeks=r.randint(0, 260))
        days = [r.choice([0, 8, 8, 8, 10]) for _ in range(5)]
        total = float(sum(days))
        pay = round(r.uniform(18, 60), 2)
        bill = round(pay * r.uniform(1.35, 1.7), 2)
        reg, ot = min(total, 40.0), max(total - 40.0, 0.0)
        gross, invoice = round(reg * pay + ot * pay * 1.5, 2), round(reg * bill + ot * bill * 1.5, 2)
        iso = we.isocalendar()
        tracking.append({
            "TrackingID": i, "CustomerID": proj_customer[pid], "EmployeeID": r.randint(1, n_emp), "ProjectID": pid, "AssignWeek": iso.week, "AssignYear": iso.year, "WeekEndingDate": datetime.combine(we, datetime.min.time()),
            "PayrollCoOnSiteID": r.randint(1, 2), "PayRate": pay, "OTPayRate": round(pay * 1.5, 2), "BillRate": bill, "BillRateOT": round(bill * 1.5, 2), "SatHours": 0.0, "SunHours": 0.0,
            "MonHours": days[0], "TueHours": days[1], "WedHours": days[2], "ThuHours": days[3], "FriHours": days[4], "MonStatusFlagID": 1 if days[0] else 4, "TotalHours": total, "RegularHours": reg,
            "OvertimeHours": ot, "InvoiceAmount": invoice, "EmGrossPayroll": gross, "CalcProfitMargin": round((invoice - gross) / invoice, 4) if invoice else None, "WCC": r.choice(wcc)[0],
            "Grade": r.choice(["A", "B", "C", None]), "HoursNote": None, "DirectionsSentEmail": False, "DirectionsSentText": r.random() < 0.3, "DirVerified": r.random() < 0.5, "PayrollInfoSent": r.random() < 0.5,
            "Placeholder": False, "AssignmentUserName": r.choice(initials), "AssignmentTimestamp": datetime.combine(we, datetime.min.time()) - timedelta(days=6),
        })
    table("tblTracking", tracking)
    return out


# ---------------------------------------------------------------- build
def refuse_office_servers(url: str) -> None:
    u = make_url(url)
    host = (u.host or "").split("\\")[0].split(",")[0].strip().lower()
    if u.drivername.startswith("mssql") and (host in FORBIDDEN_HOSTS or settings.is_office_host(host)):
        raise RuntimeError(f"Refusing to build a synthetic database on '{u.host}': the office servers are never touched.")


def build(url: str, scale: float = 0.05, quiet: bool = False, fill_existing: bool = False) -> dict[str, int]:
    """Create the 33 tables and fill them. With ``fill_existing`` the tables may already exist (built by app.pgschema
    from the full structure) but must all be EMPTY; the rows are then inserted into them."""
    refuse_office_servers(url)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    t0 = time.perf_counter()
    md = build_metadata()
    engine = create_engine(url, future=True)
    existing = set(inspect(engine).get_table_names())
    clash = [t.name for t in md.sorted_tables if t.name in existing]
    if clash and not fill_existing:
        raise RuntimeError(f"Tables already exist in that database ({', '.join(clash[:5])}...): refusing to build on top of them.")
    if fill_existing:
        missing = [t.name for t in md.sorted_tables if t.name not in existing]
        if missing:
            raise RuntimeError(f"fill_existing: these tables do not exist yet ({', '.join(missing[:5])}...). Apply app.pgschema first.")
        with engine.connect() as conn:
            for t in md.sorted_tables:
                if conn.execute(select(func.count()).select_from(t)).scalar_one():
                    raise RuntimeError(f"Table {t.name} already holds rows: refusing to add synthetic data to a database that is not empty.")
    else:
        md.create_all(engine)
    rows = _rows(scale)
    counts: dict[str, int] = {}
    with engine.begin() as conn:
        for t in md.sorted_tables:  # dependency order
            data = rows.get(t.name, [])
            valid = {c.name for c in t.columns}
            for i in range(0, len(data), CHUNK):
                conn.execute(t.insert(), [{k: v for k, v in row.items() if k in valid} for row in data[i:i + CHUNK]])
            counts[t.name] = len(data)
        if engine.dialect.name == "postgresql":
            from .pgschema import reset_sequences

            reset_sequences(conn)  # the rows carry explicit ids: move the identity sequences past them
    with engine.connect() as conn:
        for t in md.sorted_tables:
            counts[t.name] = int(conn.execute(select(func.count()).select_from(t)).scalar_one())
    engine.dispose()
    if not quiet:
        print(f"Synthetic McLabor-shaped database built in {time.perf_counter() - t0:.0f}s at scale {scale}:")
        for name, n in counts.items():
            print(f"  {name:36} {n:>9,}")
        print("Every value is invented. The restricted columns exist and are empty.")
    return counts


if __name__ == "__main__":  # pragma: no cover
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    build(args[0], float(args[1]) if len(args) > 1 else 0.05, fill_existing="--fill-existing" in sys.argv)
