"""Natural-language search interpretation.

Turns a free-text request such as

    "licensed journeyman electricians near Worcester with 5+ years who can travel"

into a structured filter set that the search service understands.

Two interpreters are available:

* **Claude** - used when ANTHROPIC_API_KEY is configured.  The request is sent
  to the Claude API with a strict JSON schema so the result is always
  well-formed.  Server-side refusal fallbacks are enabled so a policy decline
  never produces an empty search.
* **Heuristic** - a deterministic vocabulary/regex parser that runs with no
  network access.  It is also the automatic fallback if the Claude call fails
  for any reason, so the application never breaks because of the AI layer.

What leaves this PC when Claude is used: the typed question and the fixed
vocabulary (trade, status and type names, state codes), plus the list of city
names.  In the demo the sales-rep names and industry labels are included too.
With real data (staging / production) they are NOT sent - no staff name and no
customer-derived text - and Claude is only used at all when the owner's approval
is recorded in CLAUDE_REAL_DATA_APPROVAL (see config.py).  Employee, customer
and job records are never sent: every result row comes from the database.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Vocabulary shared by both interpreters
# ----------------------------------------------------------------------------
TRADE_SYNONYMS: dict[str, list[str]] = {
    "Electrician": ["electrician", "electricians", "electrical", "sparky", "wireman", "wiremen"],
    "Plumber": ["plumber", "plumbers", "plumbing"],
    "HVAC Technician": ["hvac", "hvac tech", "hvac technician", "refrigeration", "ac tech", "heating"],
    "Carpenter": ["carpenter", "carpenters", "carpentry", "framer", "framers", "finish carpenter"],
    "Laborer": ["laborer", "laborers", "labor", "general labor", "helper", "helpers"],
    "Pipefitter": ["pipefitter", "pipefitters", "pipe fitter", "steamfitter"],
    "Welder": ["welder", "welders", "welding"],
    "Painter": ["painter", "painters", "painting"],
    "Drywall Installer": ["drywall", "drywaller", "taper", "sheetrock"],
    "Mason": ["mason", "masons", "masonry", "bricklayer", "block"],
    "Ironworker": ["ironworker", "ironworkers", "iron worker", "rebar", "structural steel"],
    "Roofer": ["roofer", "roofers", "roofing"],
    "Sheet Metal Worker": ["sheet metal", "sheetmetal", "ductwork", "tin knocker"],
    "Sprinkler Fitter": ["sprinkler", "sprinkler fitter", "fire protection", "fire sprinkler"],
    "Equipment Operator": ["operator", "operators", "equipment operator", "excavator", "hoisting"],
}

QUALIFICATION_SYNONYMS: dict[str, list[str]] = {
    "Master": ["master", "masters"],
    "Journeyman": ["journeyman", "journeymen", "journey"],
    "Apprentice": ["apprentice", "apprentices"],
    "Helper": ["helper", "helpers"],
    "Foreman": ["foreman", "foremen", "lead", "crew lead", "supervisor"],
}

EMPLOYEE_STATUS_SYNONYMS: dict[str, list[str]] = {
    "Available": ["available", "open", "on the bench", "bench", "free", "not assigned", "unassigned"],
    "On Assignment": ["on assignment", "assigned", "working", "placed", "on a job"],
    "Active": ["active"],
    "Inactive": ["inactive", "former"],
    "Applicant": ["applicant", "applicants", "new hire", "candidate", "candidates"],
    "Do Not Use": ["do not use", "dnu", "blacklisted", "banned"],
}

CUSTOMER_STATUS_SYNONYMS: dict[str, list[str]] = {
    "Active": ["active"],
    "Inactive": ["inactive", "dormant"],
    "Prospect": ["prospect", "prospects", "lead", "leads", "new lead"],
    "Collections": ["collections", "past due", "overdue", "owe", "owes", "delinquent"],
    "Do Not Use": ["do not use", "dnu"],
}

CUSTOMER_TYPE_SYNONYMS: dict[str, list[str]] = {
    "Electrical Contractor": ["electrical contractor", "electrical contractors", "electrical company"],
    "Plumbing Contractor": ["plumbing contractor", "plumbing contractors", "plumbing company"],
    "General Contractor": ["general contractor", "general contractors", "gc", "gcs", "builder", "builders"],
    "HVAC Contractor": ["hvac contractor", "hvac contractors", "hvac company", "mechanical"],
    "Mechanical Contractor": ["mechanical contractor", "mechanical contractors"],
    "Property Manager": ["property manager", "property management", "landlord"],
    "Developer": ["developer", "developers"],
}

PROJECT_STATUS_SYNONYMS: dict[str, list[str]] = {
    "Active": ["active", "running", "ongoing", "in progress", "open"],
    "Pending": ["pending", "upcoming", "not started", "not yet started"],  # "starting this month" is a start window, not a status
    "On Hold": ["on hold", "paused", "hold"],
    "Completed": ["completed", "complete", "finished", "done", "closed"],
    "Cancelled": ["cancelled", "canceled"],
}

STATES: dict[str, str] = {
    "MA": "massachusetts",
    "CT": "connecticut",
    "RI": "rhode island",
    "NH": "new hampshire",
    "NY": "new york",
    "ME": "maine",
    "VT": "vermont",
}

STOPWORDS = {
    "a", "an", "and", "the", "in", "near", "with", "who", "that", "for", "of", "to", "at", "me", "find", "show",
    "list", "all", "any", "get", "give", "need", "needs", "want", "looking", "look", "search", "please", "from",
    "are", "is", "be", "can", "could", "has", "have", "or", "on", "by", "around", "within", "some", "employees",
    "employee", "workers", "worker", "people", "guys", "crew", "customers", "customer", "accounts", "account",
    "clients", "client", "companies", "company", "projects", "project", "jobs", "job", "sites", "site", "than",
    "more", "least", "us", "our", "we", "i", "my", "this", "these", "those", "it", "its",
}


@dataclass
class SearchIntent:
    entity: str
    query: str
    mode: str  # "claude" | "heuristic"
    filters: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    interpretation: str = ""

    def as_info(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "query": self.query,
            "interpretation": self.interpretation,
            "filters": self.filters,
            "keywords": self.keywords,
        }


# ----------------------------------------------------------------------------
# Heuristic interpreter
# ----------------------------------------------------------------------------
def _match_vocab(text: str, vocab: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    for canonical, words in vocab.items():
        for w in words:
            if re.search(rf"(?<![a-z]){re.escape(w)}(?:s|es)?(?![a-z])", text):  # plural-tolerant: "pipe fitters"
                found.append(canonical)
                break
    return found


def _find_cities(text: str, cities: list[str]) -> list[str]:
    hits = []
    for c in sorted(cities, key=len, reverse=True):
        # The real city list has junk entries such as "Ma", "NY", "St" and "P": too short to be a city in a question.
        if len(c.strip()) < 3 or c.lower() not in text:
            continue
        if re.search(rf"(?<![a-z]){re.escape(c.lower())}(?![a-z])", text):
            hits.append(c)
    return hits


def _find_states(text: str) -> list[str]:
    hits = []
    for code, name in STATES.items():
        if re.search(rf"(?<![a-z]){name}(?![a-z])", text) or re.search(rf"(?<![a-z]){code.lower()}(?![a-z])", text):
            hits.append(code)
    return hits


def _years(text: str) -> tuple[int | None, int | None]:
    m = re.search(r"(\d+)\s*\+\s*(?:years|yrs|year)", text) or re.search(
        r"(?:at least|over|more than|minimum of|min)\s*(\d+)\s*(?:years|yrs|year)", text
    )
    lo = int(m.group(1)) if m else None
    m2 = re.search(r"(?:under|less than|fewer than|max(?:imum)?(?: of)?)\s*(\d+)\s*(?:years|yrs|year)", text)
    hi = int(m2.group(1)) if m2 else None
    if lo is None and hi is None:
        m3 = re.search(r"(\d+)\s*(?:years|yrs)\s*(?:of)?\s*(?:experience|exp)", text)
        if m3:
            lo = int(m3.group(1))
    return lo, hi


def _money(text: str, key_words: str) -> float | None:
    m = re.search(rf"{key_words}\s*\$?\s*(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _real_label(canonical: str, real_labels: list[str] | None) -> str | None:
    """The label the real lookup table uses for a canonical vocabulary value ("General Contractor" -> "General
    Contractors"), or None when the real list is known and has nothing like it (pilot finding: the demo vocabulary
    named types the real database does not have, so the filter found nobody). No list given: the canonical value."""
    if not real_labels:
        return canonical
    want = canonical.lower()
    by_lower = {lbl.lower(): lbl for lbl in real_labels if lbl}
    if want in by_lower:
        return by_lower[want]
    words = [w for w in re.findall(r"[a-z]+", want) if len(w) > 2]
    for lower, lbl in by_lower.items():
        if all(w in lower or w.rstrip("s") in lower for w in words):
            return lbl
    return None


def heuristic_interpret(entity: str, query: str, vocab: dict[str, list[str]]) -> SearchIntent:
    text = query.lower().strip()
    f: dict[str, Any] = {}
    consumed: list[str] = []
    cities = vocab.get("cities", [])

    states = _find_states(text)
    if states:
        f["state"] = states[0]
        consumed += [STATES[states[0]], states[0].lower()]
    city_hits = _find_cities(text, cities)
    if city_hits:
        f["city"] = city_hits[0]
        consumed.append(city_hits[0].lower())
    # ZIP code: only when the question says so ("zip 02118", "in 02118", "near 02118"), never any 5-digit number
    zip_hit = re.search(r"(?:zip(?:\s*code)?|in|near|around)\s+(\d{5})(?!\d)", text)
    if zip_hit:
        f["zip"] = zip_hit.group(1)
        consumed += ["zip", "code"]

    if entity == "employees":
        trades = _match_vocab(text, TRADE_SYNONYMS)
        if trades:
            f["trade"] = trades[0]
            consumed += TRADE_SYNONYMS[trades[0]]
        quals = _match_vocab(text, QUALIFICATION_SYNONYMS)
        if quals:
            f["qualification"] = quals[0]
            consumed += QUALIFICATION_SYNONYMS[quals[0]]
        statuses = _match_vocab(text, EMPLOYEE_STATUS_SYNONYMS)
        if statuses:
            f["status"] = statuses[0]
            consumed += EMPLOYEE_STATUS_SYNONYMS[statuses[0]]
        if re.search(r"(?<![a-z])(licensed|license|licence|holds a license)(?![a-z])", text) and "unlicensed" not in text:
            f["licensed"] = True
            consumed += ["licensed", "license"]
        if "unlicensed" in text:
            f["licensed"] = False
            consumed.append("unlicensed")
        if re.search(r"osha\s*(10|30)?", text):
            f["osha"] = True
            consumed += ["osha", "osha 10", "osha 30"]
        if re.search(r"(?<![a-z])(travel|travels|traveling|willing to travel|will travel)(?![a-z])", text):
            f["will_travel"] = True
            consumed += ["travel", "travels", "traveling", "willing", "will"]
        lo, hi = _years(text)
        if lo is not None:
            f["min_years"] = lo
        if hi is not None:
            f["max_years"] = hi
        if lo is not None or hi is not None:
            consumed += ["years", "yrs", "year", "experience", "exp"]  # the words that expressed the number are not search words
        m = re.search(r"(?:expir\w*)\s*(?:in|within|next)?\s*(\d+)\s*(days|months)", text)
        if m:
            n = int(m.group(1))
            f["license_expiring_days"] = n * 30 if m.group(2) == "months" else n
            consumed += ["expiring", "expires", "expire", "days", "months", "next", "within"]
        elif re.search(r"expir", text):
            f["license_expiring_days"] = 90
            consumed += ["expiring", "expires", "expire", "soon"]
        rate = _money(text, r"(?:under|below|less than|max(?:imum)?(?: rate)?(?: of)?)")
        if rate is not None:
            f["max_rate"] = rate
        rate_lo = _money(text, r"(?:over|above|at least|more than|min(?:imum)?(?: rate)?(?: of)?)")
        if rate_lo is not None and "years" not in text:
            f["min_rate"] = rate_lo
        if re.search(r"(?<![a-z])(citizen|citizens|us citizen)(?![a-z])", text):
            f["us_citizen"] = True
            consumed += ["citizen", "citizens"]
        if re.search(r"(?<![a-z])(i-?9|i9)(?![a-z])", text):
            f["i9_complete"] = "missing" not in text and "without" not in text and "no i9" not in text
            consumed += ["i9", "i-9", "complete", "missing", "without"]
    elif entity == "customers":
        # "active jobs" / "running projects" describe the customer's jobs, not the customer's own status: take that
        # phrase out before the status words are looked at (pilot finding: "customers in MA with active jobs" was
        # also read as status = Active)
        active_jobs_phrase = r"(?<![a-z])(active|running|ongoing|current) (jobs?|projects?|work)(?![a-z])"
        status_text = re.sub(active_jobs_phrase, " ", text)
        statuses = _match_vocab(status_text, CUSTOMER_STATUS_SYNONYMS)
        if statuses:
            f["status"] = statuses[0]
            consumed += CUSTOMER_STATUS_SYNONYMS[statuses[0]]
        types = _match_vocab(text, CUSTOMER_TYPE_SYNONYMS)
        if types:
            real = _real_label(types[0], vocab.get("customer_types"))
            if real is not None:  # the real lookup has a matching type (or no lookup list was given)
                f["customer_type"] = real
                consumed += CUSTOMER_TYPE_SYNONYMS[types[0]]
        if re.search(r"(?<![a-z])(on hold|hold)(?![a-z])", text):
            f["on_hold"] = True
            consumed += ["on hold", "hold"]
        if re.search(r"(?<![a-z])(no contract|without (a )?contract|missing contract|unsigned)(?![a-z])", text):
            f["contract_on_file"] = False
            consumed += ["contract", "without", "missing", "unsigned"]
        elif re.search(r"(?<![a-z])(contract on file|signed contract|with (a )?contract|contract)(?![a-z])", text):
            f["contract_on_file"] = True
            consumed += ["contract", "signed", "file"]
        rev = _money(text, r"(?:revenue|billing|billed|spend|spending)\s*(?:over|above|at least|more than|>)?")
        if rev is None:
            rev = _money(text, r"(?:over|above|at least|more than)\s*\$")
        if rev is not None:
            f["min_revenue"] = rev * 1000 if re.search(r"\d+\s*k(?![a-z])", text) else rev
        if re.search(
            r"(?<![a-z])(active (jobs?|projects?)|(jobs?|projects?) (running|active|in progress|going)|currently working|with work|has work|running jobs?)(?![a-z])",
            text,
        ):
            f["has_active_projects"] = True
            consumed += ["active", "jobs", "projects", "currently", "working", "running"]
        if re.search(r"(?<![a-z])(no (active )?(jobs|projects|work)|idle|without (jobs|projects|work))(?![a-z])", text):
            f["has_active_projects"] = False
            consumed += ["no", "idle", "without", "jobs", "projects", "work"]
        for ind in vocab.get("industries", []):
            if ind.lower() in text:
                f["industry"] = ind
                consumed.append(ind.lower())
                break
        for s in vocab.get("salesmen", []):
            first = s.split(" ")[0].lower()
            if re.search(rf"(?<![a-z]){re.escape(s.lower())}(?![a-z])", text) or re.search(
                rf"(?:salesman|rep|sales rep|owned by|assigned to|belongs to)\s+{re.escape(first)}", text
            ):
                f["salesman"] = s
                consumed += s.lower().split(" ")
                break
    elif entity == "projects":
        statuses = _match_vocab(text, PROJECT_STATUS_SYNONYMS)
        if statuses:
            f["status"] = statuses[0]
            consumed += PROJECT_STATUS_SYNONYMS[statuses[0]]
        if re.search(r"(?<![a-z])(unmanned|not manned|need(s|ing)? (men|people|workers|staff|crew)|understaffed|no crew)(?![a-z])", text):
            f["manned"] = False
            consumed += ["unmanned", "manned", "need", "needs", "needing", "understaffed"]
        elif re.search(r"(?<![a-z])(manned|staffed|fully staffed)(?![a-z])", text):
            f["manned"] = True
            consumed += ["manned", "staffed", "fully"]
        trades = _match_vocab(text, TRADE_SYNONYMS)
        if trades:
            f["trade"] = trades[0]
            consumed += TRADE_SYNONYMS[trades[0]]
        m = re.search(r"(?:at least|more than|over|min(?:imum)?)\s*(\d+)\s*(?:employees|workers|people|men|guys|heads)", text)
        if m:
            f["min_employees"] = int(m.group(1))
        if re.search(r"(?<![a-z])(ocip)(?![a-z])", text):
            f["ocip"] = True
            consumed.append("ocip")
        if re.search(r"(?<![a-z])(this month|starting this month)(?![a-z])", text):
            f["start_window"] = "this_month"
            consumed += ["this", "month", "starting"]
        elif re.search(r"(?<![a-z])(next month)(?![a-z])", text):
            f["start_window"] = "next_month"
            consumed += ["next", "month"]
        elif re.search(r"(?<![a-z])(this week|starting this week)(?![a-z])", text):
            f["start_window"] = "this_week"
            consumed += ["this", "week", "starting"]
        elif re.search(r"(?<![a-z])(this year)(?![a-z])", text):
            f["start_window"] = "this_year"
            consumed += ["this", "year"]
        for cust in vocab.get("customers", []):
            # a customer whose business name is also the city in the question ("jobs in Hartford") is the city, not a customer filter
            if cust.lower() in text and cust.lower() != str(f.get("city", "")).lower():
                f["customer"] = cust
                consumed += cust.lower().split(" ")
                break

    # leftover tokens become keywords for free-text matching
    cleaned = text
    for c in sorted(set(consumed), key=len, reverse=True):
        cleaned = re.sub(rf"(?<![a-z]){re.escape(c)}(?:s|es)?(?![a-z])", " ", cleaned)
    tokens = [t for t in re.findall(r"[a-z0-9][a-z0-9\-']+", cleaned) if t not in STOPWORDS and not t.isdigit()]
    keywords = []
    for t in tokens:
        if t not in keywords and len(t) > 1:
            keywords.append(t)

    parts = [f"{k.replace('_', ' ')} = {v}" for k, v in f.items()]
    if keywords:
        parts.append("keywords: " + ", ".join(keywords))
    interpretation = "; ".join(parts) if parts else "No specific filters recognised - showing best text matches."
    return SearchIntent(entity=entity, query=query, mode="heuristic", filters=f, keywords=keywords, interpretation=interpretation)


# ----------------------------------------------------------------------------
# Claude interpreter
# ----------------------------------------------------------------------------
_FILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["interpretation", "keywords", "filters"],
    "properties": {
        "interpretation": {"type": "string", "description": "One sentence restating what will be searched."},
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Free-text words to match against names, notes, and addresses. Exclude words that became filters.",
        },
        "filters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "state": {"type": ["string", "null"], "description": "Two-letter US state code"},
                "city": {"type": ["string", "null"]},
                "zip": {"type": ["string", "null"]},
                "trade": {"type": ["string", "null"], "description": "Canonical trade name from the vocabulary"},
                "qualification": {"type": ["string", "null"]},
                "status": {"type": ["string", "null"], "description": "Canonical status name from the vocabulary"},
                "customer_type": {"type": ["string", "null"]},
                "licensed": {"type": ["boolean", "null"]},
                "osha": {"type": ["boolean", "null"]},
                "will_travel": {"type": ["boolean", "null"]},
                "us_citizen": {"type": ["boolean", "null"]},
                "i9_complete": {"type": ["boolean", "null"]},
                "min_years": {"type": ["integer", "null"]},
                "max_years": {"type": ["integer", "null"]},
                "min_rate": {"type": ["number", "null"]},
                "max_rate": {"type": ["number", "null"]},
                "license_expiring_days": {"type": ["integer", "null"]},
                "on_hold": {"type": ["boolean", "null"]},
                "contract_on_file": {"type": ["boolean", "null"]},
                "min_revenue": {"type": ["number", "null"]},
                "has_active_projects": {"type": ["boolean", "null"]},
                "industry": {"type": ["string", "null"]},
                "salesman": {"type": ["string", "null"]},
                "customer": {"type": ["string", "null"], "description": "Customer business name (projects only)"},
                "manned": {"type": ["boolean", "null"]},
                "min_employees": {"type": ["integer", "null"]},
                "ocip": {"type": ["boolean", "null"]},
                "start_window": {
                    "type": ["string", "null"],
                    "enum": ["this_week", "this_month", "next_month", "this_year", None],
                },
            },
            "required": [],
        },
    },
}

_ENTITY_FILTER_KEYS = {
    "employees": {
        "state", "city", "zip", "trade", "qualification", "status", "licensed", "osha", "will_travel", "us_citizen",
        "i9_complete", "min_years", "max_years", "min_rate", "max_rate", "license_expiring_days",
    },
    "customers": {
        "state", "city", "zip", "status", "customer_type", "on_hold", "contract_on_file", "min_revenue",
        "has_active_projects", "industry", "salesman",
    },
    "projects": {"state", "city", "zip", "status", "customer", "manned", "min_employees", "ocip", "start_window", "trade"},
}


def _system_prompt(entity: str, vocab: dict[str, list[str]]) -> str:
    status_vocab = {
        "employees": list(EMPLOYEE_STATUS_SYNONYMS),
        "customers": list(CUSTOMER_STATUS_SYNONYMS),
        "projects": list(PROJECT_STATUS_SYNONYMS),
    }[entity]
    if settings.is_real_data:  # real data: no staff names, no customer-derived text leaves this PC (lookup labels are fine)
        vocab = {"cities": vocab.get("cities", []), "customer_types": vocab.get("customer_types", []), "industries": [], "salesmen": []}
    customer_types = vocab.get("customer_types") or list(CUSTOMER_TYPE_SYNONYMS)
    return (
        "You convert staffing-office search requests for MC Labor, a New England skilled-trades labor "
        f"staffing company, into structured filters for the '{entity}' table.\n"
        "Only use filter keys that apply to this entity: "
        + ", ".join(sorted(_ENTITY_FILTER_KEYS[entity]))
        + ".\nUse exact canonical values from these vocabularies:\n"
        f"- trades: {', '.join(TRADE_SYNONYMS)}\n"
        f"- qualifications: {', '.join(QUALIFICATION_SYNONYMS)}\n"
        f"- statuses: {', '.join(status_vocab)}\n"
        f"- customer types: {', '.join(customer_types)}\n"
        f"- states: {', '.join(STATES)}\n"
        f"- cities: {', '.join(vocab.get('cities', []))}\n"
        f"- industries: {', '.join(vocab.get('industries', []))}\n"
        f"- salesmen: {', '.join(vocab.get('salesmen', []))}\n"
        "Leave a filter null when the request does not mention it. Put leftover descriptive words "
        "(names, nicknames, note phrases) in keywords. Keep the interpretation to one short sentence."
    )


def claude_interpret(entity: str, query: str, vocab: dict[str, list[str]]) -> SearchIntent | None:
    if not settings.claude_allowed:  # no key, or real data without the owner's recorded approval
        return None
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        log.warning("anthropic SDK not installed; using heuristic search")
        return None

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=20.0, max_retries=1)
    try:
        response = client.beta.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": _FILTER_SCHEMA}},
            system=[{"type": "text", "text": _system_prompt(entity, vocab), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": query}],
        )
        if response.stop_reason == "refusal":
            log.warning("Claude declined the search request; using heuristic")
            return None
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
    except Exception as exc:  # noqa: BLE001 - any failure falls back to heuristic
        log.warning("Claude search interpretation failed (%s); using heuristic", exc)
        return None

    allowed = _ENTITY_FILTER_KEYS[entity]
    filters = {k: v for k, v in (data.get("filters") or {}).items() if v is not None and k in allowed}
    return SearchIntent(
        entity=entity,
        query=query,
        mode="claude",
        filters=filters,
        keywords=[k for k in data.get("keywords", []) if isinstance(k, str) and k.strip()],
        interpretation=data.get("interpretation") or "",
    )


def interpret(entity: str, query: str, vocab: dict[str, list[str]]) -> SearchIntent:
    intent = claude_interpret(entity, query, vocab)
    if intent is None:
        intent = heuristic_interpret(entity, query, vocab)
    if settings.is_real_data:  # restricted columns cannot be searched
        for key in ("us_citizen", "i9_complete"):
            intent.filters.pop(key, None)
    return intent


def ai_mode() -> str:
    return "claude" if settings.claude_allowed else "heuristic"
