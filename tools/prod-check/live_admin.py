"""Runs one reviewed script on the live SQL Server and writes a report. Called by tools/production/Invoke-LiveAdmin.ps1,
which supplies the administrator credential through the environment (LIVE_ADMIN_LOGIN / LIVE_ADMIN_PASSWORD) and, for
the read-only login, READONLY_LOGIN_PASSWORD. Nothing secret is printed or written.

  --mode backup-status | verify-login | verifyonly         read-only
  --mode copy-only-backup | readonly-login  (+ --approve)  change the server; refused without --approve
  --trusted                                                Windows authentication (local validation on the office copy only)

Guards: the server must report the expected instance name (--expect) or nothing runs; the SQL files' own
"wrong server" guard is satisfied by substituting that verified name for the LIVE-HOST placeholder in memory."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

import pyodbc

HERE = Path(__file__).resolve().parent
REPORT_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "MCLabor" / "production" / "reports"
SCRIPTS = {
    "backup-status": HERE / "backup" / "0-live-backup-status.sql",
    "verify-login": HERE / "verify-readonly-login.sql",
    "copy-only-backup": HERE / "backup" / "4-live-copyonly-backup-with-checksum.sql",
    "readonly-login": HERE / "proposed-grants-production.sql",
}
CHANGING = {"copy-only-backup", "readonly-login"}

# verify-readonly-login.sql, 11 grids, what each must show (docs/production/18, step 3)
VERIFY_EXPECT = [
    ("running_as", lambda rows: rows and all(str(rows[0][i]).lower() == "mclabor_web_read" for i in (0, 1)) and str(rows[0][2]).lower() == "mclabor"),
    ("server roles all 0", lambda rows: len(rows) == 8 and all(int(r[1] or 0) == 0 for r in rows)),
    ("one database role mclabor_web_readonly", lambda rows: len(rows) == 1 and str(rows[0][0]).lower() == "mclabor_web_readonly"),
    ("database permissions = CONNECT + key-definition defaults", lambda rows: {str(r[0]).upper() for r in rows} <= {"CONNECT", "VIEW ANY COLUMN ENCRYPTION KEY DEFINITION", "VIEW ANY COLUMN MASTER KEY DEFINITION"} and any(str(r[0]).upper() == "CONNECT" for r in rows)),
    ("server permissions = CONNECT SQL only", lambda rows: {str(r[0]).upper() for r in rows} == {"CONNECT SQL"}),
    ("no write right on any table or view", lambda rows: len(rows) == 0),
    ("executable routines = 0", lambda rows: rows and int(rows[0][0] or 0) == 0),
    ("readable approved columns = 288", lambda rows: rows and int(rows[0][0] or 0) == 288),
    ("17 sensitive columns, none readable", lambda rows: len(rows) == 17 and all(int(r[-1] or 0) == 0 for r in rows)),
    ("no readable unapproved table", lambda rows: len(rows) == 0),
    ("visible databases = master, McLabor, tempdb", lambda rows: {str(r[0]).lower() for r in rows} == {"master", "mclabor", "tempdb"}),
]


def connect(server: str, trusted: bool, database: str = "master") -> pyodbc.Connection:
    base = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Encrypt=yes;TrustServerCertificate=yes;APP=mclabor-live-admin"
    if trusted:
        cs = base + ";Trusted_Connection=yes"
    else:
        login, pw = os.environ.get("LIVE_ADMIN_LOGIN"), os.environ.get("LIVE_ADMIN_PASSWORD")
        if not login or not pw:
            sys.exit("no administrator credential in the environment (run through Invoke-LiveAdmin.ps1)")
        cs = base + f";UID={login};PWD={pw}"
    return pyodbc.connect(cs, timeout=15, autocommit=True)


def batches(sql: str) -> list[str]:
    return [b for b in re.split(r"^\s*GO\s*$", sql, flags=re.M | re.I) if b.strip()]


def run_batches(cn: pyodbc.Connection, sql: str) -> tuple[list[tuple[list[str], list[tuple]]], list[str]]:
    """Executes every batch; returns the grids (column names, rows) and the server's messages (PRINT / RAISERROR text)."""
    grids, messages = [], []
    cur = cn.cursor()
    for b in batches(sql):
        cur.execute(b)
        while True:
            if cur.description:
                grids.append(([d[0] for d in cur.description], cur.fetchall()))
            for m in cur.messages:
                messages.append(str(m[1]))
            if not cur.nextset():
                break
    return grids, messages


def md_table(cols: list[str], rows: list[tuple], limit: int = 20) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows[:limit]:
        out.append("| " + " | ".join(str(v)[:60].replace("|", "/") for v in r) + " |")
    if len(rows) > limit:
        out.append(f"| ... {len(rows) - limit} more row(s) | " + " |" * (len(cols) - 1))
    if not rows:
        out.append("| (no rows) |" + " |" * (len(cols) - 1))
    return "\n".join(out)


