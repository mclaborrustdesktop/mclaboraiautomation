from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import models as m
from .. import production, syncmirror, webauth
from ..ai import ai_mode
from ..config import RESTRICTED_FIELDS, settings
from ..security import require_admin
from .users import access_summary

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def system_status(_: m.OfficeStaff = Depends(require_admin)):
    """Readiness overview for administrators. Never includes credentials."""
    schema = production.validate_against_csv()
    return {
        "environment": settings.environment,
        "environment_label": settings.environment_label,
        "ai_mode": ai_mode(),
        "claude_model": settings.claude_model if ai_mode() == "claude" else None,
        "database": production.describe(),
        "schema_check": {
            "source": schema.source,
            "ok": schema.ok,
            "tables_checked": schema.tables_checked,
            "columns_checked": schema.columns_checked,
            "missing_tables": schema.missing_tables,
            "missing_columns": schema.missing_columns,
            "type_mismatches": schema.type_mismatches,
            "unknown_relationships": schema.unknown_relationships,
        },
        "sign_in": {
            "store": "separate web sign-in file (never the Access password column)",
            "accounts_with_web_password": webauth.account_count(),
            "demo_sign_in_offered": not settings.is_real_data,
            "lockout": f"{webauth.MAX_FAILED_ATTEMPTS} failed attempts = {webauth.LOCK_MINUTES} minutes",
            "minimum_password_length": webauth.min_password_length(),
        },
        "restricted_fields": [f"{t}.{c}" for t, cols in RESTRICTED_FIELDS.items() for c in cols],
        "restricted_fields_withheld": settings.is_real_data,
        "production_writes": "enabled" if settings.sql_writes_allowed else "disabled",
        "site_mode": "search-only" if settings.search_only else "full",
        "sync": {**syncmirror.status(), "ingest_enabled": settings.sync_enabled},
        "site_unlock": __import__("app.sitepass", fromlist=["summary"]).summary() if settings.access == "passcode" else None,
        "access": {
            "mode": settings.access,
            "platform": settings.gateway_platform if settings.access == "gateway" else None,
            "administrators_listed": len(settings.web_admin_set),
            "users_listed": len(settings.web_user_set),
            "access_lists_apply": settings.is_real_data,
            "gateway_trusted_proxies": sorted(settings.gateway_trusted_proxy_set) if settings.access == "gateway" else [],
            **access_summary(),
        },
        "outside_ai_service": {
            "api_key_present": bool(settings.anthropic_api_key),
            "used": settings.claude_allowed,
            "approval_recorded": bool((settings.claude_real_data_approval or "").strip()),
            "sent_when_used": "the typed question, fixed vocabulary and city names" + ("" if settings.is_real_data else "; in the demo also sales-rep names and industry labels"),
        },
        "warnings": settings.security_warnings(),
    }
