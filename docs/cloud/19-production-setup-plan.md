# 19. Production set-up plan: real records, twice-daily synchronization, approvals (prepared 2026-11-26)

Everything here is prepared, nothing is created: no production project, no live-server account, no transfer of real
records, no scheduled task. Each numbered gate needs the owner's explicit approval; the live-server steps need the
client's administrator.

## A. Where things stand

| Area | State |
|---|---|
| Website code | search-only mirror, password-only entrance (passcode mode), Cloudflare Access verification, one-way ingest API; staging live on Railway Pro with synthetic data |
| Read-only SQL account | designed, hardened (DENY layer), verified on the restored copy with the administrator's report and a 1.2 M-row dry run; **not yet created on the live server** |
| Live SQL Server | never connected to by this project; its name was established from the Access links (`docs/production/15`) and is to be confirmed by the administrator |
| Railway | workspace "mclaborrustdesktop's Projects" (ray@mclabor.com), Pro; project `mclabor-staging` only |
| Backups | staging: daily + weekly volume snapshots; production: to be enabled the same way plus point-in-time recovery |

## B. Gates and the order of work

**Gate 0 - backup status of the live database (administrator, read-only, 2 minutes).** `docs/production/19`:
`0-live-backup-status.sql` on the live server; proceed only with a full backup younger than 24 hours, present and
verified, or after the COPY_ONLY full backup with checksum (script 4, approved by the administrator). The restored
copy on the office PC is a 2026-11-13 snapshot, not a backup of production.

**Gate 1 - the live server's read-only account (administrator).** `docs/production/18-live-server-readonly-login-procedure.md`:
confirm the server name, run `proposed-grants-production.sql`, run `verify-readonly-login.sql`, send the grids;
from the office PC `check_readonly.py` must say READY. Proves: only the 288 approved columns of the 33 tables are
readable, the 17 sensitive columns are not, no write or execute right exists, and the Access application is
untouched (the account is new; nothing existing changes).

**Gate 2 - the production project on Railway (owner approves the cost, about 11 USD of usage a month inside the Pro
allowance).** Project `mclabor-production` in the same workspace, created like staging (empty services first, then
settings, variables, then the source): PostgreSQL (private, 1 GB volume), `backend` from
`deploy/railway/env/backend.production.env.example` with `ACCESS_MODE=passcode`, a **new** `SITE_PASSWORD_HASH` and
`SITE_PASSWORD_LABEL=production-<date>`, new `JWT_SECRET` and `SYNC_API_KEY`, `SITE_MODE=search-only`,
`WEB_ADMINS` = the real administrators' initials; `frontend` with its own domain. Volume backups daily + weekly and
point-in-time recovery on. Nothing from staging is reused: different database, different secrets, different password.
No synthetic data is ever loaded into it: the synthetic builder refuses production settings, and the ingest API refuses
any run whose announced source differs from `SYNC_EXPECTED_SOURCE` (the live server name / `McLabor`) or from the
source of the mirror's earlier successful runs (HTTP 409, `backend/app/syncmirror.py`).

**Gate 3 - access protection in front of production (owner; Cloudflare POSTPONED; devices OFF by the owner's decision
of 2026-11-27).** The boundary is the single access password (`docs/cloud/18`): a NEW production password (20 random
characters, generated locally on 2026-11-26, DPAPI-stored), `SITE_PASSWORD_LABEL=production-...` (the staging password
`initial` is refused by production), `SITE_DEVICE_APPROVAL=false`. Before any real record exists: the correct password
opens the dashboard and a wrong one answers 401 with a generic message, the lockout engages and releases, the unlock
log shows the attempts, anonymous and forged requests are refused, writes answer 423, backend and database have no
public address, a volume snapshot exists and has been restored into a scratch service. The owner confirms in writing
the accepted risks listed in `docs/cloud/18` section 2 (shared secret, no individual identity).

