# Production readiness (audit 2026-11-20)

## Current state

| Area | Status |
|---|---|
| Backend | FastAPI on :8000, connected to the Next.js frontend on :3000 (CORS + JWT). |
| Data | Synthetic demo data in local SQLite `backend/mclabor_demo.db` (170 employees, 64 customers, 95 jobs). No production data. |
| Persistence | Creates/edits are committed to SQLite and survive restarts (verified). |
| AI search | Built-in offline parser (no `ANTHROPIC_API_KEY`). Claude path is implemented (structured JSON output, refusal fallback, heuristic fallback on any error) but not enabled. |
| Production DB | Adapter ready, **disabled**. Read-only guard, no schema changes, credentials only in `backend/.env`. |
| Access app / live McLabor DB | Not touched. Only the two schema CSV exports were read (copied to `docs/schema/`). |

## Production adapter safety layers

1. `DATA_SOURCE=demo` by default; a SQL Server URL is refused unless `DATA_SOURCE=production`.
2. Statement guard on the engine: only `SELECT` / `WITH` / `SET` reach the server until writes are approved;
   `CREATE/ALTER/DROP/TRUNCATE/EXEC/...` are always refused.
3. API returns `423 Locked` for every edit while production is read-only; activity logging is skipped.
4. Connection declares `ApplicationIntent=ReadOnly`; recommended SQL login has only `db_datareader`.
5. No `create_all` / seeding in production mode; credentials are masked in logs and never returned by the API.

## Schema findings (`python -m app.production schema`)

All 31 tables / 291 columns used by the app exist in the export, except four that live elsewhere in production and are
mapped automatically in production mode (read-only):

- `tblEmployee.YearsInTrade` -> `YearsInTradeID` -> `tblPullDownYearsInTrade` (number = label's leading digits; verify labels)
- `tblEmployee.WillTravel` -> `tblEmployeeB.WillTravel`
- `tblProject.SiteCity` / `SiteState` -> `SiteStateCityID` -> `tblPullDownStateCities` / `tblPullDownStates`

12 relationships the app relies on (e.g. `tblEmployee.EmTradeID -> tblPullDownTrade`) are **not enforced** as foreign keys
on the server. The API now validates every lookup id before saving.

## Remaining before 30+ real users

1. **Authentication for real staff** - DONE (2026-11-20). Web passwords are kept in a separate local store
   (`backend/web_auth.db`, `app/webauth.py`); the Access password column is never read or written. Lockout after 5
   failed attempts, admin-set temporary passwords, self-service change. Still to do per person: an administrator gives
   each staff member a web password (`python -m app.webauth set-password INITIALS` for the first admin).
2. **Read-only pilot against SQL Server** - BLOCKED on the server certificate (`docs/production-connection-report.md`,
   `docs/certificate-script-review.md`) and on a restricted login (`tools/prod-check/proposed-grants.sql`).
   Application side is ready: in production mode the app requests exactly the approved 33 tables / 288 columns and none
   of EmDOB / USCitizen / I9Complete / OfficeStaffPassword (`python -m app.prodverify`, output in
   `docs/production-query-verification.txt`). It refuses to start with the demo JWT secret, with encryption off, or
   with certificate verification off.
   Before writes are ever enabled: YearsInTrade, WillTravel, SiteCity and SiteState are read-only in production
   (stored elsewhere) and need a write mapping.
3. **Write approval** - only after the pilot: migration plan for web-only needs, sign-off reference in `PRODUCTION_WRITE_APPROVAL`.
4. **Hosting** - run on a Windows/Linux server (not a workstation) behind HTTPS (IIS/nginx), `JWT_SECRET` set, 4+ workers.
5. **Search at production scale** - filtering/ranking runs in Python over the filtered set; fine for the demo (24 ms median
   under 35 users) but should move into SQL Server (indexes / full-text) for the full employee table.
6. **Backups & monitoring** - SQL Server backups are the client's; add request logging/alerts for the web API.

## Update 2026-11-20 (later)

- Step-by-step procedure for the certificate, the read-only login and the first live test: `docs/sql-server-connection-procedure.md`.
- SQL Server is unpatched (15.0.2000.5): `docs/sql-server-update-review.md`.
- Fixed before it could reach production: boolean filters were sent as `IS 0` / `IS 1`, which SQL Server rejects. `python -m app.prodverify` now scans for such constructs.
- No default administrator in production: demo sign-in details are offered only on demo data, production uses a separate sign-in file and refuses to start if any account still has the demo password.
- Live search test for the first approved connection: `python -m app.livecheck` (counts and timings only).

## Production documents (2026-11-20)

The current, owner-facing set is in `docs/production/`: start with `00-production-readiness-report.md`.


## Environments (2026-11-20)

DEV-PC holds a restored copy, not the live database. The website now has DEMO, STAGING and PRODUCTION environments: `docs/environments.md`.

## Search performance (2026-11-20)

Search now filters, ranks and pages inside the database; see `docs/search-performance.md`. This replaces item 5 above ("Search at production scale"). Still unmeasured on SQL Server itself: the first real timings come from `python -m app.livecheck` on the staging copy.

