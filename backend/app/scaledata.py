"""Synthetic data at the size of the real McLabor database, for performance testing only.

    .venv\\Scripts\\python.exe -m app.scaledata  PATH\\to\\scale.db

Builds a SQLite file with the demo lookups plus roughly the row counts measured on the restored
copy on 2026-11-20: 178,993 employees, 106,828 customers, 15,748 jobs, 192,225 weekly tracking
rows.  All names, phones, addresses and notes are invented (seeded pseudo-random), so results are
repeatable.  It never touches SQL Server and is never used by the website itself.
"""
from __future__ import annotations

import random
import sys
import time
from datetime import date, timedelta

from sqlalchemy import insert, select
from sqlalchemy.orm import sessionmaker

from . import models as m
from .database import Base, make_engine
from .seed import seed, week_ending

REAL_COUNTS = {"employees": 178_993, "customers": 106_828, "projects": 15_748, "tracking": 192_225}

FIRST = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
         "Joseph", "Jessica", "Thomas", "Sarah", "Carlos", "Karen", "Daniel", "Nancy", "Matthew", "Lisa", "Anthony", "Betty", "Mark", "Maria", "Luis",
         "Sandra", "Steven", "Ashley", "Paul", "Kimberly", "Andrew", "Emily", "Joshua", "Donna", "Kevin", "Michelle", "Brian", "Carol", "Jorge", "Amanda",
         "Edward", "Melissa", "Ronald", "Deborah", "Timothy", "Stephanie", "Jason", "Rebecca", "Jeffrey", "Sharon", "Ryan", "Laura", "Jacob", "Cynthia",
         "Gary", "Kathleen", "Nicholas", "Amy", "Eric", "Angela", "Jonathan", "Shirley", "Stephen", "Anna", "Larry", "Brenda", "Justin", "Pamela", "Scott",
         "Emma", "Brandon", "Nicole", "Benjamin", "Helen", "Samuel", "Samantha", "Gregory", "Katherine", "Frank", "Christine", "Raymond", "Debra", "Patrick",
         "Rachel", "Jack", "Carolyn", "Dennis", "Janet", "Jerry", "Catherine", "Tyler", "Heather", "Aaron", "Diane", "Jose", "Ruth", "Adam", "Julie"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson",
        "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis",
        "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall",
        "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker", "Cruz", "Edwards", "Collins",
        "Reyes", "Stewart", "Morris", "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson", "Bailey", "Reed", "Kelly",
        "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson", "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes",
        "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long", "Ross", "Foster", "Jimenez", "O'Brien", "Sullivan", "Fitzgerald", "Donovan",
        "Gallagher", "Kowalski", "Petrov", "Santos", "Silva", "Costa"]
COMPANY_A = ["Harbor", "Summit", "Bay State", "Patriot", "Pioneer", "Granite", "Liberty", "Atlantic", "Beacon", "Northeast", "Commonwealth", "Evergreen",
             "Ironworks", "Keystone", "Landmark", "Mayflower", "Minuteman", "Colonial", "Riverside", "Seaport", "Sterling", "Titan", "Unity", "Vanguard",
             "Blue Hills", "Cape", "Charles River", "Merrimack", "Pilgrim", "Quabbin"]
COMPANY_B = ["Electric", "Electrical Contractors", "Plumbing & Heating", "Mechanical", "Construction", "Builders", "HVAC Services", "Property Management",
             "Development Group", "General Contracting", "Fire Protection", "Roofing", "Masonry", "Sheet Metal", "Interiors"]
STREETS = ["Main St", "Washington St", "Elm St", "Park Ave", "Maple Ave", "High St", "School St", "Summer St", "Pleasant St", "Broadway", "Union St", "Center St"]
NOTES = ["reliable, shows up early", "prefers night shift", "has own tools and truck", "bilingual english/spanish", "needs steel toe boots reminder",
         "good with blueprints", "do not send to rooftop work", "available weekends", "recommended by foreman", "completed safety refresher",
         "asked for more hours", "strong finish carpentry", "fork lift certified", "worked hospital jobs", None, None, None, None]
SITES = ["Medical Center Fit-Out", "Elementary School Renovation", "Office Tower Floors", "Warehouse Expansion", "Apartment Complex Phase", "Retail Plaza",
         "Lab Building", "Hotel Refurbishment", "Parking Garage", "Data Center Hall", "University Dorm", "Fire Station Upgrade"]
