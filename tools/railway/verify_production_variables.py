"""Verifies the PRODUCTION variable files before anything is created on Railway, with the backend's own settings rules.
Usage: python verify_production_variables.py <backend.production.variables.env> [<sync.env>]
Optional: SITE_PW_CHECK in the environment (the production password, decrypted by the caller) to prove the hash matches.
Prints PASS/FAIL lines and nothing secret; exit 0 when everything passes."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

fails = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail else ""))


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main(argv: list[str]) -> int:
    env_path = Path(argv[1])
    sync_path = Path(argv[2]) if len(argv) > 2 else None
    vars_ = parse(env_path)
    print(f"1. {env_path.name}: the backend's own rules")
    # Railway references are resolved in the cloud; stand in a private-network URL of the same shape here
    for k, v in vars_.items():
        if "${{" in v:
            vars_[k] = "postgresql+psycopg://railway:x@postgres.railway.internal:5432/railway"
    os.environ.update(vars_)
    os.environ["MCLABOR_SETTINGS_FILE"] = os.devnull  # ignore any local .env
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app.config import settings  # noqa: E402
    from app.security import verify_password  # noqa: E402

    problems = settings.environment_problems()
    check(settings.environment == "production", "DATA_SOURCE selects production", settings.environment)
    check(not problems, "environment_problems() is empty", "; ".join(problems)[:300])
    check(settings.access == "passcode", "entrance is the single access password", settings.access)
    check(settings.search_only, "search-only (every write refused)")
    check(not settings.site_device_approval, "device layer off")
    check(settings.is_postgres and "railway.internal" in (settings.postgres_url or ""), "database is the private Railway PostgreSQL reference")
    check((vars_.get("SITE_PASSWORD_LABEL") or "").lower() not in ("", "initial", "staging", "test", "demo"), "password label is a production label", vars_.get("SITE_PASSWORD_LABEL", ""))
    check(len(vars_.get("JWT_SECRET", "")) >= 32, "JWT_SECRET is 32+ characters")
    check(len(vars_.get("SYNC_API_KEY", "")) >= 32, "SYNC_API_KEY is 32+ characters")
    src = vars_.get("SYNC_EXPECTED_SOURCE", "")
    check(bool(re.fullmatch(r"[A-Za-z0-9-]+\\[A-Za-z0-9]+/[A-Za-z0-9]+", src)), "SYNC_EXPECTED_SOURCE names the live server and database", src)
    check(bool(vars_.get("OFFICE_HOSTS")), "OFFICE_HOSTS lists the office servers (never a mirror target)")
    check(vars_.get("ANTHROPIC_API_KEY", "") == "", "no outside AI service key")
    check(vars_.get("CORS_ORIGINS", "").startswith("https://"), "CORS origin is https", vars_.get("CORS_ORIGINS", ""))
    default_user = vars_.get("SITE_DEFAULT_USER", "")
    check(bool(default_user) and "<" not in default_user and default_user.upper() not in ("TBD", "PENDING"), "SITE_DEFAULT_USER names the staff record everyone acts as (to be confirmed by the client)", default_user)

    print("2. Different from staging in every secret")
    staging_dir = Path(os.environ["LOCALAPPDATA"]) / "MCLabor" / "staging"
    st_hash_file = staging_dir / "site-password-hash-initial.txt"
    if st_hash_file.exists():
        st_hash = st_hash_file.read_text(encoding="utf-8").strip().split("=", 1)[-1]
        check(st_hash != vars_.get("SITE_PASSWORD_HASH"), "production password hash differs from the staging one")
    for name in ("railway-staging-secrets-ray.json", "railway-staging-secrets.json"):
        f = staging_dir / name
        if f.exists():
            st = json.loads(f.read_text(encoding="utf-8"))
            for key, var in (("jwt", "JWT_SECRET"), ("sync", "SYNC_API_KEY")):
                if st.get(key):
                    check(st[key] != vars_.get(var), f"{var} differs from staging ({name})")
    pw = os.environ.get("SITE_PW_CHECK")
    if pw:
        check(verify_password(pw, vars_.get("SITE_PASSWORD_HASH", "")), "the DPAPI-stored production password matches SITE_PASSWORD_HASH")
        check(pw != "mclabordata2026" and len(pw) >= 16, "production password is not the disclosed staging one and is 16+ characters", f"{len(pw)} characters")
    else:
        print("  (SITE_PW_CHECK not given: hash/password match not checked)")

    if sync_path is not None:
        print(f"3. {sync_path.name}: the office agent's settings")
        sv = parse(sync_path)
        check(sv.get("DATA_SOURCE") == "production", "agent reads the live environment")
        check(sv.get("PRODUCTION_DB_USER") == "mclabor_web_read", "agent uses the read-only login, never an administrator")
        check(sv.get("PRODUCTION_WRITES_ENABLED", "").lower() == "false", "writes disabled for the agent")
        check(sv.get("PRODUCTION_DB_ENCRYPT", "").lower() == "true" and sv.get("PRODUCTION_DB_TRUST_SERVER_CERTIFICATE", "").lower() == "false", "TLS to the server with certificate verification")
        check(f"{sv.get('PRODUCTION_DB_EXPECTED_SERVER_NAME')}/{sv.get('PRODUCTION_DB_NAME')}" == src, "agent's announced source equals the website's SYNC_EXPECTED_SOURCE")
        check(sv.get("SYNC_API", "").startswith("https://"), "agent sends to an https address", sv.get("SYNC_API", ""))
    print(f"\nRESULT: {'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
