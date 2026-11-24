"""Change history: who changed what, when. Record pages show their own history; administrators see everything."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import audit
from .. import models as m
from ..security import require_admin, require_feature

router = APIRouter(prefix="/api/audit", tags=["audit"])

_ENTITY_TABLE = {"employees": ("tblEmployee", "employees.view"), "customers": ("tblCustomer", "customers.view"),
                 "projects": ("tblProject", "projects.view"), "tracking": ("tblTracking", "tracking.view")}


@router.get("")
def recent_changes(limit: int = Query(100, ge=1, le=1000), table: str | None = None, staff_id: int | None = None, action: str | None = None,
                   _: m.OfficeStaff = Depends(require_admin)):
    """The newest changes made through the website (administrators)."""
    return {"items": audit.recent(limit=limit, table=table, staff_id=staff_id, action=action)}


def _history_dep(entity: str):
    if entity not in _ENTITY_TABLE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown record type")
    return _ENTITY_TABLE[entity]


@router.get("/{entity}/{record_id}")
def record_history(entity: str, record_id: int, limit: int = Query(50, ge=1, le=500), user: m.OfficeStaff = Depends(require_feature("employees.view"))):
    table, feature = _history_dep(entity)
    from ..security import user_has_feature

    if not user_has_feature(user, feature):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {feature}")
    return {"table": table, "record_id": record_id, "items": audit.history(table, record_id, limit=limit)}
