"""Many people searching at once against a RUNNING STAGING website. Timings and status codes only.

    powershell -File tools\\staging\\run-readonly.ps1 ..\\tools\\staging\\loadtest.py [people] [searches each] [base url] [label]

The website under test is normally the one loadtest-staging.ps1 starts on port 8001 (the DEMO website on port
8000 is left alone). Sign-in is a 20-minute test token for the first staff number in WEB_ADMINS, made on this PC;
no password is created. Only GET requests are sent. The report (counts and timings) is saved under
tools\\prod-check\\reports\\.
"""
import datetime as dt
import random
import statistics
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import httpx  # noqa: E402
import jwt  # noqa: E402

from app.config import settings  # noqa: E402

people = int(sys.argv[1]) if len(sys.argv) > 1 else 35
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 6
BASE = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8001"
label = sys.argv[4] if len(sys.argv) > 4 else f"{people}users"
assert settings.is_staging
admin_id = next(int(a) for a in settings.web_admin_set if a.isdigit())
now = dt.datetime.now(dt.timezone.utc)
token = jwt.encode({"sub": str(admin_id), "env": "staging", "iat": now, "exp": now + dt.timedelta(minutes=20)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
if settings.access == "passcode":  # password-only site: the backend accepts only its own site-mode token (security.create_site_token)
    token = jwt.encode({"sub": str(admin_id), "mode": "site", "who": "pilot-test", "env": settings.environment, "iat": now, "exp": now + dt.timedelta(minutes=20)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)

MIX = [
    ("employees: first page", "/api/employees", {}),
    ("employees: one trade", "/api/employees", {"trade_id": 1}),
    ("employees: last name", "/api/employees", {"q": "smith"}),
    ("employees: first + last name", "/api/employees", {"q": "john smith"}),
    ("employees: one status", "/api/employees", {"status_id": 1}),
    ("employees: page 7", "/api/employees", {"page": 7}),
    ("customers: first page", "/api/customers", {}),
    ("customers: one state", "/api/customers", {"state": "MA"}),
    ("customers: word in name", "/api/customers", {"q": "electric"}),
    ("jobs: first page", "/api/projects", {}),
    ("jobs: one status", "/api/projects", {"status_id": 1}),
    ("tracking: first page", "/api/tracking", {}),
]
results = defaultdict(list)
lock = threading.Lock()
lines: list[str] = []


def say(s: str) -> None:
    lines.append(s)
    print(s, flush=True)


def person(seed: int) -> None:
    rnd = random.Random(seed)
    with httpx.Client(base_url=BASE, timeout=90, headers={"Authorization": f"Bearer {token}"}) as c:
        time.sleep(rnd.uniform(0, 3))
        for _ in range(rounds):
            label_, path, params = rnd.choice(MIX)
            t0 = time.perf_counter()
            try:
                code = c.get(path, params=params).status_code
            except httpx.HTTPError as exc:
                code = type(exc).__name__
            with lock:
                results[label_].append((code, time.perf_counter() - t0))
            time.sleep(rnd.uniform(2, 6))


health = httpx.get(f"{BASE}/api/health", timeout=30).json()
assert health.get("environment") == "staging" and health.get("ai_mode") == "heuristic", health
started = time.perf_counter()
threads = [threading.Thread(target=person, args=(n,)) for n in range(people)]
[t.start() for t in threads]
[t.join() for t in threads]
say(f"Load test [{label}] - {people} people, {rounds} searches each, a search every 2 to 6 seconds ({time.perf_counter() - started:.0f}s in total) against {BASE} ({health['environment']}, read-only)")
say(dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
say(f"{'search':32} {'n':>3} {'typical':>8} {'95%':>8} {'slowest':>8}  answers")
everything = []
for label_, rows in sorted(results.items()):
    secs = sorted(s for _, s in rows)
    everything += rows
    codes = defaultdict(int)
    for code, _ in rows:
        codes[code] += 1
    say(f"{label_:32} {len(rows):>3} {statistics.median(secs):>7.2f}s {secs[max(0, int(len(secs) * 0.95) - 1)]:>7.2f}s {max(secs):>7.2f}s  " + ", ".join(f"{k}: {v}" for k, v in codes.items()))
secs = sorted(s for _, s in everything)
bad = sum(1 for code, _ in everything if code != 200)
busy = sum(1 for code, _ in everything if code == 503)
say(f"ALL: {len(secs)} searches, {bad} not answered normally ({busy} 'busy, try again'); typical {statistics.median(secs):.2f}s, 95% within {secs[max(0, int(len(secs) * 0.95) - 1)]:.2f}s, slowest {secs[-1]:.2f}s")
out = ROOT / "tools" / "prod-check" / "reports" / f"loadtest-{label}-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Report saved: {out}")
