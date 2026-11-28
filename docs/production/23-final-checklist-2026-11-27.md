# 23. Final checklist: MC Labor AI Automation on the office PC (2026-11-27, late evening)

Everything below ran on the office PC (`DEV-PC`) against the **restored copy of the McLabor database (data as of
2026-11-13 17:00)** with the read-only login, the password-only sign-in and the production build of the website.
No record left the PC, no paid service was created, the live server was not contacted. Reports with every line:
`tools/prod-check/reports/staging-pilot-20261127-232248.txt`, `loadtest-local-20-users-2-20261127-233631.txt`.
This is **not live production**: the data is a two-week-old snapshot (section D).

## A. WORKING (verified tonight)

| # | Item | Evidence |
|---|---|---|
| 1 | SQL Server to SQLite synchronization, all 33 approved tables | agent run `incremental`, 33 tables, 1,209,951 source rows, 947,106 upserted in 451 s after the fix below, 0 warnings; source label `DEV-PC\SQLEXPRESS/McLabor` |
| 2 | Reconciliation of all 33 tables | row counts SQL Server vs mirror: **33 of 33 MATCH, 1,209,951 = 1,209,951** (`reconcile_local_mirror.py`) |
| 3 | FastAPI backend on real records | `DATA_SOURCE=staging`, 4 workers, read-only, restricted login, certificate verified; health reports staging / sqlserver / passcode / writes off |
| 4 | React website (production build, `next build` + `next start`) | sign-in page with one "Access Password" field; dashboard, lists, AI search, tracking all render real records; strict CSP (no `unsafe-eval`) with no console errors; `/api` forwarded by the site itself |
| 5 | Dashboard | 178,993 employees (5,179 active, 85 available), 106,828 customers (1,694 active), 15,748 jobs (7,178 active), 16 staff accounts, hours per week chart, workforce by trade |
| 6 | Employee search | pilot: all employees, by trade, by status, trade+status, licensed, 5+ years, by state, last name, first+last, word in notes, newest / most experienced first, pages 2 and 100, 200 per page, 201 refused, past 10,000 refused: **all equal to direct database counts**; 192 records opened |
| 7 | Customer search | all, by state (MA, CT), city, ZIP prefix, on hold, word "electric", phone area code, newest / highest revenue first, page 2: all equal; 160 records opened |
| 8 | Job search | all newest first, status, state, city, not manned, word "school", by site name, page 2: all equal; 161 records opened |
| 9 | Staffing (weekly tracking) | list of weeks, first page, week ending 2026-11-13 (259 assignments, 232 workers, 82 customers), week + search word: all equal |
| 10 | AI Search (built-in parser, no outside service) | 9 of 9 plain-English questions understood with the right filters; in the browser "licensed electricians in Texas" → 21,611 matches with facets in 2.0 s |
| 11 | Changes impossible | website answers 423 to 8 kinds of change; SQL Server refuses UPDATE / DELETE / INSERT for the login and refuses SSN, bank, date-of-birth, staff-password columns and `SELECT *`; row counts unchanged after the tests |
| 12 | Performance, 20 people | 20 people, 8 searches each, every 2 to 6 s: 160 of 160 answered, typical 0.33 s, 95 % within 2.4 s, slowest 6.4 s. Pilot's 35 people, 210 searches: all answered, typical 0.24 s, 95 % within 2.4 s, slowest 5.0 s. (With the sync running at the same time one request of 160 timed out: run the twice-daily sync outside office hours or accept one slow search.) |
| 13 | Security, 52 checks | no access without the password (11 endpoints 401), demo sign-in refused, forged token refused, correct password unlocks as the configured staff record, session 8 h bound to site mode and environment, no sensitive field in records, no staff password material, all writes 423, ingest endpoint absent on SQL Server, hostile search input harmless, page size cap, CSP / nosniff / frame DENY / Referrer / Permissions / HSTS headers, unlock audit log, **lockout after 5 wrong passwords (429, Retry-After 1800 s) that does not say which part was wrong** |

## B. COMPLETED (prepared, verified, nothing paid for, nothing uploaded)

| # | Item | State |
|---|---|---|
| 1 | Sync agent speed fix | the agent's state file committed every row (profiled: 42 of 45 s in `executemany`); now one transaction per batch: about 80 → 2,000 rows/s. Unit tests pass (12 sync tests + 33 environment/device/guard tests). |
| 2 | Start-up race fix, development CSP fix, test-tool sign-in for password-only mode | committed (e57c8b8, dc71595) |
| 3 | Production deployment package | `deploy/railway/create-production.ps1` plan mode prints the full plan (project, PostgreSQL, two services, variables from the verified files, domain for the frontend only, redeploys, daily + weekly snapshots + point-in-time recovery, checks); estimated 12 USD a month inside the Pro allowance. **Not executed.** |
| 4 | Production variables | `verify_production_variables.py`: **ALL PASSED** (28 checks) after `SITE_DEFAULT_USER=RMV` (the owner's own staff record; change in the risk acknowledgment if another record should be the default) |
| 5 | Production website build | `next build` passes with the strict policy; served tonight on this PC |
| 6 | Client-performed one-time setup for the live server | package on the Desktop (`21`): read-only login, verified certificate, encrypted password hand-off; rehearsed, all checks pass |
| 7 | Local snapshot preserved | the restored copy of 2026-11-13 stays on `DEV-PC\SQLEXPRESS`; the local mirror `%LOCALAPPDATA%\MCLabor\sync\local-mirror-staging.db` holds the 33 tables; the backup file `C:\ZZZ-SQL\McLabor_2026_11_13_170000.80.bak` is untouched |

## C. Fresh-data feed on this PC: none found

Checked without extracting any credential: no mapped network drive, no non-Microsoft scheduled task, no shared folder,
one backup file (copied by hand on 2026-11-13), no exported `.csv`/`.xlsx`/`.bak` newer than that except files this
project created, and the Access files link to the live server's *development* database with a saved password that is
not extracted. There is no authorized, regularly updated export the agent could read. The November 13 snapshot is
therefore the data the application uses, and **live updates are the remaining blocker**.

## D. BLOCKED (exact reason)

| # | Item | Reason |
|---|---|---|
| 1 | Current data | the only database this PC may read is the 2026-11-13 copy. Every path to newer data needs one action by the client on the live server (`21`: 15 minutes of their administrator, no credentials shared with us) or a regular export from it, neither of which exists today. |
| 2 | "Live production" label | not applicable until 1 is resolved; the website shows "STAGING - test copy" and reads the snapshot. |
| 3 | Railway production project, first upload, 06:00/12:30 schedule | the owner's explicit approvals (`19` section D, `docs/cloud/20`); nothing created or sent. |
| 4 | Risk acknowledgment | the owner's signature and the `WEB_ADMINS` yes/no choice (`docs/cloud/20`). |

## E. Running state left on this PC

Backend 127.0.0.1:8000 (4 workers, staging, read-only), website 127.0.0.1:3000 (production build), the local mirror.
`backend\.env` selects staging (password-only sign-in, staging password); `frontend\.env.local` points the site at its
own `/api` proxy (previous file kept as `.env.local.bak-2026-11-27`). To stop: end the uvicorn and node processes and
rename `backend\.env` to `.env.off` (DEMO again).
