"""Web sign-in credentials, kept apart from the business database.

The Access application stores staff passwords in ``tblOfficeStaff.OfficeStaffPassword``.
The web app never reads or writes that column.  Web passwords live in a small local
database of their own (``backend/web_auth.db`` by default), keyed by OfficeStaffID:

* nothing has to be created or changed in the McLabor SQL Server database;
* the SQL login used by the web app needs no access to the password column;
* it works the same in demo mode and in read-only production mode.

Who a user *is* (name, active flag, admin flag, permissions) still comes from
``tblOfficeStaff`` / ``tblOfficeStaffPermission``.  Only the password check is here.

Command line (run from the backend folder):

    .venv\\Scripts\\python.exe -m app.webauth set-password INITIALS    (asks twice, hidden)
    .venv\\Scripts\\python.exe -m app.webauth list
"""
from __future__ import annotations

import hmac
import sys
from datetime import datetime, timedelta

from sqlalchemy import Boolean, DateTime, Integer, String, select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings
from .security import hash_password, verify_password

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
_DUMMY_HASH = hash_password("not-a-real-password")  # keeps timing similar for unknown users


class AuthBase(DeclarativeBase):
    pass


class WebCredential(AuthBase):
    __tablename__ = "web_credentials"
    staff_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # tblOfficeStaff.OfficeStaffID
    password_hash: Mapped[str] = mapped_column(String(300))
    must_change: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class WebAccess(AuthBase):
    """Who may use the website with real data, decided by an administrator in the website itself (Users page or the
    command line), so that adding or removing a person needs no settings change, no restart and no redeploy.
    The settings-file lists (WEB_ADMINS / WEB_USERS) remain the bootstrap administrators. One row per staff member."""

    __tablename__ = "web_access"
    staff_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # tblOfficeStaff.OfficeStaffID
    role: Mapped[str] = mapped_column(String(10))                     # "admin" | "user"
    initials: Mapped[str | None] = mapped_column(String(10))
    email: Mapped[str | None] = mapped_column(String(120))
    granted_by: Mapped[str | None] = mapped_column(String(50))
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)   # last request by this person (unique-user count)


# Access roles are read on every request: a short in-process memory keeps the local store from being hit each time.
_ACCESS_TTL_SECONDS = 15
_access_cache: dict[str, tuple[float, dict[int, str]]] = {}
_seen_recently: dict[int, float] = {}


def access_roles() -> dict[int, str]:
    """{staff_id: role} from the store (cached for a few seconds; cleared by every change)."""
    import time

    now = time.monotonic()
    hit = _access_cache.get("roles")
    if hit and now - hit[0] < _ACCESS_TTL_SECONDS:
        return hit[1]
    with _session() as s:
        roles = {r.staff_id: r.role for r in s.execute(select(WebAccess)).scalars()}
    _access_cache["roles"] = (now, roles)
    return roles


def clear_access_cache() -> None:
    _access_cache.clear()


def set_access(staff_id: int, role: str | None, by: str | None, initials: str | None = None, email: str | None = None) -> None:
    """Grant ("admin" / "user") or remove (None) website access for a staff member. Takes effect on the next request."""
    if role not in ("admin", "user", None):
        raise ValueError("role must be admin, user or None")
    with _session() as s:
        row = s.get(WebAccess, staff_id)
        if role is None:
            if row is not None:
                s.delete(row)
        else:
            if row is None:
                row = WebAccess(staff_id=staff_id)
                s.add(row)
            row.role, row.granted_by, row.granted_at = role, by, datetime.utcnow()
            if initials:
                row.initials = initials
            if email:
                row.email = email.strip().lower()
        s.commit()
    clear_access_cache()


def list_access() -> list[dict]:
    with _session() as s:
        return [{"staff_id": r.staff_id, "role": r.role, "initials": r.initials, "email": r.email, "granted_by": r.granted_by,
                 "granted_at": r.granted_at, "last_seen_at": r.last_seen_at} for r in s.execute(select(WebAccess).order_by(WebAccess.role, WebAccess.initials)).scalars()]


def touch_seen(staff_id: int) -> None:
    """Record that this person used the website (at most once every 10 minutes per person; feeds the unique-user count)."""
    import time

    now = time.monotonic()
    if now - _seen_recently.get(staff_id, -1e9) < 600:
        return
    _seen_recently[staff_id] = now
    with _session() as s:
        row = s.get(WebAccess, staff_id)
        if row is not None:
            row.last_seen_at = datetime.utcnow()
            s.commit()


