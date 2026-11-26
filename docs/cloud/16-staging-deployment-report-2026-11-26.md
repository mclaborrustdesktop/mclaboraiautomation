# 16. Railway STAGING deployment report (2026-11-26)

**Website:** https://frontend-production-b331880c.up.railway.app (Railway-issued HTTPS certificate; plain HTTP redirects)

**Account and project:** Railway workspace "mclaborrustdesktop's Projects" (ray@mclabor.com), plan **Pro** (customer state
ACTIVE, payment method on file; billing was not touched by the deployment). Project `mclabor-staging`, Railway
environment `production` (the application runs as **STAGING**: `DATA_SOURCE=staging`). Code: GitHub
`mclaborrustdesktop/mclaboraiautomation`, branch `main`, commit `bb52bfc` (the existing project, no rebuild).

## 1. What runs

| Service | Source | Network | Health check | Size (first hour, incl. the 30-minute data load) |
|---|---|---|---|---|
| `Postgres` (PostgreSQL 18, Railway template) | image `ghcr.io/railwayapp-templates/postgres-ssl:18` | private only: no public domain, no TCP proxy | Railway's | CPU avg 0.003 vCPU, memory avg 105 MB, volume 500 MB (85 MB used) |
| `backend` (FastAPI, 2 workers) | repo root `/`, `deploy/railway/backend.Dockerfile` | private only (`backend.railway.internal:8000`), no public domain | `/api/ready` | CPU avg 0.05 vCPU (max 0.19), memory avg 205 MB (max 450 MB) |
| `frontend` (Next.js standalone) | repo folder `frontend`, its `Dockerfile` | **the only public address**; `/api/*` is proxied over the private network to the backend | `/healthz` | CPU avg 0.007 vCPU, memory avg 40 MB (max 104 MB) |

Variables: 21 on the backend (database references `${{Postgres.DATABASE_URL}}`, `SITE_MODE=search-only`,
`ACCESS_MODE=login`, `WEB_ADMINS=ARI`, seat limit 20, `JWT_SECRET`, `SYNC_API_KEY`, `WEB_BOOTSTRAP_PASSWORD`, CORS,
logging), 3 on the frontend. Secret values exist only in Railway and in the owner's local folder
`%LOCALAPPDATA%\MCLabor\staging` on COMP-27; none is in the repository or in this report.

## 2. Data

Synthetic only. The office sync agent (`app.syncagent`) ran once from this PC against a **synthetic SQLite source**
(`app.synthdb`, scale 0.2, every value invented, restricted columns empty) through the website address with the sync
key: bootstrap created the 33 mirror tables; full run **33 tables, 173,518 rows sent, 0 deleted, 0 warnings, 201
batches, 30.5 minutes**. The site shows "last successful sync" = 2026-11-26 14:42 UTC, level fresh. Employees 35,435
(duplicates hidden), customers 21,365, jobs 3,149, weekly tracking 38,445. No connection to SERVER-1; the twice-daily
scheduled task is **not** registered.

## 3. Tests (staging_checks.py against the public address, all PASS)

- Health: backend reports staging on PostgreSQL, search-only, writes off, login required; readiness database ok and
  sign-in store ok; frontend health; login page over HTTPS; HTTP 301 to HTTPS.
- Security: anonymous GET on employees, customers, projects, tracking, users, system status, lookups and sync status
  all 401; anonymous AI search 401; forged bearer token 401; sync ingest without key / with a wrong key refused; no
  API docs on the public address; backend and PostgreSQL have no public domain (checked in Railway).
- Sign-in: wrong password 401; the one-time bootstrap password is refused for anyone but the first administrator;
  `ARI` (synthetic administrator) signs in once with it and is told to change the password; the token works; the
  record says administrator and search-only.
- Data and search: employee, customer, job and tracking lists come from the mirror; no SSN or bank fields in any
  payload; AI search (built-in parser, no outside AI service) returns employees in 0.2 s and customers; lookups carry
  search-only; system status and users page open for the administrator; last successful sync recorded.
- Writes: POST employees, POST customers, PUT employee, DELETE employee and the user-management password endpoint are
  refused (423 / blocked) **even for the administrator**.

## 4. Persistence and backups

- Volume `postgres-volume` (500 MB) at `/var/lib/postgresql/data`, state READY, survived the removal of all
  deployments on 2026-11-25 and re-attached on the Pro redeploy.
- Persistence test after the load: PostgreSQL restarted on purpose; the backend returned to ready and the full test
  script was rerun: **all checks passed**, same row counts (35,435 / 21,365 / 3,149 / 38,445), sync status intact,
  sign-in store intact (the administrator's password survived the restart).
- Railway volume backups: schedule enabled **daily** (18:36 UTC) and **weekly** (Saturday 09:37 UTC); one on-demand
  backup taken at 14:44 UTC on 2026-11-26 (id `200b0cee…`). Point-in-time recovery is off (not needed for a mirror
  that the office re-feeds). The encrypted R2 backup service in `deploy/railway/backup` stays optional.
- Deployment health checks: backend `/api/ready` (120 s), frontend `/healthz` (120 s), restart ON_FAILURE x5.

## 5. What the owner does next

1. Open the website, sign in as `ARI` with the one-time bootstrap password (given privately, not in this file), choose a
   real password when asked. Then the variable `WEB_BOOTSTRAP_PASSWORD` can be deleted from the backend service
   (`railway variable delete WEB_BOOTSTRAP_PASSWORD --service backend`); it no longer applies anyway.
2. Grant the other test users on the Users page (roster against the 20-seat limit).
3. Optional, in Workspace Settings -> Usage limits: soft limit 15 USD, hard limit 30 USD (docs/cloud/15 section 7).
   Expected cost for this stack at the measured sizes: about 11 USD of usage a month, inside Pro's 20 USD of included
   usage, so the Pro minimum (20 USD) is the bill.
4. Later: Cloudflare Zero Trust in front of the frontend domain (switch `ACCESS_MODE` to `gateway`), the office
   agent's scheduled task against the real server after the administrator's read-only login exists, a production
   project.

## 6. Not done, on purpose

No SERVER-1 connection, no real records, no scheduled synchronization, no Cloudflare Access yet, no billing change, no
additional account, no TCP proxy or public domain on the backend or the database.
