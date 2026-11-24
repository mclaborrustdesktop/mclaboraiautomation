from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models as m
from ..database import get_db
from ..schemas import Page, UserCreate, UserOut, UserUpdate
from .. import webauth
from ..config import settings
from ..security import _listed, is_web_admin, require_admin, web_features, web_role

router = APIRouter(prefix="/api/users", tags=["users"])


class SetPassword(BaseModel):
    password: str
    must_change: bool = True


def _check_password(password: str, initials: str | None) -> None:
    problem = webauth.password_problem(password, initials)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)


def user_out(u: m.OfficeStaff) -> UserOut:
    data = {c: getattr(u, c) for c in UserOut.model_fields if hasattr(u, c)}
    data["Profile"] = is_web_admin(u)
    data["search_only"] = settings.search_only
    if settings.is_real_data:
        # Real data: a person can have 1,000+ Access-form permissions; none of them is a website page.
        # WEB_USERS see the view-only pages; administrators (Profile) see everything.
        data["feature_ids"], data["features"] = [], web_features(u)
        data["web_access"] = web_role(u) or "none"
        # "settings" = named in the settings file (bootstrap, changed by an administrator of the server);
        # "store" = granted in the website (changeable here); "none" = no access
        data["web_access_source"] = "settings" if (_listed(u, settings.web_admin_set) or _listed(u, settings.web_user_set)) else ("store" if data["web_access"] != "none" else "none")
    else:
        data["feature_ids"] = [p.FeatureID for p in u.permissions]
        data["features"] = [p.feature.ObjectName for p in u.permissions]
        data["web_access"] = "admin" if u.Profile else "features"
    return UserOut(**data)


def _load(db: Session, user_id: int) -> m.OfficeStaff:
    u = db.execute(
        select(m.OfficeStaff).options(selectinload(m.OfficeStaff.permissions).selectinload(m.OfficeStaffPermission.feature))
        .where(m.OfficeStaff.OfficeStaffID == user_id)
    ).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u


def _set_permissions(db: Session, u: m.OfficeStaff, feature_ids: list[int]) -> None:
    valid = {f.FeatureID for f in db.execute(select(m.Feature)).scalars()}
    bad = set(feature_ids) - valid
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown feature ids: {sorted(bad)}")
    u.permissions.clear()
    db.flush()
    for fid in sorted(set(feature_ids)):
        u.permissions.append(m.OfficeStaffPermission(FeatureID=fid))


class WebAccessIn(BaseModel):
    role: str  # "admin" | "user" | "none"


def access_summary() -> dict:
    """How many people may use the website, how many used it this month, and how close that is to the seat limit."""
    store = webauth.access_roles()
    settings_people = len(settings.web_admin_set | settings.web_user_set) if settings.is_real_data else 0
    authorized = len(set(store) | set()) + settings_people
    limit, warn = max(0, settings.access_seat_limit), max(0, settings.access_seat_warn)
    service_limit, other = max(0, settings.access_service_limit), max(0, settings.access_other_seats)
    service_used = authorized + other
    messages = []
    if limit and warn and authorized >= warn:
        messages.append(f"{authorized} of {limit} authorized website users are assigned (the company maximum is {limit}).")
    if service_limit and service_used >= service_limit - 5:
        messages.append(f"{service_used} of {service_limit} seats of the sign-in service are in use ({authorized} website users + {other} other users such as the Access PCs). Above {service_limit} the service is no longer free: see docs/cloud/09-user-access-plan.md.")
    return {
        "authorized": authorized,
        "administrators": sum(1 for r in store.values() if r == "admin") + (len(settings.web_admin_set) if settings.is_real_data else 0),
        "users": sum(1 for r in store.values() if r == "user") + (len(settings.web_user_set) if settings.is_real_data else 0),
        "used_this_month": webauth.unique_users_this_month() if settings.is_real_data else 0,
        "seat_limit": limit or None,
        "seats_left": (limit - authorized) if limit else None,
        "service_seat_limit": service_limit or None,
        "service_seats_used": service_used,
        "warning": bool(messages),
        "message": " ".join(messages) if messages else None,
    }


@router.get("/access-summary")
def get_access_summary(_: m.OfficeStaff = Depends(require_admin)):
    return access_summary()