def write_report(mode: str, server_name: str, login: str, grids, messages, summary: list[str]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = REPORT_DIR / f"live-{mode}-{stamp}.md"
    body = [f"# Live server: {mode} ({stamp})", "", f"Server: `{server_name}`. Run as: `{login}`. Script: `{SCRIPTS.get(mode, Path(mode)).name if mode in SCRIPTS else mode}`.", ""]
    body += ["## Summary", ""] + [f"- {s}" for s in summary] + [""]
    for i, (cols, rows) in enumerate(grids, 1):
        body += [f"## Grid {i}", "", md_table(cols, rows), ""]
    if messages:
        body += ["## Server messages", ""] + [f"    {m}" for m in messages] + [""]
    path.write_text("\n".join(body), encoding="utf-8")
    log = REPORT_DIR / "live-admin-log.md"
    with log.open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} `{mode}` on `{server_name}` as `{login}`: {summary[0] if summary else 'done'} -> {path.name}\n")
    return path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--expect", required=True, help="the instance name the server must report")
    ap.add_argument("--mode", required=True, choices=sorted(set(SCRIPTS) | {"verifyonly"}))
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--trusted", action="store_true")
    a = ap.parse_args(argv[1:])
    if a.mode in CHANGING and not a.approve:
        print(f"REFUSED: '{a.mode}' changes the live server and was not approved (--approve).")
        return 3

    cn = connect(a.server, a.trusted)
    cur = cn.cursor()
    name, login, sysadmin = cur.execute("SELECT CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)), SUSER_SNAME(), IS_SRVROLEMEMBER('sysadmin')").fetchone()
    print(f"connected: {name}  as {login}  sysadmin={sysadmin}")
    if name.lower() != a.expect.lower():
        print(f"REFUSED: the server reports '{name}', expected '{a.expect}'. Nothing was run.")
        return 4

    summary: list[str] = []
    if a.mode == "verifyonly":
        row = cur.execute("""SELECT TOP 1 bmf.physical_device_name, bs.backup_finish_date, bs.has_backup_checksums FROM msdb.dbo.backupset bs
                              JOIN msdb.dbo.backupmediafamily bmf ON bmf.media_set_id = bs.media_set_id
                              WHERE bs.database_name = N'McLabor' AND bs.type = 'D' ORDER BY bs.backup_finish_date DESC""").fetchone()
        if row is None:
            print("no full backup of McLabor is recorded on this server")
            return 5
        device, finished, checks = row
        print(f"RESTORE VERIFYONLY of {device} (backup of {finished}, checksums={checks}) ...")
        sql = f"RESTORE VERIFYONLY FROM DISK = N'{device}'" + (" WITH CHECKSUM" if checks else "")
        try:
            grids, messages = run_batches(cn, sql)
            summary = [f"VERIFYONLY OK: {device} (backup finished {finished})"] + messages
        except pyodbc.Error as exc:
            summary = [f"VERIFYONLY FAILED: {str(exc)[:200]}"]
            grids, messages = [], []
    else:
        sql = SCRIPTS[a.mode].read_text(encoding="utf-8-sig")
        sql = sql.replace("N'LIVE-HOST\\SQLEXPRESS'", f"N'{name}'").replace("LIVE-HOST\\SQLEXPRESS", name)
        if a.mode == "readonly-login":
            pw = os.environ.get("READONLY_LOGIN_PASSWORD", "")
            if len(pw) < 16:
                print("no generated password for mclabor_web_read in the environment")
                return 6
            sql = sql.replace("<<TYPE-A-LONG-PASSWORD-HERE>>", pw.replace("'", "''"))
        if a.mode == "verify-login":
            cn.close()
            cn = connect(a.server, a.trusted, database="McLabor")
        grids, messages = run_batches(cn, sql)

        if a.mode == "backup-status":
            latest = {str(r[0]).upper(): r for cols, rows in grids[2:3] for r in rows}
            full = latest.get("FULL")
            verdict = grids[7][1][0][0] if len(grids) > 7 and grids[7][1] else "(no verdict grid)"
            restores = len(grids[4][1]) if len(grids) > 4 else 0
            if full is None:
                summary = ["GATE FAILED: no full backup of McLabor recorded", f"verdict: {verdict}"]
            else:
                age, copy_only, checks, damaged, size, by, device, exists = full[2], full[3], full[4], full[5], full[6], full[7], full[8], full[9]
                ok = int(age) <= 24 and bool(checks) and not bool(damaged) and int(exists or 0) != 0
                summary = [("GATE PASSED (pending a RESTORE VERIFYONLY or restore test)" if ok else "GATE FAILED") + f": newest full backup finished {full[1]}, {age} h ago, {size} MB, checksums={checks}, damaged={damaged}, copy_only={copy_only}, by {by}",
                           f"file: {device} (exists={exists}; -1 = could not ask, 1 = present, 0 = missing)",
                           f"restores recorded on the server: {restores}",
                           f"server verdict: {verdict}"]
            if len(grids) > 8:
                summary += ["free space: " + "; ".join(f"{r[0]}: {r[1]} MB" for r in grids[8][1])]
        elif a.mode == "verify-login":
            results = []
            for i, (label, test) in enumerate(VERIFY_EXPECT):
                rows = grids[i][1] if i < len(grids) else []
                try:
                    ok = bool(test(rows))
                except Exception:  # noqa: BLE001
                    ok = False
                results.append((ok, label))
            failed = [label for ok, label in results if not ok]
            summary = [("READ-ONLY LOGIN VERIFIED: all 11 grids as expected" if not failed else f"VERIFICATION FAILED: {len(failed)} grid(s) differ: " + "; ".join(failed))]
            summary += [f"{'PASS' if ok else 'FAIL'} {label}" for ok, label in results]
        elif a.mode == "readonly-login":
            final = grids[-2:] if len(grids) >= 2 else grids
            summary = ["READ-ONLY LOGIN SCRIPT RAN: " + "; ".join(f"{cols[0]}={rows[0][0]}" + (f", {cols[1]}={rows[0][1]}" if len(cols) > 1 and rows else "") for cols, rows in final if rows) + "; unexpected_role rows: " + str(len(final[-1][1]) if final else "?")] + messages
        elif a.mode == "copy-only-backup":
            summary = ["COPY_ONLY BACKUP SCRIPT RAN"] + messages

    path = write_report(a.mode, name, login, grids, messages, summary)
    for s in summary:
        print(" ", s)
    print(f"report: {path}")
    return 0 if (summary and ("FAILED" not in summary[0] and "REFUSED" not in summary[0])) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
