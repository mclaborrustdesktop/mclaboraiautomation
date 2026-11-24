# 13. One-way synchronization: office SQL Server -> Railway PostgreSQL -> search-only website (2026-11-24)

Final requirements for the first release: the office SQL Server and the Access application stay the **primary**
system; the cloud website is **search-only** (maximum 20 users, Cloudflare Access sign-in, administrator and look-up
roles); an agent on an office PC copies the approved tables to the cloud **one way, at least twice a day**; the
website keeps working from the last successful copy when the office is offline; nothing ever flows back.

```
office PC (scheduled task 06:00 + 12:30)                         Railway (private network)
┌────────────────────────────────────────┐    HTTPS + sync key    ┌──────────────┐    ┌──────────────┐
│ syncagent: SELECT approved columns     │ ─────────────────────> │ backend      │ ─> │ Postgres     │
│  with the read-only login, hash rows,  │  Cloudflare service    │ /api/sync/*  │    │ 33 mirror    │
│  send only what changed, delete what   │  token in front        │ (ingest)     │    │ tables       │
│  disappeared; state file on this PC    │                        └──────────────┘    └──────────────┘
└────────────────────────────────────────┘                               ▲ reads only
        SQL Server (LIVE-HOST, or the DEV-PC copy for rehearsal)   browser → Cloudflare Access → frontend → backend
```

## 1. What already existed and is reused

| Piece | Reused for |
|---|---|
| `tools/prod-check/required_schema.json`: the 33 approved tables, their approved columns, the sensitive columns | the only thing the agent may copy; the mirror's table definitions |
| Restricted read-only login `mclabor_web_read` (column-level grants, `proposed-grants*.sql`), DPAPI password store, SELECT-only statement guard and server identity check (`production.py`) | the agent's source connection |
| PostgreSQL adapter, psycopg, production-shape ORM, search on PostgreSQL (`12-railway-plan.md`) | the website on the mirror |
| Cloudflare Access verification, roles, 20-user limit | unchanged; a service token covers the agent |

## 2. What was built

| Piece | File | Notes |
|---|---|---|
| Approved spec, mirror metadata | `backend/app/syncspec.py` | 33 tables, approved columns only; sensitive names refused by list and by pattern (SSN, bank, routing, birth, password, citizen, I-9, race, sex, W-4...); no foreign keys on the mirror (it must accept whatever the office holds); search indexes |
| Office agent | `backend/app/syncagent.py` | read-only source, hash reconciliation, batches of 1,000 rows, retries with back-off, resumable state file, run lock, dry run, full run, `status` |
| Cloud side | `backend/app/syncmirror.py`, `routers/sync.py` | bootstrap, upsert by key (`INSERT ... ON CONFLICT`), delete, run log in the website's own store, `GET /api/sync/status` for the banner, `GET /api/sync/runs` for administrators; ingest refuses unapproved tables/columns with 422 |
| Search-only mode | `config.py` (`SITE_MODE`), `main.py` middleware (423 for every write, administrators included), `security.py` (`*.edit` features off), frontend (`hasFeature`, hidden controls, banner, footer) | default on for a PostgreSQL mirror in staging/production; the Add/Edit code stays in the repository and works in the demo (`SITE_MODE=full`) |
| "Last updated" | `SyncBanner.tsx`: grey line when fresh, amber after `SYNC_STALE_HOURS` (14), red after twice that or when nothing was ever loaded, note when the latest attempt failed | every page |
| Office scripts | `tools/sync/*`: `sync.env.example`, `store-sync-secrets.ps1` (DPAPI), `run-sync.ps1`, `register-sync-task.ps1` (Task Scheduler, times configurable, no overlap, retry after 15 min, runs when not logged on) | |
| Tests | `tests/test_sync.py` (files), `tests/test_sync_postgres.py` (agent -> API -> PostgreSQL 16 -> website) | see section 6 |

## 3. Reconciliation without modification timestamps (task 6)

The office tables have creation stamps (`*EntryTimestamp`) and per-column audit stamps, but no reliable
"row last modified" value, and deletions leave no trace. The agent therefore never assumes one:

1. Every run reads **every row** of every approved table (approved columns only, keyset-paged by the key, 5,000 rows a page).
2. It hashes each row (SHA-1 of the canonical values) and compares it with the hash it remembered in its state file
   on the office PC (`%LOCALAPPDATA%\MCLabor\sync\state-<env>.db`, one line per row).
3. **New or changed** rows are sent (only those); **rows no longer in the source** are deleted on the mirror
   (children first); unchanged rows cost nothing but the read.
4. Keys that appear twice in the source (the 1:1 extension table has had that) are sent once.
5. A batch is remembered in the state file only after the cloud acknowledged it, so an interruption (network, crash,
   task time limit) leaves the state consistent: the next run resends exactly what was not acknowledged. The cloud
   marks a run that never finished as "abandoned" when the next one starts.
6. `--full` forgets the state and resends everything; the upserts are idempotent (same key = same row).

Cost of a run: the real tables (179k employees, 107k customers, 16k jobs, 192k tracking rows, about 50 columns
each) are one read of about 500k rows over the office LAN, a few minutes; the first run sends everything
(roughly 150 MB of JSON in 500 batches), later runs send only the day's changes.

### 3a. Deletion guard (an incomplete scan can never wipe the mirror)

Deletions are the only destructive step, so they are guarded on both sides:

