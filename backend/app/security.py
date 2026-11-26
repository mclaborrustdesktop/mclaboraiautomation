from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import OfficeStaff

_bearer = HTTPBearer(auto_error=False)
_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
    return hmac.compare_digest(actual, expected)


# What a WEB_USERS person may do with real data: look things up. Nothing that changes a record, manages users or
# shows the system status page.
WEB_VIEW_FEATURES = ("employees.view", "customers.view", "projects.view", "tracking.view", "ai.search")


def _listed(staff: OfficeStaff, names: set[str]) -> bool:
    """Is this staff member named (by OfficeStaffID, initials or e-mail) in an access list from backend/.env?"""
    if not names:
        return False
    email = (getattr(staff, "OfficeStaffEmail", None) or "").strip().lower()
    return str(staff.OfficeStaffID) in names or (staff.Initials or "").strip().lower() in names or (bool(email) and email in names)


def web_role(staff: OfficeStaff) -> str | None:
    """Real data: "admin", "user" or None. The settings file's lists come first (bootstrap administrators), then
    the roles an administrator granted in the website's own store (webauth.WebAccess)."""
    if _listed(staff, settings.web_admin_set):
        return "admin"
    if _listed(staff, settings.web_user_set):
        return "user"
    from . import webauth

    return webauth.access_roles().get(staff.OfficeStaffID)


def is_web_admin(staff: OfficeStaff) -> bool:
    """Demo: the staff record's Profile flag. Real data: WEB_ADMINS, or an "admin" role granted in the website."""
    if not settings.is_real_data:
        return bool(staff.Profile)
    return web_role(staff) == "admin"


def is_web_user(staff: OfficeStaff) -> bool:
    """May this person use the website at all? Demo: every active account. Real data: a listed or granted role."""
    if not settings.is_real_data:
        return True
    return web_role(staff) is not None


def web_features(staff: OfficeStaff) -> list[str]:
    """Feature names to show the browser for a real-data user. Administrators are flagged by Profile instead."""
    if not settings.is_real_data or is_web_admin(staff):
        return []
    return list(WEB_VIEW_FEATURES) if is_web_user(staff) else []


def require_web_access(staff: OfficeStaff) -> None:
    if settings.is_real_data and not is_web_user(staff):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has not been given access to the website. Ask an administrator to add you.")
    if settings.is_real_data:
        from . import webauth

        webauth.touch_seen(staff.OfficeStaffID)  # unique-user count (what a per-seat sign-in service bills)


def create_access_token(staff: OfficeStaff) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(staff.OfficeStaffID),
        "name": staff.OfficeStaffFullName,
        "initials": staff.Initials,
        "admin": is_web_admin(staff),
        "env": settings.environment,  # a sign-in is valid only in the environment that issued it
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _open_demo_user(db: Session) -> OfficeStaff:
    """DEMO without a sign-in page: every visitor is the demo administrator (synthetic data only)."""
    if settings.is_real_data:  # belt and braces: settings.access can never be 'open' with real data
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = db.execute(
        select(OfficeStaff).where(OfficeStaff.OfficeStaffActive == True, OfficeStaff.Profile == True).order_by(OfficeStaff.OfficeStaffID)  # noqa: E712
    ).scalars().first()
    if user is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The demo data has no administrator account")
    return user


