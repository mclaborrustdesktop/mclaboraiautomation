# 12. Railway + PostgreSQL: the hosting decision and its plan (2026-11-24)

Decision by the owner: the website replaces Microsoft Access completely; hosting is **Railway with PostgreSQL**;
at most 20 website users. This supersedes the single Azure VM plan (`07`, `10`, `11`) as the primary option; that
plan stays on file as the fallback (it keeps SQL Server and Access alive side by side).

## 1. What was built for it (all local, all tested)

| Piece | Where | Proof |
|---|---|---|
| PostgreSQL adapter: `*_DATABASE_URL` per environment, psycopg driver, statement timeout, ILIKE searches, GROUPING SETS facets, row locking on saves | `backend/app/config.py`, `database.py`, `sqlutil.py`, `search.py`, routers | `tests/test_postgres.py` on a real PostgreSQL 16 (the `pgserver` pip package, no installation) |
| Schema generator from the SQL Server export: 288 tables, 3,328 columns, 252 foreign keys, identity keys, search indexes, business-rule constraints | `backend/app/pgschema.py` -> `deploy/railway/postgres/*.sql` | applied in the test; the ORM runs on it in the production shape |
| Synthetic filler for an existing schema (`--fill-existing`), sequences reset | `backend/app/synthdb.py` | test |
| Derived-field writes (years in trade -> lookup id, will-travel -> `tblEmployeeB`, site city from the lookup) | `backend/app/derived.py` | test (create and update on PostgreSQL) |
| Change log and "changed by someone else" protection | `backend/app/audit.py`, `routers/audit.py`, frontend History sections | `tests/test_audit_and_rules.py`, `test_postgres.py` (two simultaneous saves: one succeeds, one told to reload) |
| Railway service configs, root-context backend image, env templates, cron backup + restore test, same-origin API proxy, Cloudflare token via cookie | `deploy/railway/*`, `frontend/src/app/api/[...path]/route.ts`, `security.py` | `tests/test_railway_config.py`, `test_cloud_ready.py` |

The SQL Server adapter is untouched: `DATA_SOURCE=staging/production` without a `*_DATABASE_URL` behaves exactly as
before (read-only, server identity check, 423 on writes). 185 backend tests cover both.

## 2. Networking and security on Railway

* One public hostname (the frontend's custom domain) behind Cloudflare Access; the backend and the database have
  no public address (private network `*.railway.internal`, IPv6/IPv4; the images listen on `::`).
* The backend verifies Cloudflare's signed token on every request (header or `CF_Authorization` cookie), then the
  website's own access roles (administrator / look-up only, maximum 20, Users page). No website login screen.
* TLS from the browser to Cloudflare and from Cloudflare to Railway; inside Railway's private network traffic is
  encrypted by its WireGuard mesh. The app refuses a public PostgreSQL URL without `sslmode=require`, and any URL
  that names an office server.
* Secrets are sealed Railway variables; the database URL is a reference variable; nothing is in the repository.
* Restricted columns (date of birth, citizenship, I-9, SSN, bank) exist in the schema (migration completeness) but
  are not mapped by the website in the production shape and never appear in the change log.

## 3. Backups and restore

Nightly `pg_dump` (custom format) -> AES-256-CBC with PBKDF2 and a sealed passphrase -> SHA-256 checksum -> an
S3-compatible bucket outside Railway (Cloudflare R2, free under 10 GB), 35 days kept. `restore-test.sh` restores
the newest backup into a scratch database on the same server, counts the main tables and drops it; run monthly.
Railway's own volume snapshots (where the plan offers them) are a second copy, not the only one.

## 4. Health checks

`/api/ready` (database + sign-in store) is the backend's Railway health check; `/healthz` the frontend's; a failing
check restarts the service. The administrators' status page shows backend, shape, access summary and warnings.

## 5. Cost for 20 employees (Railway list prices read from railway.com/pricing and the plans page on 2026-11-24)

Unit prices: RAM 10 USD per GB-month, CPU 20 USD per vCPU-month, volumes 0.15 USD per GB-month, egress 0.05 USD
per GB; Hobby plan 5 USD per month with 5 USD of usage included; private networking free; cron needs Hobby or above.
Railway bills measured use, not reserved size.

| Item | Assumption | USD / month |
|---|---|---|
| Hobby plan | 1 workspace, up to 3 members per project | 5.00 |
| backend | 0.25 vCPU, 0.5 GB on average (20 users, 2 workers) | 10.00 |
| frontend | 0.1 vCPU, 0.3 GB | 5.00 |
| Postgres | 0.1 vCPU, 0.5 GB, 2 GB volume | 7.30 |
| backup cron, egress, R2 | minutes a day; < 5 GB egress; < 10 GB bucket | 0.50 |
| included usage | | -5.00 |
| **Production** | | **about 23** |
| Staging running all month (can be stopped when not in use) | | + about 15 |
| Cloudflare DNS + Access (<= 50 users) + R2 | free plans | 0 |

Worst case, every service at 1 vCPU and 2 GB for the whole month: about 90 USD. Against the earlier 200 USD ceiling
and the 98.61 USD Azure B2ms estimate, Railway is the cheapest option, with the trade-off that the database moves to
PostgreSQL (so Access and QuickBooks' QODBC link to SQL Server no longer apply: section 7).

## 6. Cloudflare seats

20 website users on the free Access plan (50). The MS Access PCs' WARP users no longer count once Access is retired.

## 7. Migration from SQL Server, and what it means for Access and QuickBooks (NOT started; needs the owner's approval)

1. Export: a restored copy of the SQL Server backup on DEV-PC (never LIVE-HOST live) -> the copy tool (to be written at
   that stage) -> PostgreSQL staging first, with the schema's foreign keys validated and `constraints.sql` applied.
2. Verification: row counts and checksums per table, the read-only smoke tests, a week of parallel use on staging.
3. Cut-over weekend: freeze Access, final copy, switch production, keep SQL Server read-only for 90 days.
4. **Access**: the Access application cannot link to PostgreSQL the way it links to SQL Server without rework
   (ODBC linked tables to PostgreSQL are possible but every pass-through query and form would need review). The
   decision "replace Access completely" means Access is retired at cut-over, which requires the website to cover
   the daily workflows first: `docs/access-replacement/01-access-workflow-audit.md` lists what is covered and what is not.
5. **QuickBooks**: the Access application reads QuickBooks through QODBC on an office PC. The website replaces
   that with either (a) an import of the QuickBooks open-invoice export (CSV/IIF) into `tblQBOpenInvoices`, which
   the schema has, or (b) the QuickBooks Online API if the company moves to QuickBooks Online. Decision pending.

## 8. Before the first Railway deployment: what is needed from the owner

| # | Decision / access | Why |
|---|---|---|
| 1 | A Railway account (Hobby) and a GitHub repository for the code | the services build from the repository |
| 2 | A Cloudflare account with the company domain, a staging hostname, and an Access application | sign-in without a website login |
| 3 | An R2 bucket (or S3) for backups and a password safe for the passphrase | encrypted off-platform backups |
| 4 | Approval of the staging deployment with synthetic data (no real records) | first real test of the stack |
| 5 | Later: approval of the migration plan (section 7) and the Access retirement date | production |
