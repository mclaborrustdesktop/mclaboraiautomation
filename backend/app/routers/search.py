from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models as m
from ..ai import SearchIntent, ai_mode, interpret
from ..database import get_db
from ..schemas import AISearchInfo, AISearchRequest, Page
from ..search import search_customers, search_employees, search_projects, vocab
from ..security import require_feature, user_has_feature
from ..production import writes_allowed

router = APIRouter(prefix="/api/search", tags=["ai-search"])

_VIEW_FEATURE = {"employees": "employees.view", "customers": "customers.view", "projects": "projects.view"}
_SEARCHERS = {"employees": search_employees, "customers": search_customers, "projects": search_projects}

EXAMPLES = {
    "employees": [
        "licensed journeyman electricians in Worcester with 5+ years",
        "available plumbers in Massachusetts who will travel",
        "HVAC techs with OSHA 10 under $40",
        "carpenters whose license expires in the next 60 days",
        "apprentice laborers in Rhode Island",
    ],
    "customers": [
        "active general contractors in Boston with jobs running",
        "customers in collections",
        "prospects in Connecticut without a contract",
        "electrical contractors with revenue over 100k",
        "healthcare facilities customers on hold",
    ],
    "projects": [
        "active jobs in Boston that are not manned",
        "pending projects starting this month",
        "OCIP jobs in Massachusetts",
        "completed electrical jobs in Worcester",
        "jobs needing at least 4 workers",
    ],
}

# Quick-refinement chips offered when the matching filter is not yet applied.
SUGGESTIONS: dict[str, list[dict[str, Any]]] = {
    "employees": [
        {"label": "Licensed only", "patch": {"licensed": True}},
        {"label": "Available now", "patch": {"status": "Available"}},
        {"label": "OSHA card", "patch": {"osha": True}},
        {"label": "Will travel", "patch": {"will_travel": True}},
        {"label": "5+ years", "patch": {"min_years": 5}},
        {"label": "Journeyman", "patch": {"qualification": "Journeyman"}},
        {"label": "In MA", "patch": {"state": "MA"}},
        {"label": "Under $35/hr", "patch": {"max_rate": 35}},
        {"label": "License expiring 90d", "patch": {"license_expiring_days": 90}},
    ],
    "customers": [
        {"label": "Active", "patch": {"status": "Active"}},
        {"label": "Contract on file", "patch": {"contract_on_file": True}},
        {"label": "Has active jobs", "patch": {"has_active_projects": True}},
        {"label": "General contractors", "patch": {"customer_type": "General Contractor"}},
        {"label": "In MA", "patch": {"state": "MA"}},
        {"label": "Revenue > $100k", "patch": {"min_revenue": 100000}},
        {"label": "Not on hold", "patch": {"on_hold": False}},
    ],
    "projects": [
        {"label": "Active", "patch": {"status": "Active"}},
        {"label": "Needs crew", "patch": {"manned": False}},
        {"label": "Pending", "patch": {"status": "Pending"}},
        {"label": "In MA", "patch": {"state": "MA"}},
        {"label": "Starting this month", "patch": {"start_window": "this_month"}},
        {"label": "4+ workers", "patch": {"min_employees": 4}},
        {"label": "OCIP", "patch": {"ocip": True}},
    ],
}


@router.get("/status")
def search_status(_: m.OfficeStaff = Depends(require_feature("ai.search"))):
    return {"mode": ai_mode(), "examples": EXAMPLES}


def _summary(entity: str, total: int, facets: list[dict[str, Any]], filters: dict[str, Any]) -> str:
    noun = {"employees": "worker", "customers": "customer", "projects": "job"}[entity]
    if total == 0:
        return f"No {noun}s match - try removing a filter or a keyword."
    parts = [f"{total} {noun}{'s' if total != 1 else ''}"]
    by_key = {f["key"]: f for f in facets}
    for key in ("trade", "customer_type", "status", "city"):
        fac = by_key.get(key)
        if fac and key not in filters and fac["values"]:
            top = fac["values"][0]
            share = round(100 * top["count"] / total)
            if share >= 30:
                parts.append(f"{share}% {top['value']}")
    return " · ".join(parts)


@router.post("", response_model=Page)
def ai_search(body: AISearchRequest, db: Session = Depends(get_db), user: m.OfficeStaff = Depends(require_feature("ai.search"))):
    if not user_has_feature(user, _VIEW_FEATURE[body.entity]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {_VIEW_FEATURE[body.entity]}")

    if body.filters is not None:
        # The UI edited the understood filters directly (chip removed, facet clicked, suggestion applied).
        intent = SearchIntent(
            entity=body.entity, query=body.query or "", mode="manual",
            filters={k: v for k, v in body.filters.items() if v is not None},
            keywords=body.keywords or [], interpretation="Filters adjusted by you.",
        )
    else:
        if not (body.query or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a search request")
        intent = interpret(body.entity, body.query, vocab(db, body.entity, body.query))
        if body.refine and body.base_filters:
            merged = {k: v for k, v in body.base_filters.items() if v is not None}
            merged.update(intent.filters)
            intent.filters = merged
            intent.keywords = list(dict.fromkeys((body.base_keywords or []) + intent.keywords))
            intent.interpretation = "Refined: " + intent.interpretation

    # facet counts are only needed (and only computed) for the first page
    result = _SEARCHERS[body.entity](db, intent.filters, intent.keywords, body.page, body.page_size, sort=body.sort or "relevance", with_facets=body.page == 1)
    if writes_allowed():  # activity log is skipped while production is read-only
        db.add(m.OfficeStaffActivity(OfficeStaffID=user.OfficeStaffID, OfficeStaffActivityObjectName=f"ai.search.{body.entity}"))
        db.commit()
    suggestions = [s for s in SUGGESTIONS[body.entity] if not all(intent.filters.get(k) == v for k, v in s["patch"].items())][:6]
    info = AISearchInfo(**intent.as_info(), summary=_summary(body.entity, result.total, result.facets, intent.filters), suggestions=suggestions)
    return Page(items=result.items, total=result.total, page=body.page, page_size=body.page_size, ai=info, facets=result.facets)