def _gateway_user(request: Request, db: Session) -> OfficeStaff:
    """Staging / production behind a company-only gateway. The gateway has already signed the person in; it
    proves itself with the shared secret and names the person by e-mail. Anything else is refused."""
    came_from = (request.client.host if request.client else "") or ""
    # Three things must all be true: the request comes from where the gateway runs, the gateway proved itself,
    # and the gateway named an active staff member who is on the website's access list.
    if not settings.is_trusted_proxy(came_from):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This site is only available through the company gateway.")
    platform = (settings.gateway_platform or "proxy").strip().lower()
    if platform == "cloudflare-access":
        # Cloudflare signs every request it lets through with a token for this application; the tunnel on this
        # server is the only route in (trusted proxy = localhost). The e-mail comes from the verified token, never
        # from a plain header.
        from . import cloudflare_access

        # Cloudflare puts the token in a header and in the CF_Authorization cookie; a hosted front end that forwards the
        # browser's request to this API (deploy/railway) passes both on, so either is accepted. Both are verified the same way.
        token = request.headers.get("Cf-Access-Jwt-Assertion") or request.cookies.get("CF_Authorization")
        try:
            email = cloudflare_access.verify(token)["email"]
        except cloudflare_access.AccessTokenInvalid:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This site is only available through the company gateway.")
    elif platform == "azure-easyauth":
        # Azure's built-in authentication sidecar: it strips X-MS-CLIENT-PRINCIPAL-* from visitors and sets them itself.
        # Both headers must be present; the sidecar is the only route to the app (trusted proxy = localhost).
        if not request.headers.get("X-MS-CLIENT-PRINCIPAL-IDP") or not request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME"):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This site is only available through the company gateway.")
        email = request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "").strip().lower()
    else:
        secret = settings.gateway_secret or ""
        offered = request.headers.get(settings.gateway_secret_header, "")
        if len(secret) < 32 or not hmac.compare_digest(offered.encode(), secret.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This site is only available through the company gateway.")
        email = request.headers.get(settings.gateway_email_header, "").strip().lower()
    user = None
    if email:
        user = db.execute(select(OfficeStaff).where(func.lower(OfficeStaff.OfficeStaffEmail) == email)).scalars().first()
    if user is None or not user.OfficeStaffActive:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not an active MC Labor office staff record.")
    require_web_access(user)
    return user


def client_address(request: Request) -> str:
    """The visitor's address for the unlock counters. A hosted front end (deploy/railway) forwards the browser's request
    over the private network with X-Forwarded-For as the platform's edge set it; only that proxy can reach this API."""
    xff = request.headers.get("X-Forwarded-For", "")
    last = xff.split(",")[-1].strip() if xff else ""  # the edge appends the real address last; a visitor cannot forge that entry
    return last or ((request.client.host if request.client else "") or "?")


def gateway_identity(request: Request) -> tuple[str | None, str | None]:
    """(email, common_name) from a verified Cloudflare Access token on this request, if the platform is configured and the
    token is present. (None, None) otherwise. Used by the passcode mode to know WHO unlocked, for the audit trail and the
    access lists, without a user name field."""
    if (settings.gateway_platform or "").strip().lower() != "cloudflare-access":
        return None, None
    if not ((settings.cloudflare_access_team_domain or "").strip() and (settings.cloudflare_access_aud or "").strip()):
        return None, None
    token = request.headers.get("Cf-Access-Jwt-Assertion") or request.cookies.get("CF_Authorization")
    if not token:
        return None, None
    from . import cloudflare_access

    try:
        claims = cloudflare_access.verify(token, require_email=False)
    except cloudflare_access.AccessTokenInvalid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This site is only available through the company gateway.")
    return (claims.get("email") or None), (claims.get("common_name") or None)


def resolve_site_identity(request: Request, db: Session) -> tuple[OfficeStaff, str]:
    """Passcode mode: the staff record a successful unlock acts as, and the identity string for the audit trail.
    A Cloudflare Access identity (certificate common name or e-mail) always wins; otherwise SITE_DEFAULT_USER."""
    email, cn = gateway_identity(request)
    ident = (email or cn or "").strip().lower()
    label = f"cloudflare:{ident}" if ident else f"default:{(settings.site_default_user or '').strip().lower()}"
    if not ident:
        ident = (settings.site_default_user or "").strip().lower()
    user = None
    if ident:
        user = db.execute(select(OfficeStaff).where(
            (func.lower(OfficeStaff.Initials) == ident) | (func.lower(OfficeStaff.OfficeStaffEmail) == ident))).scalars().first()
    if user is None or not user.OfficeStaffActive:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your access identity is not an active MC Labor office staff record. Ask an administrator.")
    require_web_access(user)
    return user, label


def create_site_token(staff: OfficeStaff, identity: str, device_id: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(staff.OfficeStaffID), "name": staff.OfficeStaffFullName, "initials": staff.Initials, "admin": is_web_admin(staff),
               "mode": "site", "who": identity[:120], "env": settings.environment, "iat": now, "exp": now + timedelta(minutes=settings.site_session_minutes)}
    if device_id is not None:
        payload["dev"] = int(device_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def staff_by_ident(db: Session, ident: str) -> OfficeStaff | None:
    """An active staff record by initials or e-mail (case-insensitive), or None."""
    ident = (ident or "").strip().lower()
    if not ident:
        return None
    user = db.execute(select(OfficeStaff).where((func.lower(OfficeStaff.Initials) == ident) | (func.lower(OfficeStaff.OfficeStaffEmail) == ident))).scalars().first()
    return user if user is not None and user.OfficeStaffActive else None


def _site_user(request: Request, creds: HTTPAuthorizationCredentials | None, db: Session) -> OfficeStaff:
    """Passcode mode: only a token issued by /api/auth/unlock (mode 'site') in this environment is accepted."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Enter the password again.")
    if payload.get("mode") != "site" or payload.get("env", "demo") != settings.environment:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Enter the password again.")
    email, cn = gateway_identity(request)  # if the gateway names someone, the session must belong to that person
    ident = (email or cn or "").strip().lower()
    if ident and payload.get("who") != f"cloudflare:{ident}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Enter the password again.")
    if settings.site_device_approval:
        # the session must have been issued to an approved device, and that device must still be approved (revocation is immediate)
        from . import devices

        dev = payload.get("dev")
        if not dev or not devices.is_approved(int(dev)):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This device is no longer approved. Enter the password again.")
    user = db.get(OfficeStaff, int(payload["sub"]))
    if user is None or not user.OfficeStaffActive:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    require_web_access(user)
    return user


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> OfficeStaff:
    if settings.access == "gateway":
        return _gateway_user(request, db)  # web sign-in tokens are not accepted in this mode
    if settings.access == "passcode":
        return _site_user(request, creds, db)  # only unlock tokens are accepted in this mode
    if settings.access == "open":
        # Demo without sign-in: everyone is the demo administrator. A token left in the browser from an
        # earlier sign-in (possibly expired, or from another environment) is simply ignored.
        return _open_demo_user(db)
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("env", "demo") != settings.environment:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This sign-in belongs to a different environment. Please sign in again.")
    user = db.get(OfficeStaff, int(payload["sub"]))
    if user is None or not user.OfficeStaffActive:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    require_web_access(user)  # the access lists are read on every request, so removing a name takes effect at the next restart, not at token expiry
    return user


def require_admin(user: OfficeStaff = Depends(get_current_user)) -> OfficeStaff:
    if not is_web_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


def user_has_feature(user: OfficeStaff, object_name: str) -> bool:
    if settings.search_only and object_name.endswith(".edit"):
        return False  # a search-only mirror: nobody adds, edits or deletes, administrators included
    if is_web_admin(user):
        return True
    if settings.is_real_data:
        # the real permission table lists Access forms, not website pages: WEB_USERS get the view-only set, nobody else gets anything
        return object_name in WEB_VIEW_FEATURES and is_web_user(user)
    return any(p.feature.ObjectName == object_name for p in user.permissions)


def require_feature(object_name: str):
    def _dep(user: OfficeStaff = Depends(get_current_user)) -> OfficeStaff:
        if not user_has_feature(user, object_name):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {object_name}")
        return user

    return _dep
