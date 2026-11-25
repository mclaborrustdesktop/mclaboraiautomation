from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import webauth
from ..config import settings
from ..database import get_db
from ..schemas import LoginRequest, TokenResponse, UserOut
from ..security import create_access_token, get_current_user, require_web_access
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