def unique_users_this_month() -> int:
    """People with website access who have used it since the first of the month (what a per-seat sign-in service counts)."""
    start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with _session() as s:
        return len(s.execute(select(WebAccess.staff_id).where(WebAccess.last_seen_at >= start)).all())


_engine = None
_Session: sessionmaker | None = None


def _session() -> Session:
    global _engine, _Session
    if _Session is None:
        from .database import make_engine

        _engine = make_engine(settings.web_auth_url)
        try:
            AuthBase.metadata.create_all(_engine)
        except (IntegrityError, ProgrammingError):
            # Several worker processes start at once on a fresh database and all try to create the tables; the first one
            # wins and the others see "already exists". Fine as long as the tables are there now.
            from sqlalchemy import inspect

            if not all(inspect(_engine).has_table(t) for t in AuthBase.metadata.tables):
                raise
        _Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _Session()


def reset_for_tests(url: str | None = None) -> None:
    """Drop the cached engine (tests point the store at a temporary file)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = _Session = None
    if url:
        settings.web_auth_database_url = url


def min_password_length() -> int:
    return 12 if settings.is_real_data else 6


def password_problem(password: str, initials: str | None = None) -> str | None:
    """Returns a human-readable reason the password is not acceptable, or None."""
    n = min_password_length()
    if len(password) < n:
        return f"Password must be at least {n} characters"
    if initials and password.strip().lower() == initials.strip().lower():
        return "Password cannot be the same as your initials"
    if settings.is_real_data and password == settings.demo_password:
        return "The demo password cannot be used"
    return None


def has_password(staff_id: int) -> bool:
    with _session() as s:
        return s.get(WebCredential, staff_id) is not None


def set_password(staff_id: int, password: str, must_change: bool = False) -> None:
    with _session() as s:
        cred = s.get(WebCredential, staff_id)
        if cred is None:
            cred = WebCredential(staff_id=staff_id, password_hash="")
            s.add(cred)
        cred.password_hash = hash_password(password)
        cred.must_change = must_change
        cred.failed_attempts = 0
        cred.locked_until = None
        cred.password_changed_at = datetime.utcnow()
        s.commit()


def bootstrap_first_admin(staff_id: int | None, initials: str | None, email: str | None, offered: str) -> bool:
    """First sign-in on a fresh real-data deployment: WEB_BOOTSTRAP_PASSWORD (a sealed, one-time setting) is accepted as
    the password of the FIRST name in WEB_ADMINS while that person has no web password yet. It is stored as their
    password with "must change" set, so the sign-in continues with choosing a real one. It never replaces an existing
    password and never applies to anyone else. Returns True when it was just applied."""
    pw = (settings.web_bootstrap_password or "").strip()
    first = next((a.strip().lower() for a in (settings.web_admins or "").split(",") if a.strip()), "")
    if not pw or len(pw) < 16 or not first or staff_id is None or not settings.is_real_data:
        return False
    if first not in ((initials or "").strip().lower(), (email or "").strip().lower()):
        return False
    if not hmac.compare_digest(offered.encode(), pw.encode()):
        return False
    with _session() as s:
        if s.get(WebCredential, staff_id) is not None:
            return False
    set_password(staff_id, pw, must_change=True)
    return True


def import_hash(staff_id: int, password_hash: str) -> None:
    """Demo only: carry over a hash that is already in this app's own format."""
    with _session() as s:
        if s.get(WebCredential, staff_id) is None:
            s.add(WebCredential(staff_id=staff_id, password_hash=password_hash))
            s.commit()


def check_password(staff_id: int | None, password: str) -> tuple[str, bool]:
    """Returns (result, must_change).  result: 'ok' | 'bad' | 'locked' | 'not-set'."""
    if staff_id is None:
        verify_password(password, _DUMMY_HASH)
        return "bad", False
    with _session() as s:
        cred = s.get(WebCredential, staff_id)
        if cred is None:
            verify_password(password, _DUMMY_HASH)
            return "not-set", False
        now = datetime.utcnow()
        if cred.locked_until and cred.locked_until > now:
            return "locked", False
        if verify_password(password, cred.password_hash):
            cred.failed_attempts = 0
            cred.locked_until = None
            cred.last_login_at = now
            s.commit()
            return "ok", bool(cred.must_change)
        cred.failed_attempts = (cred.failed_attempts or 0) + 1
        if cred.failed_attempts >= MAX_FAILED_ATTEMPTS:
            cred.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            cred.failed_attempts = 0
        s.commit()
        return "bad", False


