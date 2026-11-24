"""Synthetic demonstration data.

Everything here is generated with a fixed random seed so the demo database
is reproducible.  No real MC Labor data is used.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .config import settings
from .security import hash_password

SEED = 20251119
fake = Faker("en_US")

DIVISIONS = ["Electrical", "Plumbing / HVAC", "General Construction", "Finishing"]
TRADES = [
    ("Electrician", "Electrical"), ("Plumber", "Plumbing / HVAC"), ("HVAC Technician", "Plumbing / HVAC"),
    ("Pipefitter", "Plumbing / HVAC"), ("Sprinkler Fitter", "Plumbing / HVAC"), ("Sheet Metal Worker", "Plumbing / HVAC"),
    ("Carpenter", "General Construction"), ("Laborer", "General Construction"), ("Mason", "General Construction"),
    ("Ironworker", "General Construction"), ("Equipment Operator", "General Construction"), ("Welder", "General Construction"),
    ("Roofer", "General Construction"), ("Painter", "Finishing"), ("Drywall Installer", "Finishing"),
]
STATES = [("MA", "Massachusetts"), ("CT", "Connecticut"), ("RI", "Rhode Island"), ("NH", "New Hampshire"),
          ("NY", "New York"), ("ME", "Maine"), ("VT", "Vermont")]
CITIES = {
    "MA": ["Boston", "Worcester", "Springfield", "Cambridge", "Lowell", "Quincy", "Framingham", "Waltham", "Brockton",
           "Newton", "Somerville", "Marlborough", "Plymouth", "Woburn", "Peabody"],
    "CT": ["Hartford", "New Haven", "Stamford", "Bridgeport", "Waterbury", "Danbury", "Norwalk"],
    "RI": ["Providence", "Warwick", "Cranston", "Pawtucket", "Newport"],
    "NH": ["Manchester", "Nashua", "Concord", "Portsmouth", "Salem"],
    "NY": ["Albany", "Yonkers", "White Plains", "Poughkeepsie"],
    "ME": ["Portland", "Lewiston", "Bangor"],
    "VT": ["Burlington", "Rutland"],
}
EMPLOYEE_STATUSES = ["Active", "Available", "On Assignment", "Inactive", "Applicant", "Do Not Use"]
QUALIFICATIONS = ["Master", "Journeyman", "Apprentice", "Helper", "Foreman"]
EXPERIENCE = ["Entry (0-2 yrs)", "Intermediate (3-5 yrs)", "Experienced (6-10 yrs)", "Senior (10+ yrs)"]
LICENSE_TYPES = ["Journeyman Electrician", "Master Electrician", "Journeyman Plumber", "Master Plumber",
                 "HVAC / Refrigeration", "Hoisting Engineer", "Construction Supervisor (CSL)", "Sprinkler Fitter",
                 "Sheet Metal Journeyperson", "Welding Certification"]
CUST_STATUSES = ["Active", "Prospect", "Inactive", "Collections", "Do Not Use"]
CUST_TYPES = ["Electrical Contractor", "Plumbing Contractor", "General Contractor", "HVAC Contractor",
              "Mechanical Contractor", "Property Manager", "Developer"]
SALES_STATUSES = ["New Lead", "Contacted", "Quoted", "Active Account", "Dormant", "Lost"]
PROJ_STATUSES = ["Pending", "Active", "On Hold", "Completed", "Cancelled"]
WCC = [("5190", "Electrical Wiring - Within Buildings"), ("5183", "Plumbing NOC"), ("5537", "HVAC Installation & Service"),
       ("5645", "Carpentry - Detached Dwellings"), ("5403", "Carpentry NOC"), ("5474", "Painting NOC"),
       ("5022", "Masonry NOC"), ("5551", "Roofing - All Kinds"), ("5538", "Sheet Metal Work - Installation"),
       ("5213", "Concrete Construction NOC"), ("6217", "Excavation & Drivers"), ("5057", "Iron or Steel Erection")]
PAYROLL_COS = [("MC Labor Services LLC", "MLS"), ("Hub Staffing Group", "HSG"), ("Interstate Personnel Group", "IPG")]
STATUS_FLAGS = [("W", "Worked"), ("N", "No Show"), ("S", "Sick"), ("H", "Holiday"), ("R", "Rain-out"), ("O", "Off")]
CONTACT_TITLES = ["Owner", "President", "Project Manager", "Superintendent", "Foreman", "Estimator", "Office Manager",
                  "Accounts Payable", "Safety Director"]
NOTE_TYPES = ["General", "Review", "Payroll", "Safety", "Attendance", "Recruiting", "Reference Check"]
INDUSTRIES = ["Commercial Construction", "Residential Construction", "Healthcare Facilities", "Education",
              "Industrial / Manufacturing", "Multi-family Housing", "Retail Build-out", "Public Works",
              "Data Centers", "Hospitality"]
FEATURES = [
    ("employees.view", "View Employees", "Open the employee list and employee records"),
    ("employees.edit", "Add / Edit Employees", "Create new employees and edit existing records"),
    ("customers.view", "View Customers", "Open the customer list and customer records"),
    ("customers.edit", "Add / Edit Customers", "Create new customers and edit existing records"),
    ("projects.view", "View Jobs / Projects", "Open the job list and job records"),
    ("projects.edit", "Add / Edit Jobs / Projects", "Create and edit jobs"),
    ("tracking.view", "View Weekly Tracking", "See weekly assignments and hours"),
    ("tracking.edit", "Edit Weekly Tracking", "Create assignments and enter hours"),
    ("payroll.view", "View Pay / Bill Rates", "See pay rates, bill rates and margins"),
    ("reports.view", "View Reports & Dashboard", "Dashboard metrics and reports"),
    ("ai.search", "AI Search", "Use natural-language AI search"),
    ("users.manage", "Manage Users", "Create users and assign permissions"),
]
ROLE_FEATURES = {
    "Administrator": [f[0] for f in FEATURES],
    "Office Manager": [f[0] for f in FEATURES if f[0] != "users.manage"],
    "Recruiter": ["employees.view", "employees.edit", "projects.view", "tracking.view", "ai.search", "reports.view"],
    "Sales Representative": ["customers.view", "customers.edit", "projects.view", "projects.edit", "employees.view", "ai.search", "reports.view"],
    "Dispatcher": ["employees.view", "customers.view", "projects.view", "projects.edit", "tracking.view", "tracking.edit", "ai.search"],
    "Payroll Specialist": ["employees.view", "tracking.view", "tracking.edit", "payroll.view", "reports.view"],
    "Accounting": ["customers.view", "tracking.view", "payroll.view", "reports.view"],
    "Safety Coordinator": ["employees.view", "projects.view", "ai.search"],
}

COMPANY_SUFFIXES = ["Electric", "Electrical Contractors", "Plumbing & Heating", "Mechanical", "Construction",
                    "Builders", "Development", "Contracting", "HVAC", "Properties", "Group", "Services"]


def week_ending(d: date) -> date:
    """MC Labor weeks run Saturday-Friday; the week-ending date is the Friday."""
    return d + timedelta(days=(4 - d.weekday()) % 7)


def _phone() -> str:
    return f"({random.randint(201, 989)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}"


def database_is_seeded(db: Session) -> bool:
    return db.execute(select(m.OfficeStaff.OfficeStaffID).limit(1)).first() is not None


def seed(db: Session) -> dict[str, int]:
    if database_is_seeded(db):
        return {}
    random.seed(SEED)
    Faker.seed(SEED)

    # ---- lookups ------------------------------------------------------
    divisions = {name: m.PullDownDivision(PullDownDivision=name, PullDownDivisionSort=i) for i, name in enumerate(DIVISIONS, 1)}
    db.add_all(divisions.values())
    db.flush()
    trades = {}
    for i, (name, div) in enumerate(TRADES, 1):
        t = m.PullDownTrade(PullDownTrade=name, PullDownTradeSort=i, PullDownTradeDivisionID=divisions[div].PullDownDivisionID)
        db.add(t)
        trades[name] = t
    states = {}
    for i, (code, name) in enumerate(STATES, 1):
        s = m.PullDownState(PullDownState=code, PullDownStateName=name, PullDownStateSort=i)
        db.add(s)
        states[code] = s
    db.flush()
    cities: dict[tuple[str, str], m.PullDownStateCity] = {}
    for code, names in CITIES.items():
        for i, c in enumerate(names, 1):
            sc = m.PullDownStateCity(StateID=states[code].PullDownStateID, City=c, PullDownStateCitySort=i)
            db.add(sc)
            cities[(code, c)] = sc
    emp_status = {n: m.PullDownEmployeeStatus(PullDownEmployeeStatus=n, PullDownEmployeeStatusSort=i) for i, n in enumerate(EMPLOYEE_STATUSES, 1)}
    quals = {n: m.PullDownQualification(PullDownQualification=n, PullDownQualificationSort=i) for i, n in enumerate(QUALIFICATIONS, 1)}
    exp = {n: m.PullDownExperience(PullDownExperience=n, PullDownExperienceSort=i) for i, n in enumerate(EXPERIENCE, 1)}
    lic_types = {n: m.PullDownLicenseType(PullDownLicenseType=n, PullDownLicenseTypeSort=i) for i, n in enumerate(LICENSE_TYPES, 1)}
    cust_status = {n: m.PullDownCustStatus(PulldownCustStatus=n, PulldownCustStatusSort=i) for i, n in enumerate(CUST_STATUSES, 1)}
    cust_types = {n: m.PullDownCustomerType(PullDownCustomerType=n, PullDownCustomerTypeSort=i) for i, n in enumerate(CUST_TYPES, 1)}
    sales_status = {n: m.PullDownSalesStatus(PullDownSalesStatus=n, PullDownSalesStatusSort=i) for i, n in enumerate(SALES_STATUSES, 1)}
    proj_status = {n: m.PullDownProjStatus(PullDownProjStatus=n, PullDownProjStatusSort=i) for i, n in enumerate(PROJ_STATUSES, 1)}
    wccs = {c: m.PullDownWCC(PullDownWCC=c, PullDownWCCDesc=d, PullDownWCCSort=i) for i, (c, d) in enumerate(WCC, 1)}
    payroll = {ini: m.PullDownContractWithPayrollCo(PullDownContractWith_PayrollCoName=n, PullDownContractWith_PayrollCoInitials=ini, PullDownContractWith_PayrollCoSort=i) for i, (n, ini) in enumerate(PAYROLL_COS, 1)}
    on_site = {ini: m.PullDownPayrollCoOnSite(PullDownPayrollCoOnSiteName=n, PullDownPayrollCoOnSiteInitials=ini, PullDownPayrollCoOnSiteSort=i) for i, (n, ini) in enumerate(PAYROLL_COS, 1)}
    flags = {f: m.PullDownStatusFlag(PullDownStatusFlag=f, PullDownStatusFlagDesc=d, PullDownStatusFlagSort=i) for i, (f, d) in enumerate(STATUS_FLAGS, 1)}
    titles = {n: m.PullDownCustomerContactTitle(PullDownCustomerContactTitle=n, PullDownCustomerContactTitleSort=i) for i, n in enumerate(CONTACT_TITLES, 1)}
    note_types = {n: m.PullDownEmployeeNoteType(PullDownEmployeeNoteType=n, PullDownEmployeeNoteTypeSort=i) for i, n in enumerate(NOTE_TYPES, 1)}
    features = {}
    for i, (obj, title, desc) in enumerate(FEATURES, 1):
        f = m.Feature(ObjectName=obj, FeatureTitle=title, FeatureDescription=desc, FeatureSort=i)
        db.add(f)
        features[obj] = f
    for group in (emp_status, quals, exp, lic_types, cust_status, cust_types, sales_status, proj_status, wccs, payroll,
                  on_site, flags, titles, note_types):
        db.add_all(group.values())
    db.flush()

    # ---- office staff (application users) -----------------------------
    pw = hash_password(settings.demo_password)
    staff: list[m.OfficeStaff] = []
    admin = m.OfficeStaff(
        OfficeStaffFirstName="Demo", OfficeStaffLastName="Administrator", OfficeStaffFullName="Demo Administrator",
        OfficeStaffPassword=pw, OfficeStaffCanDelete=True, Profile=True, OfficeStaffActive=True, Initials="ADMIN",
        OfficeStaffTitle="Administrator", OfficeStaffEmail="admin@mclabor.demo", OfficeStaffEmployeeResearch=True,
        OfficeStaffTrackingReportEmailReceive=True,
    )
    db.add(admin)
    staff.append(admin)
    roles = ["Office Manager"] * 2 + ["Recruiter"] * 7 + ["Sales Representative"] * 7 + ["Dispatcher"] * 5 + \
            ["Payroll Specialist"] * 4 + ["Accounting"] * 3 + ["Safety Coordinator"] * 2 + ["Administrator"] * 1
    used_initials = {"ADMIN"}
    for role in roles:
        first, last = fake.first_name(), fake.last_name()
        ini = (first[0] + last[0]).upper()
        n = 2
        base = ini
        while ini in used_initials:
            ini = f"{base}{n}"
            n += 1
        used_initials.add(ini)
        s = m.OfficeStaff(
            OfficeStaffFirstName=first, OfficeStaffLastName=last, OfficeStaffFullName=f"{first} {last}",
            OfficeStaffPassword=pw, OfficeStaffCanDelete=role in ("Administrator", "Office Manager"),
            Profile=role == "Administrator", OfficeStaffActive=random.random() > 0.08, Initials=ini,
            OfficeStaffTitle=role, OfficeStaffEmail=f"{first.lower()}.{last.lower()}@mclabor.demo",
            OfficeStaffEmployeeResearch=role in ("Recruiter", "Office Manager"),
            OfficeStaffHideHours=role in ("Safety Coordinator",),
            OfficeStaffTrackingReportEmailReceive=role in ("Office Manager", "Dispatcher", "Administrator"),
        )
        db.add(s)
        staff.append(s)
    db.flush()
    for s in staff:
        role = s.OfficeStaffTitle
        for obj in ROLE_FEATURES.get(role, []):
            db.add(m.OfficeStaffPermission(OfficeStaffID=s.OfficeStaffID, FeatureID=features[obj].FeatureID))

    # salesmen = sales reps + office managers
    salesmen: list[m.PullDownSalesman] = []
    for i, s in enumerate([x for x in staff if x.OfficeStaffTitle in ("Sales Representative", "Office Manager")], 1):
        sm = m.PullDownSalesman(
            PullDownSalesmanFName=s.OfficeStaffFirstName, PullDownSalesmanLName=s.OfficeStaffLastName,
            PullDownSalesmanTitle=s.OfficeStaffTitle, PullDownSalesmanEmail=s.OfficeStaffEmail, PullDownSalesmanCell=_phone(),
            PullDownSalesmanSort=i, OfficeStaffID=s.OfficeStaffID, PullDownSalesmanActive=s.OfficeStaffActive,
        )
        db.add(sm)
        salesmen.append(sm)
    db.flush()

    staff_initials = [s.Initials for s in staff if s.OfficeStaffActive]

    # ---- employees ----------------------------------------------------
    employees: list[m.Employee] = []
    trade_names = [t[0] for t in TRADES]
    trade_weights = [18, 12, 8, 4, 3, 3, 12, 14, 4, 3, 3, 3, 3, 5, 5]
    for i in range(170):
        state = random.choices(["MA", "CT", "RI", "NH", "NY", "ME", "VT"], weights=[55, 12, 10, 10, 6, 4, 3])[0]
        city = random.choice(CITIES[state])
        trade = random.choices(trade_names, weights=trade_weights)[0]
        years = random.choices([0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25], weights=[6, 8, 9, 9, 8, 8, 8, 8, 8, 7, 6, 4, 2])[0]
        exp_name = EXPERIENCE[0] if years <= 2 else EXPERIENCE[1] if years <= 5 else EXPERIENCE[2] if years <= 10 else EXPERIENCE[3]
        qual = ("Helper" if years < 1 else "Apprentice" if years < 4 else random.choices(["Journeyman", "Master", "Foreman"], weights=[6, 2, 1])[0])
        status = random.choices(EMPLOYEE_STATUSES, weights=[20, 25, 35, 10, 8, 2])[0]
        licensed = trade in ("Electrician", "Plumber", "HVAC Technician", "Sprinkler Fitter", "Equipment Operator") and years >= 4 and random.random() < 0.8
        first, last = fake.first_name(), fake.last_name()
        base_rate = {"Helper": 19, "Apprentice": 24, "Journeyman": 34, "Master": 44, "Foreman": 42}[qual] + random.randint(-3, 6)
        e = m.Employee(
            EmFirstName=first, EmLastName=last, EmMiddle=random.choice([None, None, fake.first_name()[0]]),
            EmStreet=fake.street_address(), EmStateCityID=cities[(state, city)].PullDownStateCityID, EmCity=city,
            EmState=state, EmZip=fake.postcode(), EmHomePhone=_phone() if random.random() < 0.4 else None,
            EmMobilePhone=_phone(), EmEmail=f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@example.com",
            EmEmployeeStatusID=emp_status[status].PullDownEmployeeStatusID,
            EmQualificationID=quals[qual].PullDownQualificationID, EmTradeID=trades[trade].PullDownTradeID,
            SubTrade1ID=trades[random.choice(trade_names)].PullDownTradeID if random.random() < 0.35 else None,
            EmExperienceID=exp[exp_name].PullDownExperienceID, YearsInTrade=years,
            EmLicenseNum=f"{random.choice(['JE', 'ME', 'JP', 'MP', 'RF', 'HE'])}-{random.randint(10000, 99999)}" if licensed else None,
            EmLicenseDateExpires=date.today() + timedelta(days=random.randint(-60, 900)) if licensed else None,
            EmLicensedIn=state if licensed else None,
            OSHA10=random.choice(["OSHA 10", "OSHA 30"]) if random.random() < 0.7 else None,
            BaseSalary=base_rate, EmDOB=fake.date_of_birth(minimum_age=19, maximum_age=62),
            EmReferredBy=random.choice([None, "Indeed", "Craigslist", "Walk-in", "Employee referral", "Union hall", "Trade school"]),
            EmContractWith_PayrollCoID=random.choice(list(payroll.values())).PullDownContractWith_PayrollCoID,
            USCitizen=random.random() < 0.9, I9Complete=random.random() < 0.85, JobApplComplete=random.random() < 0.9,
            EmApplComplete=random.random() < 0.9, Recruiter=False,
            PostEmployeeAsAvailable=status == "Available" or (status == "Active" and random.random() < 0.3),
            EmployeeNoCommunication=random.random() < 0.05,
            WillTravel=random.choice(["Yes", "Yes", "No", "Within 50 miles", "Statewide", None]),
            EmAdminNotes=random.choice([None, None, "Reliable, always on time.", "Needs reminder for timesheets.",
                                        "Prefers commercial work.", "Has own truck and tools.", "Available for night shift.",
                                        "Bilingual English/Spanish.", "Strong references from last two jobs.",
                                        "Requested no out-of-state work."]),
            EmEntryUserName=random.choice(staff_initials),
            EmEntryTimestamp=datetime.now() - timedelta(days=random.randint(5, 1500)),
        )
        db.add(e)
        employees.append(e)
    db.flush()
    for e in employees:
        if e.EmLicenseNum:
            trade_name = e.trade.PullDownTrade if e.trade else "Electrician"
            lt = {"Electrician": ["Journeyman Electrician", "Master Electrician"], "Plumber": ["Journeyman Plumber", "Master Plumber"],
                  "HVAC Technician": ["HVAC / Refrigeration"], "Sprinkler Fitter": ["Sprinkler Fitter"],
                  "Equipment Operator": ["Hoisting Engineer"]}.get(trade_name, ["Construction Supervisor (CSL)"])
            db.add(m.EmployeeLicense(
                EmployeeID=e.EmployeeID, EmployeeLicenseStateID=states[e.EmState].PullDownStateID,
                EmployeeLicenseTradeID=e.EmTradeID, EmployeeLicenseTypeID=lic_types[random.choice(lt)].PullDownLicenseTypeID,
                EmployeeLicenseNumber=e.EmLicenseNum, EmployeeLicenseExpDate=e.EmLicenseDateExpires,
                EmployeeLicenseCopyOnFile=random.choice(["Yes", "Yes", "No"]),
            ))
            if random.random() < 0.25:
                db.add(m.EmployeeLicense(
                    EmployeeID=e.EmployeeID, EmployeeLicenseStateID=states[random.choice(["MA", "CT", "RI", "NH"])].PullDownStateID,
                    EmployeeLicenseTradeID=e.EmTradeID, EmployeeLicenseTypeID=lic_types["Construction Supervisor (CSL)"].PullDownLicenseTypeID,
                    EmployeeLicenseNumber=f"CS-{random.randint(100000, 999999)}",
                    EmployeeLicenseExpDate=date.today() + timedelta(days=random.randint(30, 700)),
                    EmployeeLicenseCopyOnFile="Yes",
                ))
        for _ in range(random.randint(0, 3)):
            db.add(m.EmployeeNote(
                EmployeeID=e.EmployeeID,
                EmployeeNote=random.choice([
                    "Called to confirm availability for next week.", "Completed onboarding paperwork.",
                    "Customer reported excellent work quality.", "Late twice this month - discussed.",
                    "Renewed OSHA card.", "Asked for a raise review after 90 days.", "Left voicemail re: new assignment.",
                    "Reference check completed - positive.", "Prefers jobs south of Boston.", "Updated mobile number.",
                ]),
                EmployeeNoteUserName=random.choice(staff_initials),
                EmployeeNoteTimestamp=datetime.now() - timedelta(days=random.randint(0, 400), hours=random.randint(0, 23)),
                EmployeeNoteTypeID=random.choice(list(note_types.values())).PullDownEmployeeNoteTypeID,
            ))

    # ---- customers ----------------------------------------------------
    customers: list[m.Customer] = []
    used_names: set[str] = set()
    for i in range(64):
        state = random.choices(["MA", "CT", "RI", "NH", "NY", "ME", "VT"], weights=[60, 12, 10, 8, 5, 3, 2])[0]
        city = random.choice(CITIES[state])
        ctype = random.choices(CUST_TYPES, weights=[25, 15, 25, 10, 8, 9, 8])[0]
        suffix = {"Electrical Contractor": ["Electric", "Electrical Contractors"], "Plumbing Contractor": ["Plumbing & Heating", "Plumbing"],
                  "General Contractor": ["Construction", "Builders", "Contracting"], "HVAC Contractor": ["HVAC", "Mechanical"],
                  "Mechanical Contractor": ["Mechanical", "Mechanical Systems"], "Property Manager": ["Properties", "Property Management"],
                  "Developer": ["Development", "Group"]}[ctype]
        name = f"{fake.last_name()} {random.choice(suffix)}"
        while name in used_names:
            name = f"{fake.last_name()} {random.choice(suffix)}"
        used_names.add(name)
        status = random.choices(CUST_STATUSES, weights=[55, 20, 15, 7, 3])[0]
        domain = name.lower().replace(" & ", "").replace(" ", "").replace("-", "")[:18]
        c = m.Customer(
            CustBusName=name, Street=fake.street_address(), StateCityID=cities[(state, city)].PullDownStateCityID,
            City=city, State=state, Zip=fake.postcode(), Phone=_phone(), CustEmail=f"office@{domain}.example.com",
            CustFaxNum=_phone() if random.random() < 0.3 else None, CustWebSiteHLink=f"https://www.{domain}.example.com",
            CustStatusID=cust_status[status].PulldownCustStatusID, CustomerTypeID=cust_types[ctype].PullDownCustomerTypeID,
            SalesmanID=random.choice(salesmen).PullDownSalesmanID,
            SalesStatusID=sales_status[random.choice(SALES_STATUSES) if status != "Active" else "Active Account"].PullDownSalesStatusID,
            CustContractWith_PayrollCoID=random.choice(list(payroll.values())).PullDownContractWith_PayrollCoID,
            ContractOnFile=status == "Active" and random.random() < 0.85 or random.random() < 0.2,
            ContractDate=date.today() - timedelta(days=random.randint(30, 2000)) if status != "Prospect" else None,
            CreditLimit=random.choice([5000, 10000, 15000, 25000, 50000, 100000]),
            RevenuePerYear=random.choice([0, 12000, 35000, 60000, 90000, 150000, 240000, 400000, 750000]) if status != "Prospect" else 0,
            LaborRateAFrom=52, LaborRateATo=68, LaborRateBFrom=40, LaborRateBTo=52, BillRateOTMultiplier=1.5,
            Industry=random.choice(INDUSTRIES), EmployeeSize=random.choice(["1-10", "11-50", "51-200", "200+"]),
            CustomerDescription=fake.catch_phrase(),
            CustomerNote=random.choice([None, "Pays net 30, always on time.", "Prefers e-mailed timesheets.",
                                        "Requires OSHA 30 for foremen.", "Large hospital project starting next spring.",
                                        "Call before sending new workers - gate check-in required.", "Ask for PM, not office."]),
            InvoiceNote=random.choice([None, "PO number required on invoice.", "Weekly invoicing.", "Bill to corporate office."]),
            CollectionsNote="Two invoices over 60 days - follow up weekly." if status == "Collections" else None,
            OnHold=status in ("Collections", "Do Not Use") or random.random() < 0.04,
            FutureSales=status == "Prospect" or random.random() < 0.2,
            FutureCall=date.today() + timedelta(days=random.randint(1, 60)) if random.random() < 0.4 else None,
            CustomerLicenseNumber=f"{random.choice(['A', 'B', 'CS'])}-{random.randint(10000, 99999)}" if random.random() < 0.6 else None,
            CustEntryUserName=random.choice(staff_initials),
            CustEntryTimestamp=datetime.now() - timedelta(days=random.randint(10, 2500)),
        )
        db.add(c)
        customers.append(c)
    db.flush()
    for c in customers:
        for pri in range(1, random.randint(2, 4)):
            first, last = fake.first_name(), fake.last_name()
            db.add(m.CustomerContact(
                CustomerID=c.CustomerID, CustomerContactPriority=pri, CustomerContactFName=first, CustomerContactLName=last,
                CustomerContactTitleID=random.choice(list(titles.values())).PullDownCustomerContactTitleID,
                CustomerContactEmail=f"{first[0].lower()}{last.lower()}@{c.CustEmail.split('@')[1]}",
                CustomerContactCell=_phone(), CustomerContactOfficePhone=c.Phone if pri == 1 else None,
                CustomerContactUserName=random.choice(staff_initials),
            ))
        for _ in range(random.randint(0, 3)):
            db.add(m.CustomerNote(
                CustomerID=c.CustomerID,
                CustomerNote=random.choice(["Quoted 3 electricians for spring project.", "Sent updated rate sheet.",
                                            "Requested certificate of insurance.", "Met PM on site - happy with crew.",
                                            "Needs two laborers starting Monday.", "Invoice dispute resolved.",
                                            "Left message about renewal of contract."]),
                CustomerNoteUserName=random.choice(staff_initials),
                CustomerNoteTimestamp=datetime.now() - timedelta(days=random.randint(0, 300)),
            ))

    # ---- projects -----------------------------------------------------
    projects: list[m.Project] = []
    site_words = ["Medical Center", "Elementary School", "Apartments", "Office Park", "Distribution Center", "Mixed-Use Building",
                  "Parking Garage", "Hotel", "Lab Building", "Town Hall", "Retail Plaza", "Senior Living", "Fire Station",
                  "Water Treatment Plant", "Condominiums", "High School Addition", "Warehouse", "Data Center", "Library", "Bridge Rehab"]
    type_wcc = {"Electrical Contractor": "5190", "Plumbing Contractor": "5183", "HVAC Contractor": "5537", "Mechanical Contractor": "5537",
                "General Contractor": "5403", "Property Manager": "5474", "Developer": "5213"}
    for i in range(95):
        c = random.choice([x for x in customers if x.status.PulldownCustStatus in ("Active", "Inactive", "Collections")] or customers)
        state = c.State if random.random() < 0.8 else random.choice(["MA", "CT", "RI", "NH"])
        city = random.choice(CITIES[state])
        status = random.choices(PROJ_STATUSES, weights=[12, 45, 8, 30, 5])[0]
        start = date.today() + timedelta(days=random.randint(-400, 10)) if status != "Pending" else date.today() + timedelta(days=random.randint(3, 75))
        length = random.randint(14, 300)
        end = start + timedelta(days=length)
        if status == "Completed":
            end = min(end, date.today() - timedelta(days=random.randint(1, 60)))
        headcount = random.randint(1, 8)
        p = m.Project(
            CustomerID=c.CustomerID, SiteName=f"{fake.last_name()} {random.choice(site_words)}",
            SiteStreet=fake.street_address(), SiteStateCityID=cities[(state, city)].PullDownStateCityID, SiteCity=city,
            SiteState=state, SiteZip=fake.postcode(), StartDate=start, EndDate=end,
            ProjStatusID=proj_status[status].PullDownProjStatusID,
            ProjectWCCID=wccs[type_wcc.get(c.customer_type.PullDownCustomerType, "5403")].PullDownWCCID,
            ProjNote=random.choice([None, "Hard hats and vests required.", "Check in with superintendent trailer.",
                                    "Night shift 7pm-3am.", "Prevailing wage job.", "Parking off-site - shuttle provided.",
                                    "Badging required - bring ID.", "Union site - non-union workers OK in trades listed."]),
            JobNote=random.choice([None, "Need rough-in crew first two weeks.", "Finish work only.", "Service calls, various sites."]),
            ProjStartTime=random.choice(["6:00 AM", "6:30 AM", "7:00 AM", "7:30 AM", "7:00 PM"]),
            OCIPJob=random.random() < 0.15, RateJob=random.random() < 0.2, ShiftDifferential=random.random() < 0.1,
            JobBeingManned=status == "Active" and random.random() < 0.8, GCOnSite=random.random() < 0.5,
            ARateQty=random.randint(0, 3), BRateQty=random.randint(0, 4), CRateQty=random.randint(0, 3),
            NumberOfEmployees=headcount, ContractAmount=random.choice([None, 25000, 60000, 120000, 250000, 480000]),
            CustomerContact=f"{fake.first_name()} {fake.last_name()}", CustomerPhone=_phone(),
            ProjectEntryUserName=random.choice(staff_initials),
            ProjectEntryTimestamp=datetime.combine(start, datetime.min.time()) - timedelta(days=random.randint(3, 40)),
        )
        db.add(p)
        projects.append(p)
    db.flush()

    # ---- tracking (weekly assignments, last 14 weeks + next) -------------
    this_we = week_ending(date.today())
    active_projects = [p for p in projects if p.status.PullDownProjStatus in ("Active", "Completed")]
    workers = [e for e in employees if e.status.PullDownEmployeeStatus in ("Active", "On Assignment", "Available")]
    count = 0
    for wk in range(-14, 2):
        we = this_we + timedelta(weeks=wk)
        iso = we.isocalendar()
        pool = random.sample(workers, k=min(len(workers), random.randint(45, 70)))
        for e in pool:
            cands = [p for p in active_projects if p.StartDate and p.StartDate <= we and (p.EndDate is None or p.EndDate >= we - timedelta(days=6))]
            if not cands:
                continue
            p = random.choice(cands)
            pay = float(e.BaseSalary or 25)
            bill = round(pay * random.choice([1.45, 1.5, 1.55, 1.6]), 2)
            t = m.Tracking(
                CustomerID=p.CustomerID, EmployeeID=e.EmployeeID, ProjectID=p.ProjectID,
                AssignWeek=iso.week, AssignYear=iso.year, WeekEndingDate=we,
                PayrollCoOnSiteID=random.choice(list(on_site.values())).PullDownPayrollCoOnSiteID,
                PayRate=pay, OTPayRate=round(pay * 1.5, 2), BillRate=bill, BillRateOT=round(bill * 1.5, 2),
                WCC=p.wcc.PullDownWCC if p.wcc else None, Grade=random.choice(["A", "B", "C"]),
                DirectionsSentEmail=random.random() < 0.8, DirectionsSentText=random.random() < 0.6, DirVerified=random.random() < 0.7,
                PayrollInfoSent=wk < 0, Placeholder=False, AssignmentUserName=random.choice(staff_initials),
                AssignmentTimestamp=datetime.combine(we - timedelta(days=random.randint(5, 9)), datetime.min.time()),
            )
            if wk < 1:
                for day in ("MonHours", "TueHours", "WedHours", "ThuHours", "FriHours"):
                    setattr(t, day, random.choices([8, 8, 8, 10, 0, 6, 9], weights=[40, 20, 10, 10, 8, 6, 6])[0])
                if random.random() < 0.15:
                    t.SatHours = random.choice([4, 6, 8])
                t.MonStatusFlagID = flags["W"].PullDownStatusFlagID
            t.recompute()
            db.add(t)
            count += 1
    db.commit()
    return {"staff": len(staff), "employees": len(employees), "customers": len(customers), "projects": len(projects), "tracking": count}
