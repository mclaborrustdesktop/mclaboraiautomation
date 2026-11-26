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
No synthetic data is ever loaded into it (the synthetic builder refuses production settings).

**Gate 3 - access protection in front of production (owner + Cloudflare).** Cloudflare Access on `search.<domain>`
with the per-employee certificate policy (`docs/cloud/18`, section 2), the Railway-generated domain removed,
`GATEWAY_PLATFORM=cloudflare-access` + team domain + AUD on the backend so every request carries a verified identity.
Tested with two test certificates before any real record exists.

**Gate 4 - the initial import (owner's explicit approval, after gates 1-3 and a restore-tested backup).**
On the office PC that will run the agent, as the Windows account of the future scheduled task:
1. `tools\sync\sync.env` for production (server, expected server name, user `mclabor_web_read`, `OFFICE_HOSTS`,
   `SYNC_API=https://search.<domain>`), secrets via `store-sync-secrets.ps1` (DPAPI).
2. `run-sync.ps1 -DryRun` watched by the owner: counts per table, no warnings, exit 0.
3. `run-sync.ps1 -Bootstrap -Full`: creates the mirror tables on the production PostgreSQL and sends the approved
   columns once (about 1.2 M rows; staging took 30 minutes for 174 k rows over the public address, so expect 2-3 hours
   for the first run; later runs send only changed rows).
4. Checks on the website: counts match the dry run, "Information as of" shows the run time, searches answer, every
   Add/Edit/Delete refused, the unlock log shows the owner's own entry. `tools/containers/smoke_test.py --expect production`.

**Gate 5 - the schedule (owner's approval).** `register-sync-task.ps1 -Times "06:00,12:30"` on the office PC:
Windows Task Scheduler, office-local time, S4U (no stored password), no overlap, retry after 15 minutes, logs under
`%LOCALAPPDATA%\MCLabor\sync\logs`. Exit code 2 (deletions skipped by the guard) is reviewed the same day.

## C. Verification after the import (what the report will show)

Authentication (password screen, lockout, session expiry, certificate identity in the log), database accuracy
(row counts per table against the dry run; spot checks of a few records by the owner on the office PC, never by the
developer), backups (a production snapshot before and after the import; restore drill into a separate service),
synchronization (two consecutive incremental runs with their counts and durations), security (anonymous 401 on
every endpoint, forged tokens refused, writes 423, backend and database without public address, repository scan clean).

## D. Approvals still required from the owner

1. Gate 1: authorize the administrator to run the two scripts on the live server and return the verification output.
2. Gate 2: approve creating the production project (cost above) and the production site password rotation.
3. Gate 3: the Cloudflare hostname and the certificate boundary (who issues the 20 certificates: the owner with the
   provided procedure, or the client's IT).
4. Gate 4: the initial transfer of real records, after the backups are verified.
5. Gate 5: the 06:00 / 12:30 schedule.
