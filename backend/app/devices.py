"""Approved devices: the second boundary behind the site password (ACCESS_MODE=passcode + SITE_DEVICE_APPROVAL=true).

Each device holds a WebAuthn credential: a key pair created by the device's own authenticator (Windows Hello / TPM,
Touch ID, Android, or a security key). The private key never leaves that hardware and cannot be copied out of the
browser; the website keeps only the public key. Every unlock = the site password AND a signature, made by the
device, over a fresh challenge from the server. A device is useless until an administrator approves it and names the
employee it belongs to; it can be revoked in one click. Everything is recorded in the unlock log (sitepass.py).

Flow (routers/auth.py):
  1. POST /api/auth/unlock {password}            -> stage "device" + a short-lived ticket (5 min)
  2. POST /api/auth/device/options {ticket}      -> WebAuthn request options (challenge signed into a 3-minute token)
     the browser signs with a known credential   -> POST /api/auth/device/verify {ticket, challenge, assertion}
        approved  -> session token bound to the device
        pending   -> 403 with the pairing code (an administrator has to approve it)
        revoked   -> 403
     no credential on this device                -> POST /api/auth/device/register/options {ticket}
                                                    POST /api/auth/device/register/verify {ticket, challenge, attestation}
                                                 -> the device is stored as PENDING with a pairing code
  Administrators: GET /api/auth/devices, POST /api/auth/devices/{id}/approve {staff, label}, POST .../revoke.
  First device ever: the owner enters SITE_DEVICE_BOOTSTRAP_CODE on the pending screen, which approves that one device
  as SITE_DEFAULT_USER while no approved device exists yet (then the variable is deleted).
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import Boolean, Column, DateTime, Integer, LargeBinary, String, func, select
from webauthn import generate_authentication_options, generate_registration_options, options_to_json, verify_authentication_response, verify_registration_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import AttestationConveyancePreference, AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement

from .config import settings
from .webauth import AuthBase, _session

PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
TICKET_MINUTES = 5
CHALLENGE_MINUTES = 3
_ready = False


class WebDevice(AuthBase):
    __tablename__ = "web_devices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    credential_id = Column(String(400), nullable=False, unique=True)      # base64url
    public_key = Column(LargeBinary, nullable=False)                      # COSE public key
    sign_count = Column(Integer, nullable=False, default=0)
    aaguid = Column(String(40))
    status = Column(String(10), nullable=False, default="pending")        # pending | approved | revoked
    pairing_code = Column(String(8), nullable=False, index=True)
    label = Column(String(80))                                            # "Alex Rivera - office PC"
    staff_id = Column(Integer)                                            # tblOfficeStaff.OfficeStaffID once approved
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_ip = Column(String(64))
    user_agent = Column(String(200))
    approved_at = Column(DateTime)
    approved_by = Column(String(120))
    revoked_at = Column(DateTime)
    revoked_by = Column(String(120))
    last_used_at = Column(DateTime)
    last_ip = Column(String(64))
    uses = Column(Integer, nullable=False, default=0)
    backed_up = Column(Boolean)


def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    from sqlalchemy.exc import IntegrityError, ProgrammingError

    with _session() as s:
        try:
            WebDevice.__table__.create(s.get_bind(), checkfirst=True)
        except (IntegrityError, ProgrammingError):
            s.rollback()
    _ready = True


# ---------------------------------------------------------------- tokens
def _token(kind: str, minutes: int, **claims) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"mode": kind, "env": settings.environment, "iat": now, "exp": now + timedelta(minutes=minutes), **claims}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _read(token: str | None, kind: str) -> dict:
    try:
        payload = jwt.decode(token or "", settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise ValueError("expired")
    if payload.get("mode") != kind or payload.get("env") != settings.environment:
        raise ValueError("wrong token")
    return payload


def issue_ticket(ip: str) -> str:
    """After the correct site password: proves, for a few minutes, that this visitor may try a device."""
    return _token("ticket", TICKET_MINUTES, ip=ip)


def read_ticket(token: str | None) -> dict:
    return _read(token, "ticket")


def _challenge_token(challenge: bytes, purpose: str) -> str:
    return _token("challenge", CHALLENGE_MINUTES, c=bytes_to_base64url(challenge), p=purpose)


def _read_challenge(token: str | None, purpose: str) -> bytes:
    payload = _read(token, "challenge")
    if payload.get("p") != purpose:
        raise ValueError("wrong challenge")
    return base64url_to_bytes(payload["c"])


# ---------------------------------------------------------------- WebAuthn
def rp_id() -> str:
    return (settings.webauthn_rp_id or "").strip()


def origin() -> str:
    return (settings.webauthn_origin or "").strip().rstrip("/")


def _descriptors(statuses=("approved", "pending")) -> list[PublicKeyCredentialDescriptor]:
    _ensure_table()
    with _session() as s:
        ids = [cid for (cid,) in s.execute(select(WebDevice.credential_id).where(WebDevice.status.in_(statuses)))]
    return [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in ids]


def registration_options() -> tuple[str, str]:
    """(options JSON for navigator.credentials.create, challenge token)."""
    opts = generate_registration_options(
        rp_id=rp_id(), rp_name="MC Labor Search", user_id=secrets.token_bytes(16), user_name="MC Labor device",
        user_display_name="MC Labor device", attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.DISCOURAGED, user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=_descriptors(("approved", "pending")),
    )
    return options_to_json(opts), _challenge_token(opts.challenge, "register")


def register(credential: dict | str, challenge_token: str, ip: str, user_agent: str) -> WebDevice:
    """Verifies the attestation and stores the device as PENDING with a pairing code."""
    challenge = _read_challenge(challenge_token, "register")
    try:
        v = verify_registration_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp_id(), expected_origin=origin(), require_user_presence=True)
    except InvalidRegistrationResponse as exc:
        raise ValueError(f"registration refused: {exc}")
    _ensure_table()
    with _session() as s:
        if s.execute(select(func.count()).select_from(WebDevice).where(WebDevice.status.in_(("approved", "pending")))).scalar() >= settings.site_device_limit:
            raise PermissionError("device limit reached")
        code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(6))
        d = WebDevice(credential_id=bytes_to_base64url(v.credential_id), public_key=v.credential_public_key, sign_count=v.sign_count, aaguid=str(v.aaguid),
                      status="pending", pairing_code=code, created_ip=(ip or "")[:64], user_agent=(user_agent or "")[:200], backed_up=bool(getattr(v, "credential_backed_up", False)))
        s.add(d)
        s.commit()
        s.refresh(d)
        s.expunge(d)
        return d


def authentication_options() -> tuple[str, str]:
    opts = generate_authentication_options(rp_id=rp_id(), allow_credentials=_descriptors(("approved", "pending")), user_verification=UserVerificationRequirement.PREFERRED)
    return options_to_json(opts), _challenge_token(opts.challenge, "assert")


def authenticate(credential: dict | str, challenge_token: str, ip: str) -> WebDevice:
    """Verifies the signature over our challenge with the stored public key; returns the device (any status)."""
    challenge = _read_challenge(challenge_token, "assert")
    raw_id = credential["rawId"] if isinstance(credential, dict) else __import__("json").loads(credential)["rawId"]
    _ensure_table()
    with _session() as s:
        d = s.execute(select(WebDevice).where(WebDevice.credential_id == raw_id)).scalar_one_or_none()
        if d is None:
            raise LookupError("unknown device")
        try:
            v = verify_authentication_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp_id(), expected_origin=origin(),
                                               credential_public_key=d.public_key, credential_current_sign_count=d.sign_count, require_user_verification=False)
        except InvalidAuthenticationResponse as exc:
            raise ValueError(f"signature refused: {exc}")
        d.sign_count = v.new_sign_count
        d.last_used_at = datetime.utcnow()
        d.last_ip = (ip or "")[:64]
        d.uses = (d.uses or 0) + 1
        s.commit()
        s.refresh(d)
        s.expunge(d)
        return d


# ---------------------------------------------------------------- administration
def get(device_id: int) -> WebDevice | None:
    _ensure_table()
    with _session() as s:
        d = s.get(WebDevice, device_id)
        if d is not None:
            s.expunge(d)
        return d


def is_approved(device_id: int) -> bool:
    d = get(device_id)
    return d is not None and d.status == "approved"


def approved_count() -> int:
    _ensure_table()
    with _session() as s:
        return s.execute(select(func.count()).select_from(WebDevice).where(WebDevice.status == "approved")).scalar() or 0


def approve(device_id: int, staff_id: int, label: str, by: str) -> WebDevice:
    _ensure_table()
    with _session() as s:
        d = s.get(WebDevice, device_id)
        if d is None:
            raise LookupError("no such device")
        if d.status == "revoked":
            raise ValueError("a revoked device cannot be approved again; the employee registers the device anew")
        d.status = "approved"
        d.staff_id = staff_id
        d.label = (label or "")[:80] or None
        d.approved_at = datetime.utcnow()
        d.approved_by = by[:120]
        s.commit()
        s.refresh(d)
        s.expunge(d)
        return d


def revoke(device_id: int, by: str) -> WebDevice:
    _ensure_table()
    with _session() as s:
        d = s.get(WebDevice, device_id)
        if d is None:
            raise LookupError("no such device")
        d.status = "revoked"
        d.revoked_at = datetime.utcnow()
        d.revoked_by = by[:120]
        s.commit()
        s.refresh(d)
        s.expunge(d)
        return d


def bootstrap_ok(device_id: int, offered_code: str) -> bool:
    """The first device ever: SITE_DEVICE_BOOTSTRAP_CODE (a sealed one-time setting) approves it as SITE_DEFAULT_USER
    while no approved device exists. Never afterwards."""
    code = (settings.site_device_bootstrap_code or "").strip()
    if not code or len(code) < 16 or approved_count() > 0:
        return False
    return hmac.compare_digest((offered_code or "").strip().encode(), code.encode())


def as_dict(d: WebDevice) -> dict:
    return {"id": d.id, "status": d.status, "pairing_code": d.pairing_code if d.status == "pending" else None, "label": d.label, "staff_id": d.staff_id,
            "created_at": d.created_at.isoformat(timespec="seconds") if d.created_at else None, "created_ip": d.created_ip, "user_agent": d.user_agent,
            "approved_at": d.approved_at.isoformat(timespec="seconds") if d.approved_at else None, "approved_by": d.approved_by,
            "revoked_at": d.revoked_at.isoformat(timespec="seconds") if d.revoked_at else None, "revoked_by": d.revoked_by,
            "last_used_at": d.last_used_at.isoformat(timespec="seconds") if d.last_used_at else None, "last_ip": d.last_ip, "uses": d.uses,
            "backed_up": d.backed_up, "aaguid": d.aaguid}


def list_devices() -> list[dict]:
    _ensure_table()
    with _session() as s:
        rows = s.execute(select(WebDevice).order_by(WebDevice.status, WebDevice.id.desc())).scalars().all()
        return [as_dict(d) for d in rows]


def find_by_code(code: str) -> WebDevice | None:
    """The device behind a pairing code (operator command line)."""
    _ensure_table()
    with _session() as s:
        d = s.execute(select(WebDevice).where(WebDevice.pairing_code == (code or "").strip().upper())).scalar_one_or_none()
        if d is not None:
            s.expunge(d)
        return d


def status_by_code(code: str) -> str | None:
    """pending / approved / revoked for a pairing code (the waiting screen polls this; it reveals nothing else)."""
    _ensure_table()
    with _session() as s:
        return s.execute(select(WebDevice.status).where(WebDevice.pairing_code == (code or "").strip().upper())).scalar_one_or_none()


def clear() -> None:
    """Tests only."""
    _ensure_table()
    with _session() as s:
        s.query(WebDevice).delete()
        s.commit()
