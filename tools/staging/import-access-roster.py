"""Loads a staff roster (identity,role) into the website's access store for one environment. No restart needed.

    powershell -File tools\\staging\\run-readonly.ps1 -EnvFile backend\\.env.production ..\\tools\\staging\\import-access-roster.py roster.csv [--apply]

Without --apply it only reports what would change and the resulting seat count. Identities are resolved against
the environment's staff table (initials, OfficeStaffID or e-mail); unknown or inactive people are listed and
skipped. Refuses to exceed ACCESS_SEAT_LIMIT. Nothing is written to the McLabor database.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import func, or_, select  # noqa: E402

from app import models as m  # noqa: E402
from app import webauth  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402

assert settings.is_sql_server, "the access store applies to staging or production (the demo uses its own permissions)"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path, apply = Path(sys.argv[1]), "--apply" in sys.argv
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(line for line in fh if not line.startswith("#")):
            ident, role = (r.get("identity") or "").strip(), (r.get("role") or "").strip().lower()
            if ident and role in ("admin", "user"):
                rows.append((ident, role))
    current = webauth.access_roles()
    plan, unknown = [], []
    with SessionLocal() as db:
        for ident, role in rows:
            i = ident.lower()
            conds = [func.lower(m.OfficeStaff.Initials) == i, func.lower(m.OfficeStaff.OfficeStaffEmail) == i]
            if ident.isdigit():
                conds.append(m.OfficeStaff.OfficeStaffID == int(ident))
            staff = db.execute(select(m.OfficeStaff).where(or_(*conds))).scalars().first()
            if staff is None or not staff.OfficeStaffActive:
                unknown.append(ident)
                continue
            plan.append((staff.OfficeStaffID, staff.Initials, staff.OfficeStaffEmail, role, current.get(staff.OfficeStaffID)))
    new_people = {sid for sid, *_ in plan if sid not in current}
    bootstrap = len(settings.web_admin_set | settings.web_user_set)
    after = bootstrap + len(set(current) | new_people)
    print(f"{len(rows)} roster line(s): {len(plan)} resolved, {len(unknown)} unknown or inactive{': ' + ', '.join(unknown) if unknown else ''}")
    for sid, ini, _email, role, old in plan:
        print(f"  {ini:6} OfficeStaffID {sid:<6} {old or 'none':5} -> {role}")
    print(f"authorized after import: {after}" + (f" of {settings.access_seat_limit}" if settings.access_seat_limit else ""))
    if settings.access_seat_limit and after > settings.access_seat_limit:
        print(f"REFUSED: that exceeds ACCESS_SEAT_LIMIT={settings.access_seat_limit}. Nothing was changed.")
        return 1
    if not apply:
        print("Dry run. Add --apply to write these roles to the access store.")
        return 0
    for sid, ini, email, role, _old in plan:
        webauth.set_access(sid, role, by="roster import", initials=ini, email=email)
    print(f"Applied {len(plan)} role(s). Effective on each person's next request; no restart needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
