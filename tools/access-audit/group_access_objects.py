"""Clean and group the Access object inventory by functional area (names only; no data)."""
import re
import sys
from collections import defaultdict
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
raw = [l.strip() for l in src.read_text(encoding="utf-8").splitlines()[4:] if l.strip()]

def clean(n: str) -> str | None:
    n = re.sub(r"(.)\1{6,}$", "", n)          # deleted-object remnants: name + 11 repeated characters
    n = re.sub(r"\d+$", "", n)                 # numbered copies (frmX1, frmX4)
    n = re.sub(r"(Holding|Copy|Old|Test|Backup|TEMP|Temp|_bak|zz+)$", "", n)
    if len(n) < 6:
        return None
    return n

names = sorted({c for c in (clean(n) for n in raw) if c})
forms = [n for n in names if re.match(r"^(frm|sfrm|fsub)", n)]
reports = [n for n in names if re.match(r"^(rpt|srpt)", n)]
queries = [n for n in names if n.startswith("qry")]

AREAS = [
    ("Employees: record, search, notes, licenses, contacts", r"Employee(?!.*(Payroll|Health|Insurance|Unemploy|Adjust|Advance|401|Four01|Sick|Vacation|Referral|Research|Bio|Accident))|Licens|Emp(?!loy)"),
    ("Customers: record, search, contacts, notes, sales", r"Customer(?!.*(Payment|Invoice|AR|Receivable|Deposit|Permit|Insurance|Research|Week))|Cust(?!.*(Payment|Invoice))|Sales(?!man)|Foreman|Prospect"),
    ("Jobs / projects: record, search, site, GC, NOI/NOC, permits", r"Project|Job|Site|NOI|NOC|Lien|Permit|GeneralContractor|GCVerif|Owner"),
    ("Weekly tracking / assignments / dispatch", r"Tracking|Assign|Placeholder|Week(?!ly)|Hours|Directions|Dispatch|Schedule"),
    ("Payroll: checks, adjustments, advances, sick/vacation, 401k, crosschecks, certified payroll", r"Payroll|Paycheck|Check(?!list)|Adjust|Advance|Sick|Vacation|401|Four01|Crosscheck|Certified|Timesheet|Exclusion|Garnish|Deduct"),
    ("Invoicing / accounts receivable / payments / deposits / QuickBooks", r"Invoice|Receivable|\bAR\b|Payment|Deposit|QuickBooks|\bQB|Aging|Credit|Collection|Statement|Billing|Accounting"),
    ("Workers' comp / insurance / certificates / accident reports", r"WCC|Insurance|Certificate|Accident|Claim|OCIP|Policy|Policies"),
    ("Sales commissions / clusters / referral agencies", r"Commission|Cluster|Referral|Agency|Salesman"),
    ("Health insurance / benefits / unemployment", r"Health|Benefit|Unemploy|Covid"),
    ("Reports menu, e-mail/letter templates, mail merge", r"Report(?!s?Email)|Template|Letter|Email|Mail|Newsletter|Print|Label|Export|Excel"),
    ("Users, permissions, logins, settings, help/KB", r"OfficeStaff|Permission|Login|Setting|Feature|Help|KB|Shortcut|Alert|Reminder|Message|Concurrent|Switchboard|Main|Menu|Navigation|Splash|About"),
    ("Lookup tables (PullDown) maintenance", r"PullDown|Lookup|List(?!Index)"),
    ("Imports, research, mileage, tools, other", r"Import|Research|Mileage|Tool|TruePeople|Map|Alias|AKA|Bio|Question|School|Reference|Interview|Application"),
]

def group(items):
    out = defaultdict(list)
    for n in items:
        placed = False
        for title, pat in AREAS:
            if re.search(pat, n, re.I):
                out[title].append(n); placed = True; break
        if not placed:
            out["Unclassified"].append(n)
    return out

with dst.open("w", encoding="utf-8") as f:
    f.write(f"raw names {len(raw)}; cleaned distinct {len(names)}; forms {len(forms)}; reports {len(reports)}; queries {len(queries)}\n\n")
    for label, items in (("FORMS", forms), ("REPORTS", reports)):
        g = group(items)
        f.write(f"== {label} ==\n")
        for title, _ in AREAS + [("Unclassified", "")]:
            lst = g.get(title, [])
            if lst:
                f.write(f"-- {title}: {len(lst)}\n   {', '.join(lst[:60])}{' ...' if len(lst) > 60 else ''}\n")
        f.write("\n")
    g = group(queries)
    f.write("== QUERIES (counts only) ==\n")
    for title, _ in AREAS + [("Unclassified", "")]:
        if g.get(title):
            f.write(f"-- {title}: {len(g[title])}\n")
print(dst)
