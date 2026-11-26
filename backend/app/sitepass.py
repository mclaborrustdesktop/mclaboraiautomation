"""The password-only entrance ("passcode" access mode).

One site password, stored ONLY as a PBKDF2 hash in the setting SITE_PASSWORD_HASH (never in the code, never logged),
checked at POST /api/auth/unlock. This module keeps the brute-force protection and the audit trail in the web
sign-in store (the same database as the web passwords, so every worker process and every replica sees the same
counters):

* per address: after SITE_LOCK_FAILURES failed attempts within SITE_LOCK_MINUTES the address is refused for
  SITE_LOCK_MINUTES (doubling with every further failure, up to 4 hours);
* overall: after SITE_GLOBAL_LOCK_FAILURES failures from any addresses within the window, every address is refused
  for SITE_LOCK_MINUTES (a distributed guess attack hits this);
* every attempt is recorded with the address, the identity the gateway named (if any), the client software and the
  outcome; administrators read the trail at GET /api/auth/unlock-log and the system status page summarises it.

The password itself is slow to check on purpose (PBKDF2, 120,000 rounds, about 0.1 s), which caps guessing even
before the counters do. The identity behind a successful unlock is decided in security.resolve_site_identity.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func, select

from .config import settings
from .security import verify_password
from .webauth import AuthBase, _session

MAX_LOCK_MINUTES = 240


class SiteUnlockAttempt(AuthBase):
    __tablename__ = "site_unlock_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    ip = Column(String(64), nullable=False, index=True)
    identity = Column(String(120))
    user_agent = Column(String(200))
    success = Column(Boolean, nullable=False, default=False)
    note = Column(String(60))


def _window_start() -> datetime:
    return datetime.utcnow() - timedelta(minutes=settings.site_lock_minutes)


def lock_state(ip: str) -> tuple[bool, int, str]:
    """(locked, retry_after_seconds, reason). Reason is 'address' or 'everyone' when locked."""
    now = datetime.utcnow()
    since = _window_start()
    with _session() as s:
        ip_failures = s.execute(select(func.count()).select_from(SiteUnlockAttempt).where(
            SiteUnlockAttempt.ip == ip, SiteUnlockAttempt.success.is_(False), SiteUnlockAttempt.at >= since - timedelta(minutes=MAX_LOCK_MINUTES))).scalar() or 0
        last_fail = s.execute(select(func.max(SiteUnlockAttempt.at)).where(SiteUnlockAttempt.ip == ip, SiteUnlockAttempt.success.is_(False))).scalar()
        all_failures = s.execute(select(func.count()).select_from(SiteUnlockAttempt).where(
            SiteUnlockAttempt.success.is_(False), SiteUnlockAttempt.at >= since)).scalar() or 0
        last_any_fail = s.execute(select(func.max(SiteUnlockAttempt.at)).where(SiteUnlockAttempt.success.is_(False))).scalar()
    if ip_failures >= settings.site_lock_failures and last_fail is not None:
        # the lock doubles with every failure beyond the threshold: 15, 30, 60, 120, 240 minutes
        extra = min(ip_failures - settings.site_lock_failures, 4)
        minutes = min(settings.site_lock_minutes * (2 ** extra), MAX_LOCK_MINUTES)
        until = last_fail + timedelta(minutes=minutes)
        if until > now:
            return True, int((until - now).total_seconds()) + 1, "address"
    if all_failures >= settings.site_global_lock_failures and last_any_fail is not None:
        until = last_any_fail + timedelta(minutes=settings.site_lock_minutes)
        if until > now:
            return True, int((until - now).total_seconds()) + 1, "everyone"
    return False, 0, ""


def record(ip: str, identity: str | None, user_agent: str | None, success: bool, note: str) -> None:
    with _session() as s:
        s.add(SiteUnlockAttempt(ip=(ip or "?")[:64], identity=(identity or None) and identity[:120], user_agent=(user_agent or "")[:200] or None, success=success, note=note[:60]))
        s.commit()


def check(password: str) -> bool:
    stored = (settings.site_password_hash or "").strip()
    if not stored.startswith("pbkdf2$"):
        return False
    return verify_password(password or "", stored)


def recent(limit: int = 100) -> list[dict]:
    with _session() as s:
        rows = s.execute(select(SiteUnlockAttempt).order_by(SiteUnlockAttempt.id.desc()).limit(limit)).scalars().all()
    return [{"at": r.at.isoformat(timespec="seconds"), "ip": r.ip, "identity": r.identity, "user_agent": r.user_agent, "success": r.success, "note": r.note} for r in rows]


def summary() -> dict:
    day = datetime.utcnow() - timedelta(hours=24)
    with _session() as s:
        total = s.execute(select(func.count()).select_from(SiteUnlockAttempt).where(SiteUnlockAttempt.at >= day)).scalar() or 0
        failed = s.execute(select(func.count()).select_from(SiteUnlockAttempt).where(SiteUnlockAttempt.at >= day, SiteUnlockAttempt.success.is_(False))).scalar() or 0
        addresses = s.execute(select(func.count(func.distinct(SiteUnlockAttempt.ip))).where(SiteUnlockAttempt.at >= day)).scalar() or 0
        last_ok = s.execute(select(func.max(SiteUnlockAttempt.at)).where(SiteUnlockAttempt.success.is_(True))).scalar()
    return {"attempts_24h": total, "failed_24h": failed, "addresses_24h": addresses, "last_success_at": last_ok.isoformat(timespec="seconds") if last_ok else None,
            "lock_rule": f"{settings.site_lock_failures} failures = {settings.site_lock_minutes} min per address (doubling), {settings.site_global_lock_failures} failures = {settings.site_lock_minutes} min for everyone",
            "session_minutes": settings.site_session_minutes, "password_label": settings.site_password_label}


def clear() -> None:
    """Tests only."""
    with _session() as s:
        s.query(SiteUnlockAttempt).delete()
        s.commit()