* **Agent side.** A run that reads with `--limit` or `--tables` (a partial read by definition) deletes nothing. A table
  whose source came back **empty**, or that **shrank by more than 10 % and more than 100 rows** against what the
  agent remembered, has its deletions **skipped**: the upserts go through, the run finishes as success with a
  warning (exit code 2, the warning in the log and on the status page), and every later run keeps refusing until a
  person checks the office database and reruns with `--allow-mass-delete`. A read error aborts the run before any
  deletion is computed.
* **Cloud side.** Independently of what the agent sends, one run may delete at most **10 % of the mirror's rows
  (minimum 500)** unless the run was opened with `allow_mass_delete`, which the agent sets only from that flag and
  the cloud logs as a warning. A batch beyond the budget is refused with 409, the agent stops the run (a 4xx is never
  retried), and the mirror is left exactly as it was.

Tests: `tests/test_sync_guard.py` (limited run, table subset, half the tracking table vanishing, an emptied table, the
cloud budget against a misbehaving agent, the explicit override).

## 4. Security

* The agent uses the restricted login (column-level SELECT only); the application layer refuses any non-SELECT and
  any server other than the expected one; writes are forced off in the task's environment.
* Only approved columns are selected; the cloud refuses anything else; the mirror tables do not have the sensitive
  columns at all; the column-name pattern check is a third barrier.
* Transport: HTTPS to the custom domain; Cloudflare Access service token (checked by Cloudflare, then by the backend:
  signature, audience, issuer, expiry) plus the sync key (sealed in Railway, DPAPI on the office PC). The ingest
  endpoints do not exist unless the key is configured and the backend's database is the PostgreSQL mirror.
* Search-only is enforced in the middleware (every POST/PUT/PATCH/DELETE on records is 423), in the permission
  check (`*.edit` is false for everyone) and in the pages (controls hidden). User management (website roles) and
  password changes still work: they live in the website's own store, not in the mirrored data.
* The website never connects to the office; the office never exposes a port. No real records are used until the
  owner approves the first run against the live server.

## 5. Schedule and operation

`register-sync-task.ps1 -Times "06:00,12:30"` (any list of times). Logs in `%LOCALAPPDATA%\MCLabor\sync\logs`;
the website's status page shows the cloud's view of each run and the mirror's row counts; the banner tells every
user how old the information is. If the office PC is off, the website keeps serving the last successful copy and
the banner turns amber after 14 hours and red after 28.

## 6. Tests (all local, synthetic data only)

| Test | What it proves |
|---|---|
| `test_sync.py` | the spec excludes every sensitive column; the mirror cannot hold them; initial copy of the 33 tables; a second run sends nothing; update + insert + two deletions + a duplicate key arrive correctly; dry run sends nothing; an interrupted run leaves the state consistent and the next run completes; the run lock; a full resend is idempotent; the banner's levels |
| `test_sync_postgres.py` | the agent pushes a synthetic production-shape source through the website's API into PostgreSQL 16; wrong key 401; SSN column 422; unapproved table 422; a finished run cannot be reused; the website (STAGING, search-only) logs in, lists, searches (keyword and AI), opens records, shows the board and dashboard; every write is 423 for an administrator; `.edit` features hidden; user management still works; status is fresh; an office deletion and a rename arrive on the next run |

Not tested here: a run against a real SQL Server. The source side uses the same connection code as the pilot's
read-only tools (verified on the DEV-PC copy earlier), but the first agent run against the copy is step 2 of
section 8.

## 7. Railway configuration and costs

Same services as `12-railway-plan.md` plus `SITE_MODE=search-only`, `SYNC_API_KEY` (sealed), `SYNC_STALE_HOURS`,
and a Cloudflare Access **service token** policy on `/api/sync/*`. The ingest adds a few minutes of CPU twice a
day and about 150 MB of ingress on the first run (ingress is free). Estimate for 20 users: **about 23 USD per month**
for production (Hobby plan 5 + backend 10 + frontend 5 + Postgres 7.30 + backup/egress 0.50, minus the 5 USD included),
about 38 USD with staging running; worst case about 90. Backups: nightly encrypted `pg_dump` to R2 (free under 10 GB)
as before; since the office remains the system of record, a lost mirror is rebuilt by `run-sync.ps1 -Full` in minutes.
Monitoring: Railway health checks and restart policy, the status page, the banner, the task's log, plus a
Cloudflare notification or an e-mail from the task on failure (optional).

## 8. What remains before the first Railway STAGING deployment

| # | Item | Who |
|---|---|---|
| 1 | Railway Hobby account and a GitHub repository with the code; Cloudflare account with a staging hostname, an Access application and a service token; an R2 bucket | owner / IT |
| 2 | First agent rehearsal on this PC: `run-sync.ps1 -EnvFile <staging env> -DryRun -Limit 500` against the DEV-PC copy with the existing read-only login, target a local PostgreSQL (never the cloud) | developer, after the owner says the copy may be used for this |
| 3 | Deploy staging per `deploy/railway/README.md` with **synthetic** data: `run-sync.ps1` from a synthetic source (`app.synthdb`), roster of test users, smoke tests, 20-user load test | developer |
| 4 | Owner's approval to point the agent at the live server (read-only login on LIVE-HOST by the administrator; `proposed-grants-production.sql`), then the first real copy to **production** | owner, administrator |
