"""Container smoke test: is a running website stack healthy, isolated and correctly guarded? Synthetic DEMO data only.

    backend\\.venv\\Scripts\\python.exe tools\\containers\\smoke_test.py [--api http://127.0.0.1:8000] [--web http://127.0.0.1:3000]
                                                               [--expect demo|staging|production] [--through-proxy https://site]

Against the DEMO profile (default): health and readiness, request ids, open access, every list page, the AI
search, a write that works (demo only) and the health route of the frontend. Against a real-data stack
(--expect staging/production, --through-proxy): the backend must refuse anonymous and forged requests, the
proxy must demand sign-in, and the backend port must not be reachable from where the test runs.
Prints PASS/FAIL lines and exits 1 on any failure. Sends no real data anywhere.
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
from urllib.parse import urlparse

import httpx

failures = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""), flush=True)


def wait_for(url: str, seconds: int = 90) -> httpx.Response | None:
    deadline = time.time() + seconds
    last = None
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code < 500:
                return r
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        time.sleep(2)
    print(f"  no answer from {url} within {seconds}s ({last})")
    return None


def port_open(url: str) -> bool:
    u = urlparse(url)
    try:
        with socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)), timeout=3):
            return True
    except OSError:
        return False


def demo_checks(api: str, web: str) -> None:
    print("DEMO stack (synthetic data)")
    r = wait_for(f"{api}/api/health")
    check(r is not None and r.status_code == 200, "backend liveness /api/health")
    if r is None:
        return
    h = r.json()
    check(h.get("environment") == "demo" and h.get("database") == "sqlite" and h.get("ai_mode") == "heuristic", "backend reports DEMO, SQLite, built-in parser", str(h))
    check(h.get("access_mode") == "open", "DEMO has no sign-in page (open access)")
    r = httpx.get(f"{api}/api/ready", timeout=10)
    check(r.status_code == 200 and r.json().get("checks") == {"database": "ok", "sign_in_store": "ok"}, "backend readiness /api/ready", r.text[:120])
    check(bool(r.headers.get("X-Request-ID")), "every response carries X-Request-ID")
    r = httpx.get(f"{api}/api/health", headers={"X-Request-ID": "smoke-0001"}, timeout=10)
    check(r.headers.get("X-Request-ID") == "smoke-0001", "the proxy's request id is kept")
    with httpx.Client(base_url=api, timeout=30) as c:
        me = c.get("/api/auth/me")
        check(me.status_code == 200 and me.json().get("Profile") is True, "open access signs the visitor in as the demo administrator")
        for path in ("/api/employees", "/api/customers", "/api/projects", "/api/tracking", "/api/lookups", "/api/dashboard", "/api/users", "/api/system/status"):
            r = c.get(path)
            check(r.status_code == 200, f"GET {path}", f"HTTP {r.status_code}")
        r = c.get("/api/employees", params={"q": "smith"})
        check(r.status_code == 200 and "total" in r.json(), "employee word search")
        r = c.post("/api/search", json={"entity": "employees", "query": "licensed electricians in MA"})
        check(r.status_code == 200 and r.json().get("ai", {}).get("mode") == "heuristic" and r.json()["ai"]["filters"].get("trade") == "Electrician", "AI search understood on the server, no outside service", str(r.json().get("ai", {}).get("filters")))
        st = c.get("/api/system/status").json()
        check(st.get("environment") == "demo" and st["database"]["mode"].startswith("demo") and st["outside_ai_service"]["used"] is False, "status page: demo, no outside AI service")
        def leaks(obj) -> bool:  # any key that names a password/secret must hold a flag or a number, never text
            if isinstance(obj, dict):
                return any((("password" in k.lower() or "secret" in k.lower()) and isinstance(v, str) and v) or leaks(v) for k, v in obj.items())
            return isinstance(obj, list) and any(leaks(x) for x in obj)
        check(not leaks(st), "status page holds no password or secret value")
        r = c.post("/api/customers/1/notes", json={"CustomerNote": "container smoke test"})
        check(r.status_code == 201, "a write works in the demo (synthetic data, persistent inside the container)", f"HTTP {r.status_code}")
        r = c.get("/api/employees/99999999")
        check(r.status_code == 404 and "Traceback" not in r.text, "unknown record answers 404 without a stack trace")
    r = wait_for(f"{web}/healthz")
    check(r is not None and r.status_code == 200 and r.json().get("status") == "ok", "frontend liveness /healthz")
    r = wait_for(f"{web}/")
    check(r is not None and r.status_code == 200 and "html" in r.headers.get("content-type", ""), "frontend home page")


def real_data_checks(api: str | None, proxy: str | None, expect: str) -> None:
    print(f"{expect.upper()} stack (real-data guards)")
    if api:
        reachable = port_open(api)
        check(not reachable, "backend port is NOT reachable from here (only the proxy may reach it)", api)
        if reachable:
            r = httpx.get(f"{api}/api/employees", timeout=10)
            check(r.status_code == 401, "backend refuses anonymous requests", f"HTTP {r.status_code}")
            r = httpx.get(f"{api}/api/auth/me", headers={"X-Auth-Request-Email": "someone@example.com", "X-MS-CLIENT-PRINCIPAL-NAME": "someone@example.com"}, timeout=10)
            check(r.status_code in (401, 403), "backend refuses a forged identity header", f"HTTP {r.status_code}")
            h = httpx.get(f"{api}/api/health", timeout=10).json()
            check(h.get("environment") == expect and h.get("access_mode") in ("login", "gateway") and h.get("ai_mode") == "heuristic", f"backend reports {expect}, sign-in required, built-in parser", str(h))
    if proxy:
        with httpx.Client(base_url=proxy, timeout=20, follow_redirects=False, verify=True) as c:
            r = c.get("/api/auth/me")
            check(r.status_code in (401, 302, 303, 307), "proxy demands sign-in for the API", f"HTTP {r.status_code}")
            r = c.get("/")
            check(r.status_code in (401, 302, 303, 307), "proxy demands sign-in for the site", f"HTTP {r.status_code}")
            r = c.get("/api/auth/me", headers={"X-Gateway-Secret": "x" * 48, "X-Auth-Request-Email": "someone@example.com"})
            check(r.status_code in (401, 302, 303, 307), "a visitor's forged gateway headers are stripped by the proxy", f"HTTP {r.status_code}")
            check(c.get("/healthz").status_code in (401, 302, 303, 307, 200), "proxy answers (frontend health behind sign-in or open)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--web", default="http://127.0.0.1:3000")
    ap.add_argument("--expect", default="demo", choices=["demo", "staging", "production"])
    ap.add_argument("--through-proxy", default=None, help="https address of the proxy for a real-data stack")
    a = ap.parse_args()
    if a.expect == "demo":
        demo_checks(a.api, a.web)
    else:
        real_data_checks(a.api, a.through_proxy, a.expect)
    print(f"RESULT: {'PASSED' if not failures else str(failures) + ' FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
