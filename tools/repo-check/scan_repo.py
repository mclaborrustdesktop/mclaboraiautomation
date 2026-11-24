"""Before the code goes to a repository: is anything secret or real in it?

    python tools/repo-check/scan_repo.py            (from the project root; exit 1 when a BLOCKING finding exists)

1. Applies the root .gitignore (a close approximation of git's rules) to list what WOULD be committed.
2. Scans those files for credentials (passwords with values, API keys, tokens, private keys, connection strings
   with passwords), personal data patterns (SSNs, bank-looking numbers, e-mail addresses outside example domains),
   and references to local-only files. Each finding is BLOCKING (must not be committed) or INFO (internal
   infrastructure names, acceptable in a private repository; listed so the owner can decide).
3. Lists the files the ignore rules exclude, so it is visible that the local databases, env files, DPAPI files and
   reports stay on this PC.
Never prints a matched secret value: only the file, line and the kind of match.
"""
from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".txt", ".ps1", ".sql", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".env", ".example",
            ".csv", ".bicep", ".sh", ".css", ".html", ".dockerignore", ".gitignore", "Dockerfile", ".Caddyfile", ""}
PLACEHOLDER = re.compile(r"^(<[^>]*>|\$\{\{.*\}\}|\$[A-Z_]+|\{[^}]*\}|xxx+|\.\.\.|change-me.*|replace-with.*|your-.*|<sealed>|''|\"\")$", re.I)

