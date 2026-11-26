from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import webauth
from ..config import settings
from ..database import get_db
from ..schemas import LoginRequest, TokenResponse, UserOut
from ..security import client_address, create_access_token, get_current_user, require_admin, require_web_access
from .users import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Sign in with a web password (webauth.py). The Access password column is never read."""
    if settings.access == "gateway":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-in is handled by the company gateway.")
    if settings.access == "passcode":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This site uses the password screen (POST /api/auth/unlock).")
    ident = body.username.strip().lower()
    user = db.execute(
        select(m.OfficeStaff).where(
            or_(func.lower(m.OfficeStaff.Initials) == ident, func.lower(m.OfficeStaff.OfficeStaffEmail) == ident)
        )
    ).scalars().first()
    result, must_change = webauth.check_password(user.OfficeStaffID if user else None, body.password)
    if result == "not-set" and user is not None and webauth.bootstrap_first_admin(user.OfficeStaffID, user.Initials, user.OfficeStaffEmail, body.password):
        result, must_change = "ok", True  # the first administrator's one-time bootstrap password (WEB_BOOTSTRAP_PASSWORD)
    if result == "locked":
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many failed attempts. Try again in {webauth.LOCK_MINUTES} minutes.")
    if result != "ok":
        # same answer for unknown user, wrong password and no web password yet
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not user.OfficeStaffActive:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is inactive - contact an administrator")
    require_web_access(user)  # real data: only people on WEB_ADMINS / WEB_USERS may sign in, password or not
    if settings.writes_allowed:  # the office activity table is not written while production is read-only or the site is a search-only mirror
        db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName="login"))
        db.commit()
    return TokenResponse(access_token=create_access_token(user), user=user_out(user), must_change_password=must_change)


@router.get("/me", response_model=UserOut)
def me(user: m.OfficeStaff = Depends(get_current_user)):
    return user_out(user)


@router.post("/change-password", status_code=204)
def change_password(body: ChangePassword, user: m.OfficeStaff = Depends(get_current_user)):
    """Change your own web password. Stored in the web sign-in store only."""
    if settings.access == "passcode":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This site uses one site password; it is rotated by the administrator, not here.")
    result, _ = webauth.check_password(user.OfficeStaffID, body.current_password)
    if result == "locked":
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many failed attempts. Try again in {webauth.LOCK_MINUTES} minutes.")
    if result != "ok":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is not correct")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The new password must be different from the current one")
    problem = webauth.password_problem(body.new_password, user.Initials)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    webauth.set_password(user.OfficeStaffID, body.new_password, must_change=False)


# ------------------------------------------------------------------ passcode mode (one site password)
class UnlockRequest(BaseModel):
    password: str


@router.post("/unlock")
def unlock(body: UnlockRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """ACCESS_MODE=passcode: the password screen. The answer never says which part was wrong; a locked address or a
    locked site answers 429 with Retry-After. Every attempt is recorded (sitepass.py). With SITE_DEVICE_APPROVAL the
    correct password yields a short-lived ticket for the device step instead of a session."""
    if settings.access != "passcode":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    from .. import devices, sitepass
    from ..security import create_site_token, resolve_site_identity

    ip = client_address(request)
    agent = request.headers.get("User-Agent", "")
    locked, retry_after, reason = sitepass.lock_state(ip)
    if locked:
        sitepass.record(ip, None, agent, False, f"locked:{reason}")
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many attempts. Try again in {max(1, retry_after // 60)} minute(s).", headers={"Retry-After": str(retry_after)})
    if not sitepass.check(body.password):
        sitepass.record(ip, None, agent, False, "wrong")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect password.")
    if settings.site_device_approval:
        sitepass.record(ip, None, agent, True, "password-ok")
        return {"stage": "device", "ticket": devices.issue_ticket(ip), "rp_id": devices.rp_id()}
    try:
        user, identity = resolve_site_identity(request, db)
    except HTTPException:
        sitepass.record(ip, None, agent, False, "no-identity")
        raise
    sitepass.record(ip, identity, agent, True, "ok")
    return {"stage": "session", **TokenResponse(access_token=create_site_token(user, identity), user=user_out(user), must_change_password=False).model_dump()}


# ------------------------------------------------------------------ approved devices (WebAuthn), behind the password
class DeviceTicket(BaseModel):
    ticket: str


class DeviceAnswer(BaseModel):
    ticket: str
    challenge: str
    credential: dict
    bootstrap_code: str | None = None


def _device_guard(request: Request, ticket: str) -> str:
    """The device step is only reachable within minutes of a correct password, from the same address."""
    if settings.access != "passcode" or not settings.site_device_approval:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    from .. import devices

    ip = client_address(request)
    try:
        payload = devices.read_ticket(ticket)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Start again with the password.")
    if payload.get("ip") != ip:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Start again with the password.")
    return ip


@router.post("/device/options")
def device_options(body: DeviceTicket, request: Request):
    """WebAuthn request options: the browser signs the challenge with the credential it holds for this site."""
    from .. import devices

    _device_guard(request, body.ticket)
    options, challenge = devices.authentication_options()
    return {"options": options, "challenge": challenge}


@router.post("/device/verify")
def device_verify(body: DeviceAnswer, request: Request, db: Session = Depends(get_db)):
    """The signed challenge comes back. Approved device -> session bound to it. Pending -> 403 with the pairing code."""
    from .. import devices, sitepass
    from ..security import create_site_token, require_web_access, staff_by_ident

    ip = _device_guard(request, body.ticket)
    agent = request.headers.get("User-Agent", "")
    try:
        d = devices.authenticate(body.credential, body.challenge, ip)
    except LookupError:
        sitepass.record(ip, None, agent, False, "device-unknown")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This device is not registered.")
    except ValueError as exc:
        sitepass.record(ip, None, agent, False, "device-bad-signature")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Device check failed ({str(exc)[:60]}). Start again with the password.")
    if d.status == "pending" and body.bootstrap_code and devices.bootstrap_ok(d.id, body.bootstrap_code):
        owner = staff_by_ident(db, settings.site_default_user)
        if owner is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "SITE_DEFAULT_USER is not an active staff record.")
        d = devices.approve(d.id, owner.OfficeStaffID, f"{owner.OfficeStaffFullName} - first device (bootstrap)", "bootstrap-code")
        sitepass.record(ip, f"device:{d.id}", agent, True, "device-bootstrap-approved")
    if d.status == "pending":
        sitepass.record(ip, f"device:{d.id}", agent, False, "device-pending")
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "pending", "pairing_code": d.pairing_code, "message": "This device is waiting for an administrator to approve it."})
    if d.status != "approved":
        sitepass.record(ip, f"device:{d.id}", agent, False, "device-revoked")
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "revoked", "message": "Access from this device was revoked. Ask an administrator."})
    user = db.get(m.OfficeStaff, int(d.staff_id)) if d.staff_id else None
    if user is None or not user.OfficeStaffActive:
        sitepass.record(ip, f"device:{d.id}", agent, False, "device-no-staff")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The employee record for this device is inactive. Ask an administrator.")
    require_web_access(user)
    identity = f"device:{d.id}:{(d.label or '')[:40]}"
    sitepass.record(ip, identity, agent, True, "ok")
    return {"stage": "session", **TokenResponse(access_token=create_site_token(user, identity, d.id), user=user_out(user), must_change_password=False).model_dump()}


@router.post("/device/register/options")
def device_register_options(body: DeviceTicket, request: Request):
    from .. import devices

    _device_guard(request, body.ticket)
    options, challenge = devices.registration_options()
    return {"options": options, "challenge": challenge}


@router.post("/device/register/verify")
def device_register_verify(body: DeviceAnswer, request: Request):
    """Stores the new credential as PENDING and returns the pairing code the administrator will see."""
    from .. import devices, sitepass

    ip = _device_guard(request, body.ticket)
    agent = request.headers.get("User-Agent", "")
    try:
        d = devices.register(body.credential, body.challenge, ip, agent)
    except ValueError as exc:
        sitepass.record(ip, None, agent, False, "device-register-refused")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Device registration refused ({str(exc)[:80]}).")
    except PermissionError:
        sitepass.record(ip, None, agent, False, "device-limit")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The device limit is reached. Ask an administrator to revoke an old device.")
    sitepass.record(ip, f"device:{d.id}", agent, True, "device-registered")
    return {"stage": "pending", "pairing_code": d.pairing_code, "device_id": d.id}


@router.get("/device/status")
def device_status(code: str):
    """The waiting screen asks whether its pairing code was approved yet. Reveals the status only."""
    from .. import devices

    if settings.access != "passcode" or not settings.site_device_approval:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    st = devices.status_by_code(code)
    return {"status": st or "unknown"}


class DeviceApproval(BaseModel):
    staff: str
    label: str = ""


@router.get("/devices")
def devices_list(_: m.OfficeStaff = Depends(require_admin)):
    from .. import devices

    return {"devices": devices.list_devices(), "limit": settings.site_device_limit, "approved": devices.approved_count(), "enabled": settings.site_device_approval}


@router.post("/devices/{device_id}/approve")
def devices_approve(device_id: int, body: DeviceApproval, request: Request, admin: m.OfficeStaff = Depends(require_admin), db: Session = Depends(get_db)):
    from .. import devices, sitepass
    from ..security import staff_by_ident

    staff = staff_by_ident(db, body.staff)
    if staff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No active office staff record with initials or e-mail {body.staff!r}.")
    try:
        d = devices.approve(device_id, staff.OfficeStaffID, body.label or f"{staff.OfficeStaffFullName}", admin.Initials or str(admin.OfficeStaffID))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such device.")
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    sitepass.record(client_address(request), f"device:{d.id}", request.headers.get("User-Agent", ""), True, f"device-approved-by:{(admin.Initials or '')[:20]}")
    return devices.as_dict(d)


@router.post("/devices/{device_id}/revoke")
def devices_revoke(device_id: int, request: Request, admin: m.OfficeStaff = Depends(require_admin)):
    from .. import devices, sitepass

    try:
        d = devices.revoke(device_id, admin.Initials or str(admin.OfficeStaffID))
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such device.")
    sitepass.record(client_address(request), f"device:{d.id}", request.headers.get("User-Agent", ""), True, f"device-revoked-by:{(admin.Initials or '')[:20]}")
    return devices.as_dict(d)


@router.get("/unlock-log")
def unlock_log(limit: int = 100, _: m.OfficeStaff = Depends(require_admin)):
    """Administrators: the audit trail of the password screen (addresses, identities, outcomes). No passwords."""
    from .. import sitepass

    return {"summary": sitepass.summary(), "attempts": sitepass.recent(min(max(limit, 1), 500))}