def account_count() -> int:
    with _session() as s:
        return len(s.execute(select(WebCredential.staff_id)).all())


def demo_password_holders() -> int:
    """How many stored web passwords are the publicly known demo password (must be 0 in production)."""
    with _session() as s:
        hashes = [h for (h,) in s.execute(select(WebCredential.password_hash))]
    return sum(1 for h in hashes if verify_password(settings.demo_password, h))


def ensure_demo_credentials(db: Session) -> int:
    """Demo data only: every synthetic user can sign in with the demo password.

    Never runs against production - real staff get a web password from an administrator.
    """
    if settings.is_real_data:
        return 0
    from . import models as m

    created = 0
    demo_hash = None
    with _session() as s:
        existing = {sid for (sid,) in s.execute(select(WebCredential.staff_id))}
        for staff_id, legacy in db.execute(select(m.OfficeStaff.OfficeStaffID, m.OfficeStaff.OfficeStaffPassword)):
            if staff_id in existing:
                continue
            if legacy and legacy.startswith("pbkdf2$"):
                h = legacy  # demo rows already hold this app's own hash format
            else:
                demo_hash = demo_hash or hash_password(settings.demo_password)
                h = demo_hash
            s.add(WebCredential(staff_id=staff_id, password_hash=h))
            created += 1
        try:
            s.commit()
        except IntegrityError:  # another worker process created them at the same moment
            s.rollback()
            return 0
    return created


# --------------------------------------------------------------- CLI
def _find_staff(db: Session, ident: str):
    from sqlalchemy import func, or_

    from . import models as m  # noqa: F811 - also used by the access-set command below

    ident = ident.strip().lower()
    return db.execute(
        select(m.OfficeStaff.OfficeStaffID, m.OfficeStaff.OfficeStaffFullName, m.OfficeStaff.Initials, m.OfficeStaff.OfficeStaffActive)
        .where(or_(func.lower(m.OfficeStaff.Initials) == ident, func.lower(m.OfficeStaff.OfficeStaffEmail) == ident))
    ).first()


