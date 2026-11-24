"""Change log and "someone else changed this record" protection for every write the website makes.

Change log (who, when, which table and record, which columns changed from what to what) is written to the
website's OWN store (the web sign-in database: SQLite on this PC, the same PostgreSQL database in the cloud), never
to the McLabor business tables. It therefore works in every environment, including while a SQL Server environment
is read-only, and survives the move from SQL Server to PostgreSQL unchanged. Restricted columns (date of birth,
citizenship, I-9, passwords) are never written to it.

Record versions: every record a form can edit carries a ``version`` (a hash of the row's values as they were
read). A save sends it back as ``expected_version``; when the row has changed in between (another website user,
or an Access user on the same SQL Server tables), the save is refused with 409 and the person reloads the record.
No new column is needed in the business database, and a change made in Access is detected too.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import DateTime, Integer, String, Text, inspect, select
from sqlalchemy.orm import Mapped, mapped_column

from .config import RESTRICTED_FIELDS, settings
from .observability import request_id_var
from .webauth import AuthBase, _session

log = logging.getLogger("mclabor.audit")

_NEVER_LOGGED = {c for cols in RESTRICTED_FIELDS.values() for c in cols} | {"OfficeStaffPassword", "SSNum", "BankAccountNumber", "BankRoutingNumber"}


class WebAuditLog(AuthBase):
    __tablename__ = "web_audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    environment: Mapped[str] = mapped_column(String(12))
    staff_id: Mapped[int | None] = mapped_column(Integer, index=True)
    initials: Mapped[str | None] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(60))
    table_name: Mapped[str] = mapped_column(String(60), index=True)
    record_id: Mapped[int | None] = mapped_column(Integer, index=True)
    summary: Mapped[str | None] = mapped_column(String(300))
    changes: Mapped[str | None] = mapped_column(Text)  # JSON {column: {"from": old, "to": new}}
    request_id: Mapped[str | None] = mapped_column(String(40))


# ---------------------------------------------------------------- snapshots and versions
def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def snapshot(obj: Any, children: dict[str, list[Any]] | None = None) -> dict[str, Any]:
    """The loggable column values of one ORM row (and optionally of its child rows: licenses, contacts)."""
    out: dict[str, Any] = {}
    mapper = inspect(type(obj))
    for attr in mapper.column_attrs:
        name = attr.key
        if name in _NEVER_LOGGED:
            continue
        out[name] = _plain(getattr(obj, name, None))
    for key, rows in (children or {}).items():
        out[key] = [snapshot(r) for r in rows]
    return out


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    before, after = before or {}, after or {}
    changed = {}
    for k in sorted(set(before) | set(after)):
        if before.get(k) != after.get(k):
            changed[k] = {"from": before.get(k), "to": after.get(k)}
    return changed


def row_version(obj: Any, children: dict[str, list[Any]] | None = None) -> str:
    """A short hash of the record as it is now; changes whenever any of its (loggable) values change."""
    payload = json.dumps(snapshot(obj, children), sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def require_version(obj: Any, expected: str | None, children: dict[str, list[Any]] | None = None) -> None:
    """Refuse the save when the record changed since the form was opened (optimistic concurrency)."""
    if not expected:
        return
    current = row_version(obj, children)
    if current != expected:
        who = ""
        for attr in ("EmEntryUserName", "CustEntryUserName", "ProjectEntryUserName", "AssignmentUserName"):
            if getattr(obj, attr, None):
                who = f" (last entered by {getattr(obj, attr)})"
                break
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "stale",
            "message": f"This record was changed by someone else after you opened it{who}. Reload it, then make your change again.",
            "current_version": current,
        })


# ---------------------------------------------------------------- writing and reading the log
def record(user: Any, action: str, table: str, record_id: int | None, before: dict[str, Any] | None = None,
           after: dict[str, Any] | None = None, summary: str | None = None) -> None:
    """Write one log row. Never raises: a logging failure must not undo a saved record (it is reported in the server log)."""
    try:
        changes = diff(before, after) if (before is not None or after is not None) else {}
        if action.endswith(".create") and after is not None:
            changes = {k: {"from": None, "to": v} for k, v in after.items() if v not in (None, "", [], 0, False)}
        row = WebAuditLog(
            environment=settings.environment, staff_id=getattr(user, "OfficeStaffID", None), initials=getattr(user, "Initials", None),
            action=action, table_name=table, record_id=record_id, summary=(summary or "")[:300] or None,
            changes=json.dumps(changes, default=str)[:200_000] if changes else None, request_id=request_id_var.get(None),
        )
        with _session() as s:
            s.add(row)
            s.commit()
    except Exception as exc:  # noqa: BLE001
        log.error("Audit log write failed for %s %s/%s: %s", action, table, record_id, type(exc).__name__)


def _out(r: WebAuditLog) -> dict[str, Any]:
    return {"id": r.id, "at": r.at, "staff_id": r.staff_id, "initials": r.initials, "action": r.action, "table": r.table_name,
            "record_id": r.record_id, "summary": r.summary, "changes": json.loads(r.changes) if r.changes else {}, "request_id": r.request_id}


def history(table: str, record_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with _session() as s:
        rows = s.execute(select(WebAuditLog).where(WebAuditLog.table_name == table, WebAuditLog.record_id == record_id,
                                                   WebAuditLog.environment == settings.environment)
                         .order_by(WebAuditLog.at.desc(), WebAuditLog.id.desc()).limit(min(max(1, limit), 500))).scalars().all()
        return [_out(r) for r in rows]


def recent(limit: int = 100, table: str | None = None, staff_id: int | None = None, action: str | None = None) -> list[dict[str, Any]]:
    with _session() as s:
        stmt = select(WebAuditLog).where(WebAuditLog.environment == settings.environment)
        if table:
            stmt = stmt.where(WebAuditLog.table_name == table)
        if staff_id:
            stmt = stmt.where(WebAuditLog.staff_id == staff_id)
        if action:
            stmt = stmt.where(WebAuditLog.action.like(f"{action}%"))
        rows = s.execute(stmt.order_by(WebAuditLog.at.desc(), WebAuditLog.id.desc()).limit(min(max(1, limit), 1000))).scalars().all()
        return [_out(r) for r in rows]


def count() -> int:
    with _session() as s:
        return len(s.execute(select(WebAuditLog.id)).all())