**Gate 4 - the initial import (owner's explicit approval, after gates 1-3 and a restore-tested backup).**
On the office PC that will run the agent, as the Windows account of the future scheduled task:
1. `tools\sync\sync.env` for production (server, expected server name, user `mclabor_web_read`, `OFFICE_HOSTS`,
   `SYNC_API=https://search.<domain>`), secrets via `store-sync-secrets.ps1` (DPAPI).
2. `run-sync.ps1 -DryRun` watched by the owner: counts per table, no warnings, exit 0.
3. `run-sync.ps1 -Bootstrap -Full`: creates the mirror tables on the production PostgreSQL and sends the approved
   columns once (about 1.2 M rows; staging took 30 minutes for 174 k rows over the public address, so expect 2-3 hours
   for the first run; later runs send only changed rows).
4. Reconciliation: the agent was run with `--report-file <path>` (per-table source counts); then
   `python -m app.syncagent reconcile --api https://<host> --report-file <path> --expect-source "<live server>\SQLEXPRESS/McLabor"`
   must print ALL MATCH (every table's source count equals the website's count, no extra table on the website, the
   website's last run came from the live server and succeeded). Then on the website: "Information as of" shows the run
   time, searches answer, every Add/Edit/Delete refused, the unlock log shows the owner's own entry;
   `tools/containers/smoke_test.py --expect production`.

**Gate 5 - the schedule (owner's approval).** `register-sync-task.ps1 -Times "06:00,12:30"` on the office PC:
Windows Task Scheduler, office-local time, S4U (no stored password), no overlap, retry after 15 minutes, logs under
`%LOCALAPPDATA%\MCLabor\sync\logs`. Exit code 2 (deletions skipped by the guard) is reviewed the same day.

## C. Verification after the import (what the report will show)

Authentication (password screen, lockout, session expiry, certificate identity in the log), database accuracy
(row counts per table against the dry run; spot checks of a few records by the owner on the office PC, never by the
developer), backups (a production snapshot before and after the import; restore drill into a separate service),
synchronization (two consecutive incremental runs with their counts and durations), security (anonymous 401 on
every endpoint, forged tokens refused, writes 423, backend and database without public address, repository scan clean).

## C2. Prepared on 2026-11-26 (local, private, nothing created in the cloud)

- The production secret for the password screen was generated locally (20 random characters) and is stored DPAPI-encrypted for the owner's Windows
  account in `%LOCALAPPDATA%\MCLabor\production\site-password-production.dpapi`; its hash, the label `production-2026-11`,
  a new JWT secret and a new sync key in `railway-production-secrets.json` in the same folder. The initial staging
  password is refused by production by design (label rule in the backend).
- Administrator package for the live server: `%LOCALAPPDATA%\MCLabor\production\live-server-readonly-login-package.zip`
  (grant script with its 5 placeholder lines, verification script, settings template, procedure 18 and report 17).
- Site-wide lockout redesigned so that an attacker cannot lock the company out (docs/cloud/18, section 1).

## C3. Actual additional monthly cost (list prices read 2026-11-26)

| Item | USD / month |
|---|---|
| Railway Pro minimum (already subscribed), includes 20 USD of usage | 20.00 |
| Staging usage at the measured sizes (can be stopped between test days) | about 11 |
| Production usage: backend + frontend + PostgreSQL with a 1 GB volume, daily/weekly snapshots, point-in-time recovery storage | about 12 |
| **Railway total** (usage 23 against 20 included) | **about 23**, i.e. about 3 above the Pro minimum; about 20 if staging is stopped |
| Cloudflare Free: DNS, proxy, WAF rate-limiting rule, office IP rule | 0 |
| Cloudflare Access with mTLS or an identity provider (option B only, 20 users) | about 140 (not recommended) |
| Domain name, if the company has none in Cloudflare | about 0.85 (10 per year) |

**Final security architecture (recommended)**: Cloudflare Free proxy on `search.<domain>` with a rate-limit rule on
`/api/auth/unlock` and (optional) the office IP rule -> Railway frontend (the only public service; the Railway-generated
domain deleted) -> private network -> backend and PostgreSQL (no public address). Entrance: the single site password
(hashed, rotated per environment) + the approved-device boundary (option A) = something you know + something you have,
per employee, audited per device. Data: SQL Server stays the source of truth; the read-only login (288 columns, DENY
layer) feeds the mirror one way, twice a day; the website refuses every write (423). Backups: daily and weekly
snapshots plus point-in-time recovery on the production database; sync runs logged on both sides.

## E. Final production configuration (prepared 2026-11-27; files built and verified locally, nothing created)

| Item | Value |
|---|---|
| Railway project | `mclabor-production`, workspace "mclaborrustdesktop's Projects" (ray@mclabor.com, Pro); created by `deploy/railway/create-production.ps1 -Execute` after approval (plan mode prints every step) |
| Services | `Postgres` (template, private network only, 1 GB volume), `backend` (root `/`, `deploy/railway/backend.railway.json`, no public address), `frontend` (root `frontend`, the only public address) |
| Entrance | `ACCESS_MODE=passcode`, new production password (20 random characters, DPAPI-stored locally; hash in a sealed variable), label `production-2026-11`, `SITE_DEVICE_APPROVAL=false`, sessions 480 min, lockout 5/15 min, site-wide 50 |
| Identity | `SITE_DEFAULT_USER` = the staff record everyone acts as (initials **to be confirmed by the client**); `WEB_ADMINS` = that record or empty (client's choice, see `docs/cloud/20`) |
| Data | `SITE_MODE=search-only`, `DB_SHAPE=production`, `SYNC_EXPECTED_SOURCE=<live server>\SQLEXPRESS/McLabor` (any other source refused with 409), `OFFICE_HOSTS` set (office servers refused as targets), no outside AI key |
| Secrets | `JWT_SECRET`, `SYNC_API_KEY`, `SITE_PASSWORD_HASH`: new, all different from staging (verified), sealed in the dashboard after import |
| Backups | daily + weekly volume snapshots, point-in-time recovery on, one on-demand snapshot before the import, restore drill into a scratch service |
| Browser hardening | HSTS, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, Content-Security-Policy on every response (`frontend/next.config.ts`) |
| Office agent | `sync.env` built for the live server (read-only login `mclabor_web_read`, TLS with certificate check, writes disabled, `SYNC_API` = the production address once it exists); secrets via `store-sync-secrets.ps1 -Environment production`; schedule `register-sync-task.ps1 -Times "06:00,12:30"` (office-local, S4U) |
| Verification tooling | `tools/railway/Build-ProductionVariables.ps1` (builds the three files, owner-only permissions) + `verify_production_variables.py` (28 checks, 27 pass; the one open item is the initials decision) |
| Synthetic data cannot enter production | new empty database; the synthetic builder refuses office hosts and non-empty databases; the ingest API refuses any source other than the live server; reconciliation compares every table with the live counts |

Files on this PC (never committed): `%LOCALAPPDATA%\MCLabor\production\backend.production.variables.env`,
`frontend.production.variables.env`, `sync.env`, `site-password-production.dpapi`, `railway-production-secrets.json`,
`live-server-readonly-login-package.zip`.

## F. Network-level protections that keep the password-only experience (assessment 2026-11-27)

| Option | Effect | Cost | Status |
|---|---|---|---|
| Railway private network for backend and database | neither has a public address; only the frontend is reachable | 0 | in place (staging), planned (production) |
| Application lockout (per address, doubling; site-wide pressure with known-address exemption) | stops password guessing without locking the company out | 0 | in place |
| Browser hardening headers (HSTS, CSP, frame denial) | blocks framing/clickjacking, script injection, downgrade | 0 | added 2026-11-27 |
| Cloudflare Free proxy on a custom host: WAF managed rules, rate-limit rule on `/api/auth/unlock`, bot fight mode, optional office-address rule, Railway domain removed | hides the Railway address, adds edge rate limiting and bot filtering; the password screen stays the only step for people | 0 (needs the domain's DNS at Cloudflare) | **postponed** by the client |
| Office-address allow-list on the password screen (app setting) | only office addresses could reach the password screen | 0 | rejected: the client wants access from any computer or phone |
| Cloudflare Access (identity or certificates) | per-person identity | about 7 USD per user per month | postponed; contradicts the password-only wish |
| VPN / IP allow-list at Railway | Railway has no edge allow-list or WAF of its own | - | not available |

Recommendation when Cloudflare is discussed: the Free proxy with the rate-limit rule is the one addition that changes
the picture (risk 3 of `docs/cloud/20`) at no cost and without touching the sign-in experience.

## D. Approvals still required from the owner

0. (Dropped 2026-11-27: the device layer is off, so no SSH key and no device approval are needed for website access.
   The prepared Ed25519 key on the office PC stays unregistered.)
0. Gate 0: the administrator runs the read-only backup-status script on the live server and returns the grids; if no
   recent verified full backup exists, approves and runs the COPY_ONLY backup script.
1. Gate 1: authorize the administrator to run the two scripts on the live server and return the verification output.
2. Gate 2: approve creating the production project (cost above) and the production site password rotation.
3. Gate 3: sign the risk acknowledgment `docs/cloud/20` (arrangement, six risks, the two choices: initials of the
   shared staff record, administrator pages yes/no); Cloudflare postponed.
4. Gate 4: the initial transfer of real records, after the backups are verified.
5. Gate 5: the 06:00 / 12:30 schedule.