CHUNK = 5_000


def _phone(r: random.Random) -> str:
    return f"({r.randint(201, 989)}) {r.randint(200, 999)}-{r.randint(1000, 9999)}"


def _bulk(db, table, rows: list[dict]) -> None:
    for i in range(0, len(rows), CHUNK):
        db.execute(insert(table), rows[i:i + CHUNK])
    db.commit()


def build(path: str, scale: float = 1.0, quiet: bool = False) -> dict[str, int]:
    """Create the file (it must not exist) and fill it. ``scale`` shrinks every count, e.g. 0.1 for quick tests."""
    t0 = time.perf_counter()
    engine = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    r = random.Random(20261120)
    with Session() as db:
        seed(db)  # lookups, users and the small demo set
        trades = [i for (i,) in db.execute(select(m.PullDownTrade.PullDownTradeID))]
        quals = [i for (i,) in db.execute(select(m.PullDownQualification.PullDownQualificationID))]
        emp_status = [i for (i,) in db.execute(select(m.PullDownEmployeeStatus.PullDownEmployeeStatusID))]
        cust_status = [i for (i,) in db.execute(select(m.PullDownCustStatus.PulldownCustStatusID))]
        cust_types = [i for (i,) in db.execute(select(m.PullDownCustomerType.PullDownCustomerTypeID))]
        proj_status = [i for (i,) in db.execute(select(m.PullDownProjStatus.PullDownProjStatusID))]
        salesmen = [i for (i,) in db.execute(select(m.PullDownSalesman.PullDownSalesmanID))]
        wcc = [i for (i,) in db.execute(select(m.PullDownWCC.PullDownWCCID))]
        cities = [(cid, city, st) for cid, city, st in db.execute(
            select(m.PullDownStateCity.PullDownStateCityID, m.PullDownStateCity.City, m.PullDownState.PullDownState)
            .join(m.PullDownState, m.PullDownStateCity.StateID == m.PullDownState.PullDownStateID))]
        industries = [i for (i,) in db.execute(select(m.Customer.Industry).distinct()) if i]
        base = {"employees": db.execute(select(m.Employee.EmployeeID)).all().__len__(), "customers": db.execute(select(m.Customer.CustomerID)).all().__len__()}

        n_emp = int(REAL_COUNTS["employees"] * scale)
        n_cust = int(REAL_COUNTS["customers"] * scale)
        n_proj = int(REAL_COUNTS["projects"] * scale)
        n_track = int(REAL_COUNTS["tracking"] * scale)

        employees = []
        for i in range(n_emp):
            cid, city, st = r.choice(cities)
            first, last = r.choice(FIRST), r.choice(LAST)
            licensed = r.random() < 0.3
            employees.append({
                "EmFirstName": first, "EmLastName": last, "EmStreet": f"{r.randint(1, 999)} {r.choice(STREETS)}", "EmStateCityID": cid, "EmCity": city,
                "EmState": st, "EmZip": f"{r.randint(1001, 6999):05d}", "EmMobilePhone": _phone(r), "EmHomePhone": _phone(r) if r.random() < 0.3 else None,
                "EmEmail": f"{first.lower()}.{last.lower().replace(chr(39), '')}{i}@example.com", "EmEmployeeStatusID": r.choice(emp_status),
                "EmQualificationID": r.choice(quals), "EmTradeID": r.choice(trades), "SubTrade1ID": r.choice(trades) if r.random() < 0.2 else None,
                "YearsInTrade": r.randint(0, 35), "EmLicenseNum": f"L{r.randint(10000, 99999)}" if licensed else None,
                "EmLicenseDateExpires": date.today() + timedelta(days=r.randint(-200, 700)) if licensed else None,
                "EmLicensedIn": st if licensed else None, "OSHA10": r.choice(["OSHA 10", "OSHA 30", None, None]), "BaseSalary": round(r.uniform(18, 65), 2),
                "WillTravel": r.choice(["Yes", "No", "Regional", None]), "PostEmployeeAsAvailable": r.random() < 0.25, "EmAdminNotes": r.choice(NOTES),
                "EmSalesNotes": r.choice(NOTES), "USCitizen": True, "I9Complete": r.random() < 0.85, "EmployeeDuplicate": r.random() < 0.01,
            })
        _bulk(db, m.Employee.__table__, employees)
        del employees

        customers = []
        for i in range(n_cust):
            cid, city, st = r.choice(cities)
            customers.append({
                "CustBusName": f"{r.choice(COMPANY_A)} {r.choice(COMPANY_B)} {i}", "Street": f"{r.randint(1, 999)} {r.choice(STREETS)}", "StateCityID": cid, "City": city,
                "State": st, "Zip": f"{r.randint(1001, 6999):05d}", "Phone": _phone(r), "CustEmail": f"office{i}@example.com", "CustStatusID": r.choice(cust_status),
                "CustomerTypeID": r.choice(cust_types), "SalesmanID": r.choice(salesmen), "Industry": r.choice(industries),
                "ContractOnFile": r.random() < 0.6, "OnHold": r.random() < 0.05, "RevenuePerYear": round(r.uniform(5_000, 3_000_000), 2),
                "CustomerNote": r.choice(NOTES),
            })
        _bulk(db, m.Customer.__table__, customers)
        del customers

        emp_max = base["employees"] + n_emp
        cust_max = base["customers"] + n_cust
        _bulk(db, m.EmployeeLicense.__table__, [
            {"EmployeeID": r.randint(1, emp_max), "EmployeeLicenseExpDate": date.today() + timedelta(days=r.randint(-300, 900))} for _ in range(n_emp // 4)])
        _bulk(db, m.CustomerContact.__table__, [
            {"CustomerID": r.randint(1, cust_max), "CustomerContactFName": r.choice(FIRST), "CustomerContactLName": r.choice(LAST)} for _ in range(n_cust // 2)])

        projects = []
        for i in range(n_proj):
            cid, city, st = r.choice(cities)
            start = date.today() + timedelta(days=r.randint(-1500, 120))
            projects.append({
                "CustomerID": r.randint(1, cust_max), "SiteName": f"{r.choice(SITES)} {i}", "SiteStreet": f"{r.randint(1, 999)} {r.choice(STREETS)}",
                "SiteStateCityID": cid, "SiteCity": city, "SiteState": st, "SiteZip": f"{r.randint(1001, 6999):05d}", "StartDate": start,
                "EndDate": start + timedelta(days=r.randint(20, 400)), "ProjStatusID": r.choice(proj_status), "ProjectWCCID": r.choice(wcc),
                "NumberOfEmployees": r.randint(1, 12), "JobBeingManned": r.random() < 0.6, "OCIPJob": r.random() < 0.1, "ProjNote": r.choice(NOTES),
                "CustomerContact": f"{r.choice(FIRST)} {r.choice(LAST)}", "CustomerPhone": _phone(r),
            })
        _bulk(db, m.Project.__table__, projects)
        proj_customer = dict(db.execute(select(m.Project.ProjectID, m.Project.CustomerID)).all())
        proj_ids = list(proj_customer)
        del projects

        this_week = week_ending(date.today())
        tracking = []
        for _ in range(n_track):
            pid = r.choice(proj_ids)
            we = this_week - timedelta(weeks=r.randint(0, 260))
            hours = float(r.choice([8, 16, 24, 32, 40, 40, 40, 45, 50]))
            pay, bill = round(r.uniform(18, 60), 2), 0.0
            bill = round(pay * r.uniform(1.35, 1.7), 2)
            iso = we.isocalendar()
            tracking.append({
                "CustomerID": proj_customer[pid], "EmployeeID": r.randint(1, emp_max), "ProjectID": pid, "AssignWeek": iso.week, "AssignYear": iso.year,
                "WeekEndingDate": we, "PayRate": pay, "BillRate": bill, "TotalHours": hours, "RegularHours": min(hours, 40.0),
                "OvertimeHours": max(hours - 40.0, 0.0), "InvoiceAmount": round(hours * bill, 2), "EmGrossPayroll": round(hours * pay, 2),
            })
        _bulk(db, m.Tracking.__table__, tracking)
        del tracking

        counts = {
            "employees": db.execute(select(m.Employee.EmployeeID)).all().__len__(), "customers": db.execute(select(m.Customer.CustomerID)).all().__len__(),
            "projects": db.execute(select(m.Project.ProjectID)).all().__len__(), "tracking": db.execute(select(m.Tracking.TrackingID)).all().__len__(),
        }
    engine.dispose()
    if not quiet:
        print(f"Built {path} in {time.perf_counter() - t0:.0f}s: " + ", ".join(f"{v:,} {k}" for k, v in counts.items()))
    return counts


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    build(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1.0)