BLOCKING = [
    ("password with a value", re.compile(r"(?i)\b(password|passwd|pwd|db_password|_secret|secret_key|jwt_secret|sync_api_key|api_key|apikey|access_key|client_secret|passphrase)\b\s*[=:]\s*['\"]?([^\s'\"#<$][^\s'\"#]{7,})")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")),
    ("GitHub token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("AWS-style access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Cloudflare API token", re.compile(r"(?i)cloudflare.{0,20}token\s*[=:]\s*['\"]?[A-Za-z0-9_-]{30,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("connection string with password", re.compile(r"(?i)(postgres(ql)?(\+psycopg)?|mssql\+pyodbc|mysql)://[^/\s:@]+:[^@\s<$]{3,}@")),
    ("ODBC/ADO password", re.compile(r"(?i)\b(pwd|password)=([^;\s<$'\"]{4,});")),
    ("Social Security number pattern", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
    ("bank routing + account pattern", re.compile(r"(?i)\b(routing|aba)\b[^\n]{0,20}\b\d{9}\b")),
    ("DPAPI secret file content", re.compile(r"^01000000d08c9ddf", re.I | re.M)),
]
INFO = [
    ("e-mail address outside example domains", re.compile(r"(?<![\w.])[A-Za-z0-9._%+-]+@(?!example\.(com|org|net)\b|company\b|mclabor\.com\b|<)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("company e-mail domain", re.compile(r"(?<![\w.])[A-Za-z0-9._%+-]+@mclabor\.com\b")),
    ("private network address", re.compile(r"\b(10\.(?!20\.)\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b")),  # 10.20.x = the Azure plan, not the office
    ("phone number", re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}")),
]
# tools/repo-check/local-names.txt (ignored by git): the office host names, addresses and account names, one per line.
# Any of them in a committed file is BLOCKING, because the repository may be public. The names never appear in this file.
LOCAL_NAMES = ROOT / "tools" / "repo-check" / "local-names.txt"
_names = [l.strip() for l in LOCAL_NAMES.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")] if LOCAL_NAMES.is_file() else []
if _names:
    BLOCKING.append(("office infrastructure name (from local-names.txt)", re.compile("|".join(re.escape(n) for n in _names), re.I)))

# lines where a pattern is an explanation, not data (keeps the report readable)
ALLOW_LINE = re.compile(r"(?i)(example|placeholder|never|do not|don't|must not|refuse|pattern|regex|re\.compile|re\.sub|\*\*\*|mask|synthetic|555-|format|template|<sealed>|\$\{\{)")


def load_ignore(root: Path) -> list[tuple[str, bool, bool]]:
    """[(pattern, negate, dir_only)] from the root .gitignore."""
    rules = []
    f = root / ".gitignore"
    if not f.exists():
        return rules
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        dir_only = line.endswith("/")
        rules.append((line.rstrip("/"), negate, dir_only))
    return rules


def ignored(rel: str, is_dir: bool, rules) -> bool:
    """Approximates git: last matching rule wins; a pattern without '/' matches any path component or basename."""
    result = False
    parts = rel.split("/")
    for pat, negate, dir_only in rules:
        if dir_only and not is_dir and not any(fnmatch.fnmatch("/".join(parts[:i]), pat.lstrip("/")) or fnmatch.fnmatch(parts[i - 1], pat) for i in range(1, len(parts))):
            continue
        anchored = "/" in pat.rstrip("/")
        p = pat.lstrip("/")
        hit = False
        if anchored:
            hit = fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p + "/*") or (p.startswith("**/") and any(fnmatch.fnmatch("/".join(parts[i:]), p[3:]) for i in range(len(parts))))
        else:
            hit = any(fnmatch.fnmatch(part, p) for part in parts)
        if hit:
            result = not negate
    return result


def walk(root: Path, rules):
    kept, skipped = [], []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or rel == ".git":
            continue
        if path.is_dir():
            continue
        if any(ignored("/".join(rel.split("/")[: i + 1]), True, rules) for i in range(len(rel.split("/")) - 1)) or ignored(rel, False, rules):
            skipped.append(rel)
        else:
            kept.append(rel)
    return kept, skipped


def scan(root: Path, files: list[str]):
    blocking, info = [], []
    for rel in files:
        p = root / rel
        if p.suffix.lower() not in TEXT_EXT and p.name not in ("Dockerfile", "Caddyfile", ".dockerignore", ".gitignore"):
            if p.stat().st_size > 2_000_000:
                info.append((rel, 0, f"large binary file ({p.stat().st_size // 1_000_000} MB)"))
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            is_comment = stripped.startswith(("#", "//", "--", "*", "<!--", "REM "))
            for label, rx in BLOCKING:
                m = rx.search(line)
                if m:
                    if label == "password with a value":
                        value = m.group(2).strip().strip("'\",;")
                        literal = not re.search(r"[(){}$.\[\]]|^(settings|os|self|env|args|cfg|body|user|password|secrets?)\b", value)  # a variable or call, not a value
                        if is_comment or not literal or PLACEHOLDER.match(value) or ALLOW_LINE.search(line) or "/tests/" in f"/{rel}" or value in ("first-pass-1", "mclabor2025"):
                            continue  # code handling a password, a comment, a placeholder, a test fixture or the published demo password
                    if label in ("Social Security number pattern", "bank routing + account pattern", "ODBC/ADO password") and ALLOW_LINE.search(line):
                        continue
                    blocking.append((rel, n, label))
            for label, rx in INFO:
                if rx.search(line) and not (label == "phone number" and "555-" in line):
                    info.append((rel, n, label))
    return blocking, info


def main() -> int:
    rules = load_ignore(ROOT)
    kept, skipped = walk(ROOT, rules)
    blocking, info = scan(ROOT, kept)
    print(f"Repository check of the folder {ROOT.name}")  # the folder name only: the full path would name this PC's account
    print(f"  files that would be committed: {len(kept)}   excluded by .gitignore: {len(skipped)}")
    print(f"  office names rule: {'ACTIVE (' + str(len(_names)) + ' names from local-names.txt)' if _names else 'INACTIVE - tools/repo-check/local-names.txt is missing'}")
    print("\nExcluded (stay on this PC):")
    shown = set()
    bulky = {"node_modules", ".venv", ".next", "__pycache__", ".pytest_cache", "reports"}
    for s in skipped:
        parts = s.split("/")
        cut = next((i + 1 for i, p in enumerate(parts) if p in bulky), None)
        top = "/".join(parts[:cut]) + "/ (whole folder)" if cut else s
        if top not in shown:
            shown.add(top)
            print(f"  - {top}")
    print(f"\nBLOCKING findings: {len(blocking)}")
    for rel, n, label in blocking:
        print(f"  !! {rel}:{n}  {label}")
    by_label: dict[str, list[str]] = {}
    for rel, n, label in info:
        by_label.setdefault(label, []).append(f"{rel}:{n}")
    print(f"\nINFO findings (acceptable in a private repository; listed for the owner): {len(info)}")
    for label, where in by_label.items():
        print(f"  - {label}: {len(where)} line(s), e.g. {', '.join(where[:4])}")
    print("\nRESULT:", "BLOCKED - fix the findings above before committing" if blocking else "CLEAN - nothing secret or real would be committed")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
