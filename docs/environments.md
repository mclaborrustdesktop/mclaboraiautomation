# Environments and databases

Use these names everywhere. "The SQL Server" on its own is ambiguous and should not be used.

## The databases that exist

| Name used in this project | Where | What it is | Status |
|---|---|---|---|
| **Demo data** | `backend\mclabor_demo.db` on DEV-PC | Invented records for the demo website | In use by the demo |
| **Restored copy** | `DEV-PC\SQLEXPRESS` (`<dev-pc-ip>`), database `McLabor` | A copy of the real database, restored 2026-11-13 18:46 from a backup taken on LIVE-HOST at 17:00 that day | **Verified** as a copy. Contains real SSNs and bank details. Data is frozen at 2026-11-13 |
| **Development database** | `LIVE-HOST\SQLEXPRESS` (`<live-host-ip>`), database `McLabor 20260811 Development` | A database the Access files on DEV-PC also link to | Known only from those links. Never inspected. Not used by this project |
| **Possible live database** | `LIVE-HOST\SQLEXPRESS` (`<live-host-ip>`), database `McLabor` | The database the 2026-11-13 backup came from; created in 2022 | **Not verified** as the one office staff use. Never inspected. Never connected to |

Do not treat DEV-PC as production. Do not treat LIVE-HOST as confirmed live until the check in
`docs/production/07-database-location-findings.md` has been done on a staff PC.

## The website's three environments

One setting, `DATA_SOURCE` in `backend\.env`, selects exactly one. With no `backend\.env` the website is in DEMO.

| | DEMO | STAGING | PRODUCTION |
|---|---|---|---|
| Data | Demo data | Restored copy | Live database (once confirmed) |
| Label shown on every page | blue "DEMO" | amber "STAGING - test copy" | red "PRODUCTION - live data" |
| Its settings | none needed | `STAGING_DB_*` | `PRODUCTION_DB_*` |
| Its web-password file | `web_auth.db` | `web_auth_staging.db` | `web_auth_production.db` |
| Changes to data | Allowed (invented data) | Off | Off |
| Switch that would allow changes | - | `STAGING_WRITES_ENABLED` + `STAGING_WRITE_APPROVAL` | `PRODUCTION_WRITES_ENABLED` + `PRODUCTION_WRITE_APPROVAL` |
| SSN, bank, date of birth, citizenship, I-9, staff passwords | Invented | Never requested | Never requested |
| Status today | **Running** | Prepared, not activated | Not configured |

Prepared staging settings: `backend\.env.staging.example` (not active).

## What stops one environment touching another's data

1. **Separate settings.** Staging reads only `STAGING_DB_*`; production reads only `PRODUCTION_DB_*`. Having the
   other set of values in the file changes nothing, including the other environment's write switch.
2. **Server identity check.** Each environment names the one server it may use (`*_DB_EXPECTED_SERVER_NAME`). On
   every new connection the website asks the server for its own name and database and refuses the connection if
   either differs. A wrong address, a changed DNS entry or a copied settings file cannot send staging traffic to the
   live server, or the reverse.
3. **Start-up refusal.** The website will not start if staging and production name the same server and database, if
   the expected server name is missing, if encryption or certificate checking is off, or with the demo secret key.
4. **Read-only by default, twice.** The API answers "read-only" to every change, and underneath it a statement guard
   lets only SELECT statements reach SQL Server. The planned SQL login can only read as well.
5. **Separate sign-ins.** Each environment has its own web-password file, and a sign-in issued in one environment is
   rejected by the others.
6. **Visible label.** Every page, and the login page, shows which environment is active.

These are covered by 17 automated tests (`backend\tests\test_environments.py`). They run without contacting any
SQL Server; the identity check has not yet been exercised against a real server.

## In the cloud (planned, `docs/cloud/01-cloud-architecture.md`)

The same three environments, with staging and production in separate Azure resource groups, each with its own
database server, container apps, secrets and access lists. The website's settings file names the one server an
environment may use (`*_DB_EXPECTED_SERVER_NAME`) exactly as on this PC, so a staging container can never reach
the production database even with a copied settings file. DEMO stays synthetic: on this PC, and as the `demo`
profile of `deploy/cloud/docker-compose.yml`.

## Checking the restored copy without changing environment

`tools\staging\run-readonly.ps1 <script>` runs one script against the restored copy with the staging settings and
the stored read-only password loaded into that one process. `backend\.env` is not created, so the website keeps
running in DEMO. The scripts in `tools\staging\` print counts and timings only.

## Changing environment

1. Stop the website's backend.
2. Put the chosen environment's file in place as `backend\.env` (or remove it for DEMO).
3. Start the backend. Check the label at the top of the page.