def main(argv: list[str]) -> int:
    import getpass

    from . import models as m
    from .database import SessionLocal

    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "set-password" and len(argv) == 3:
        with SessionLocal() as db:
            staff = _find_staff(db, argv[2])
        if staff is None:
            print(f"No office staff record with initials or e-mail '{argv[2]}'.")
            return 1
        print(f"Setting the web password for {staff.OfficeStaffFullName} ({staff.Initials}){'' if staff.OfficeStaffActive else '  [INACTIVE account]'}")
        pw = getpass.getpass("New password (typing is hidden): ")
        problem = password_problem(pw, staff.Initials)
        if problem:
            print(problem)
            return 1
        if pw != getpass.getpass("Type it again: "):
            print("The two entries do not match. Nothing was changed.")
            return 1
        set_password(staff.OfficeStaffID, pw, must_change=False)
        print("Web password saved. The Access password was not touched.")
        return 0
    if cmd == "site-password":
        # ACCESS_MODE=passcode: print the PBKDF2 hash of a site password typed at a hidden prompt; paste it into the
        # hosting service as SITE_PASSWORD_HASH. The password itself is never written anywhere.
        pw = getpass.getpass("Site password (typing is hidden): ")
        problem = password_problem(pw, "")
        if problem:
            print(problem)
            return 1
        if pw != getpass.getpass("Type it again: "):
            print("The two entries do not match. Nothing was produced.")
            return 1
        print("SITE_PASSWORD_HASH=" + hash_password(pw))
        return 0
    if cmd == "list":
        with _session() as s:
            rows = s.execute(select(WebCredential.staff_id, WebCredential.must_change, WebCredential.last_login_at, WebCredential.locked_until)).all()
        print(f"{len(rows)} staff member(s) have a web password")
        for sid, must, last, locked in rows:
            print(f"  OfficeStaffID {sid:<6} last sign-in: {last or 'never'}{'  must change' if must else ''}{'  LOCKED' if locked and locked > datetime.utcnow() else ''}")
        return 0
    if cmd == "access-list":
        rows = list_access()
        print(f"{len(rows)} staff member(s) have website access from the store (plus WEB_ADMINS / WEB_USERS in the settings file); "
              f"{unique_users_this_month()} used it this month; seat limit {settings.access_seat_limit or 'none'}")
        for r in rows:
            print(f"  {r['role']:5} {r['initials'] or '?':6} OfficeStaffID {r['staff_id']:<6} last seen: {r['last_seen_at'] or 'never'}  (granted by {r['granted_by'] or '?'} on {str(r['granted_at'])[:10]})")
        return 0
    if cmd == "access-set" and len(argv) == 4 and argv[3] in ("admin", "user", "none"):
        with SessionLocal() as db:
            staff = _find_staff(db, argv[2])
            email = db.execute(select(m.OfficeStaff.OfficeStaffEmail).where(m.OfficeStaff.OfficeStaffID == staff.OfficeStaffID)).scalar() if staff else None
        if staff is None:
            print(f"No office staff record with initials or e-mail '{argv[2]}'.")
            return 1
        role = None if argv[3] == "none" else argv[3]
        if role and settings.access_seat_limit and staff.OfficeStaffID not in access_roles() and len(access_roles()) + 1 > settings.access_seat_limit:
            print(f"Refused: {len(access_roles())} people already have access and the seat limit is {settings.access_seat_limit} (ACCESS_SEAT_LIMIT).")
            return 1
        set_access(staff.OfficeStaffID, role, by="command line", initials=staff.Initials, email=email)
        print(f"{staff.OfficeStaffFullName} ({staff.Initials}): website access = {argv[3]}. Takes effect at once; no restart needed.")
        return 0
    if cmd == "devices" and len(argv) >= 3:
        # Operator recovery path for the approved-device boundary: runs INSIDE the backend (railway ssh), so it needs the
        # hosting account, not a website session. Every action is written to the unlock log with the operator's name.
        from . import devices, sitepass

        sub = argv[2]
        if sub == "list":
            rows = devices.list_devices()
            print(f"{len(rows)} device(s): {devices.approved_count()} approved, limit {settings.site_device_limit}")
            for d in rows:
                print(f"  #{d['id']:<4} {d['status']:8} {(d['pairing_code'] or ''):6} staff {str(d['staff_id'] or '-'):<6} {(d['label'] or '')[:40]:40} "
                      f"registered {str(d['created_at'] or '')[:16]} from {d['created_ip'] or '?'}  last used {str(d['last_used_at'] or 'never')[:16]}")
            return 0
        if sub == "approve" and len(argv) >= 6:  # devices approve PAIRING-CODE INITIALS OPERATOR [LABEL...]
            code, ident, by, label = argv[3].strip().upper(), argv[4], argv[5].strip(), " ".join(argv[6:]).strip()
            d = devices.find_by_code(code)
            if d is None or d.status != "pending":
                print(f"No PENDING device has the pairing code {code}. Nothing was changed.")
                return 1
            with SessionLocal() as db:
                staff = _find_staff(db, ident)
            if staff is None or not staff.OfficeStaffActive:
                print(f"No ACTIVE office staff record with initials or e-mail '{ident}'. Nothing was changed.")
                return 1
            if not by:
                print("Give the operator's name (it is written to the audit log).")
                return 1
            d = devices.approve(d.id, staff.OfficeStaffID, label or staff.OfficeStaffFullName, f"cli:{by}")
            sitepass.record("operator-cli", f"device:{d.id}", "command line", True, f"device-approved-by:cli:{by[:14]}")
            print(f"Device #{d.id} ({code}) approved for {staff.OfficeStaffFullName} ({staff.Initials}) as '{d.label}'. Recorded in the unlock log as cli:{by}.")
            return 0
        if sub == "revoke" and len(argv) >= 5:  # devices revoke ID OPERATOR
            by = argv[4].strip()
            try:
                d = devices.revoke(int(argv[3]), f"cli:{by}")
            except (LookupError, ValueError):
                print(f"No device #{argv[3]}. Nothing was changed.")
                return 1
            sitepass.record("operator-cli", f"device:{d.id}", "command line", True, f"device-revoked-by:cli:{by[:14]}")
            print(f"Device #{d.id} ('{d.label or ''}') revoked; any open session from it ends at its next request. Recorded as cli:{by}.")
            return 0
    print("usage: python -m app.webauth set-password INITIALS | site-password | list | access-list | access-set INITIALS admin|user|none\n"
          "       python -m app.webauth devices list | devices approve PAIRING-CODE INITIALS OPERATOR [LABEL] | devices revoke ID OPERATOR")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
