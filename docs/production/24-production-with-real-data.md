# 24. Production with real MC Labor data: the snapshot phase and the switch to live updates (2026-11-28)

Owner's instruction: the final application uses **real MC Labor records only** (the 33 approved tables, 288 approved
columns); the 1,209,951 real records synchronized on 2026-11-27 from the November 13 snapshot are the data to deploy;
all real records stay on the office PC until the cloud transfer is explicitly authorized; no empty or synthetic
production database; the live server is neither accessed nor modified.

## 1. What the production website will contain, and how it is labelled

| Phase | Source the agent reads | What the website says | Refresh |
|---|---|---|---|
| **Snapshot phase** (first) | the office PC's restored copy of McLabor, **data as of 2026-11-13 17:00**, through the read-only login | "Information from the office McLabor database (snapshot of November 13, 2026; not yet refreshed from the live server) is N hours old. It may be outdated." | none: the copy cannot refresh itself |
| **Live phase** (after the client's one-time setup, `21`) | the live server, same database continued, read-only login, verified certificate | "Information from the office McLabor system is N hours old" (only when a run is late) | 06:00 and 12:30 every day |

The website is never described as live-updated during the snapshot phase: its own status message carries the
snapshot wording above (`SYNC_SOURCE_LABEL`), and the 14-hour staleness warning stays on, so every page that shows
the data's age says it is outdated.

## 2. How the two phases are kept apart, and how the switch works

- **One source at a time.** The website only accepts runs whose announced source equals `SYNC_EXPECTED_SOURCE`
  (snapshot phase: `DEV-PC\SQLEXPRESS/McLabor`; live phase: `LIVE-HOST\SQLEXPRESS/McLabor`), and refuses any run from
  a source other than the one its earlier successful runs came from. Synthetic data (`sqlite (given)`) can never land.
- **The switch is one deliberate change** (2026-11-28, `syncmirror.start_run`, tested): a different source is accepted
  only when the owner has re-pointed `SYNC_EXPECTED_SOURCE` to it. Any other change is still refused.
- **The agent keeps its state file across the switch** (`SYNC_STATE_DIR=...\MCLabor\sync\production`): on the first live
  run, rows changed since November 13 are updated and rows removed since then are deleted on the website. The two
  phases hold the same database at two dates, never two systems.
- **Same restrictions in both phases:** read-only login (SQL Server refuses writes and the 17 sensitive columns), the
  agent's approved-column list (288 columns; the local mirror was checked: 288 of 288 present, 0 extra, 0 sensitive),
  encrypted connection with the server certificate verified, website search-only, password-only sign-in with lockout.

## 3. Files prepared for the snapshot phase (nothing executed)

| File | Content |
|---|---|
| `%LOCALAPPDATA%\MCLabor\production\backend.production.variables.env` | production website variables; `SYNC_EXPECTED_SOURCE=DEV-PC\SQLEXPRESS/McLabor`, snapshot `SYNC_SOURCE_LABEL`, `SITE_DEFAULT_USER=RMV`; `verify_production_variables.py`: **ALL PASSED** |
| `%LOCALAPPDATA%\MCLabor\production\sync.snapshot.env` (example: `tools/sync/sync.snapshot.env.example`) | the agent reads the restored copy (`DATA_SOURCE=staging`, read-only login, TLS verified) and sends to the production website with the **production** sync key (`SYNC_SECRETS_FILE=sync-production.dpapi`, new option of `run-sync.ps1`); separate state directory |
| `%LOCALAPPDATA%\MCLabor\production\sync.env` | the live-phase settings (`DATA_SOURCE=production`, live server by name, port 1433, read-only login), used after `21` |
| `deploy/railway/create-production.ps1` | creates the project, PostgreSQL, two services, variables, domain, backups (`-Execute` only after approval) |

Dry run of the snapshot-phase settings on 2026-11-28 (reads everything, sends nothing): see the end of this file.

## 4. Remaining deployment actions, in order (each needs the owner's explicit go-ahead where marked)

1. **Approval: cloud resources.** `create-production.ps1 -Execute` (about 12 USD a month). Creates an **empty** PostgreSQL
   mirror for a few minutes only; the website refuses to serve until step 3 has loaded it and shows "has not been
   loaded yet" meanwhile. Checks printed by the script are then run (no public address on the backend or the database,
   health says production / passcode / writes off / search-only).
2. **Production password.** Generated and stored on 2026-11-26 (`site-password-production.dpapi`, label production-2026-11);
   handed to the office in person, never in chat or e-mail. The staging password is refused by the production website.
3. **Approval: first transfer of real records.** `run-sync.ps1 -EnvFile ...\sync.snapshot.env` (no `-DryRun`): the
   1,209,951 rows of the 33 tables over HTTPS to the production website only. Then `app.syncagent reconcile --api
   <production> --report-file <report> --expect-source "DEV-PC\SQLEXPRESS/McLabor"`: 33 tables must match.
4. **Risk acknowledgment** (`docs/cloud/20`): signature and the `WEB_ADMINS` yes/no choice; `SITE_DEFAULT_USER` is set to
   the owner's record and can be changed there.
5. **Live updates** (the blocker for current data): the client's one-time setup on the live server (`21`, 15 minutes of
   their administrator, no credentials shared). When the results folder comes back: `Import-ClientSetupResults.ps1`,
   then on the website `SYNC_EXPECTED_SOURCE=LIVE-HOST\SQLEXPRESS/McLabor` and `SYNC_SOURCE_LABEL=the office McLabor
   system`, then `run-sync.ps1` with `sync.env` (same state directory), reconcile, and **approval: the 06:00 / 12:30
   schedule** (`register-sync-task.ps1`). Only from this point is the website refreshed from live records.

## 5. Genuine blockers

| Blocker | Exact reason |
|---|---|
| Cloud transfer | not authorized yet (steps 1 and 3 above). Nothing is created; all real records stay on this PC. |
| Current (live) records | this PC has no authorized way to read the live server or any regular export from it (`23` section C); step 5 is the client's 15-minute action. Until then the data is the November 13 snapshot and is labelled as such. |
| Signatures | the risk acknowledgment and the schedule approval. |

Not blockers: code, configuration, tests, security checks, performance (`23`); all completed and kept.

## 6. Dry run of the snapshot-phase settings (2026-11-28 00:34, nothing sent)

`run-sync.ps1 -EnvFile ...\sync.snapshot.env -DryRun`: source `DEV-PC\SQLEXPRESS/McLabor` through the read-only login,
33 tables, 1,209,951 rows read in 1,235 batches in 36 s, 0 warnings, 0 rows sent. The same settings without `-DryRun`
perform step 3 of section 4 once the transfer is authorized.