@router.put("/{user_id}/web-access", response_model=UserOut)
def set_web_access(user_id: int, body: WebAccessIn, db: Session = Depends(get_db), admin: m.OfficeStaff = Depends(require_admin)):
    """Grant ("admin" / "user") or remove ("none") website access for a staff member. Written to the website's own
    sign-in store, never to the McLabor database, so it works while real data is read-only; takes effect on the
    person's next request, with no restart. Bootstrap administrators from the settings file cannot be changed here."""
    if body.role not in ("admin", "user", "none"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "role must be admin, user or none")
    u = _load(db, user_id)
    if user_id == admin.OfficeStaffID and body.role != "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot remove your own administrator access")
    if settings.is_real_data and (_listed(u, settings.web_admin_set) or _listed(u, settings.web_user_set)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This person is named in the website's settings file (WEB_ADMINS / WEB_USERS); change it there.")
    if body.role != "none" and not u.OfficeStaffActive:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The staff record is inactive")
    role = None if body.role == "none" else body.role
    if role and user_id not in webauth.access_roles() and settings.access_seat_limit:
        if access_summary()["authorized"] + 1 > settings.access_seat_limit:
            raise HTTPException(status.HTTP_409_CONFLICT, f"The seat limit of {settings.access_seat_limit} is reached. Remove someone first, or see docs/cloud/09-user-access-plan.md for the paid or alternative plans.")
    webauth.set_access(user_id, role, by=admin.Initials, initials=u.Initials, email=u.OfficeStaffEmail)
    return user_out(_load(db, user_id))


@router.get("", response_model=Page[UserOut])
def list_users(
    q: str | None = None,
    active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: m.OfficeStaff = Depends(require_admin),
):
    stmt = select(m.OfficeStaff).options(selectinload(m.OfficeStaff.permissions).selectinload(m.OfficeStaffPermission.feature))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(m.OfficeStaff.OfficeStaffFullName).like(like),
                func.lower(m.OfficeStaff.Initials).like(like),
                func.lower(m.OfficeStaff.OfficeStaffEmail).like(like),
                func.lower(m.OfficeStaff.OfficeStaffTitle).like(like),
            )
        )
    if active is not None:
        stmt = stmt.where(m.OfficeStaff.OfficeStaffActive == active)
    rows = list(db.execute(stmt.order_by(m.OfficeStaff.OfficeStaffLastName, m.OfficeStaff.OfficeStaffFirstName)).scalars().unique())
    total = len(rows)
    rows = rows[(page - 1) * page_size : page * page_size]
    return Page(items=[user_out(u) for u in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_admin)):
    exists = db.execute(select(m.OfficeStaff).where(func.lower(m.OfficeStaff.Initials) == body.Initials.lower())).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Initials already in use")
    _check_password(body.password, body.Initials)
    data = body.model_dump(exclude={"password", "feature_ids"})
    u = m.OfficeStaff(**data, OfficeStaffFullName=f"{body.OfficeStaffFirstName} {body.OfficeStaffLastName}")
    db.add(u)
    db.flush()
    _set_permissions(db, u, body.feature_ids)
    db.commit()
    webauth.set_password(u.OfficeStaffID, body.password)  # web sign-in store, not tblOfficeStaff
    return user_out(_load(db, u.OfficeStaffID))


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_admin)):
    return user_out(_load(db, user_id))


@router.put("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), admin: m.OfficeStaff = Depends(require_admin)):
    u = _load(db, user_id)
    data = body.model_dump(exclude_unset=True)
    pw = data.pop("password", None)
    if pw:
        _check_password(pw, data.get("Initials") or u.Initials)
    feature_ids = data.pop("feature_ids", None)
    if "Initials" in data and data["Initials"]:
        dup = db.execute(
            select(m.OfficeStaff).where(func.lower(m.OfficeStaff.Initials) == data["Initials"].lower(), m.OfficeStaff.OfficeStaffID != user_id)
        ).first()
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "Initials already in use")
    if user_id == admin.OfficeStaffID and (data.get("Profile") is False or data.get("OfficeStaffActive") is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot remove your own administrator access")
    for k, v in data.items():
        setattr(u, k, v)
    u.OfficeStaffFullName = f"{u.OfficeStaffFirstName} {u.OfficeStaffLastName}"
    if feature_ids is not None:
        _set_permissions(db, u, feature_ids)
    db.commit()
    if pw:
        webauth.set_password(user_id, pw)
    return user_out(_load(db, user_id))


@router.post("/{user_id}/password", status_code=204)
def set_user_password(user_id: int, body: SetPassword, db: Session = Depends(get_db), _: m.OfficeStaff = Depends(require_admin)):
    """Administrator sets a web password for a staff member. Writes only to the web sign-in store,
    so it also works while the production database is read-only."""
    u = _load(db, user_id)
    _check_password(body.password, u.Initials)
    webauth.set_password(user_id, body.password, must_change=body.must_change)


@router.delete("/{user_id}", status_code=204)
def deactivate_user(user_id: int, db: Session = Depends(get_db), admin: m.OfficeStaff = Depends(require_admin)):
    """Soft-delete: production never hard-deletes office staff (audit trail)."""
    if user_id == admin.OfficeStaffID:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate yourself")
    u = _load(db, user_id)
    u.OfficeStaffActive = False
    db.commit()
