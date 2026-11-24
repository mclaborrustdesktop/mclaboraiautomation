# Production readiness report - MC Labor website and the McLabor SQL Server

> Read `docs/environments.md` first. It names the four databases (demo data, restored copy, development
> database, possible live database) and the website's three environments (DEMO, STAGING, PRODUCTION).

Date: 2026-11-20. Written for the owner.

## Correction (2026-11-20, found while preparing the backup)

**`DEV-PC\SQLEXPRESS` is a copy, not the live server.** SQL Server's own history shows the McLabor database on this
PC was restored here on 2026-11-13 at 18:46 from a backup taken that day at 17:00 on **`LIVE-HOST\SQLEXPRESS`**.
Nobody else was connected to the copy when it was checked. Where "the SQL Server PC" or "production" appears below
and in documents 01 to 06, it was written believing DEV-PC was the live server.

What this changes:

- The live database that the Access application uses is most likely on `LIVE-HOST`. That has not been checked;
  confirm it in Access (External Data > Linked Table Manager).
- The copy on DEV-PC is a good place to rehearse the certificate script, the read-only login and the live search
  test, because no Access user depends on it. It still holds real SSNs and bank details, so the same care applies.
- The maintenance checklist for Access users (`06`) matters for `LIVE-HOST`, not for DEV-PC.
- `LIVE-HOST` was also on version 15.0.2000 when the backup was taken, so the update advice applies there too.
- Nothing has been inspected or prepared on `LIVE-HOST`.

Details and the backup proposal: `01-backup-and-restore-checklist.md`.

Follow-up the same day: the Access files on this PC link to `<dev-pc-ip>` (this PC's copy) and to a development
database on `<live-host-ip>` (LIVE-HOST). Which database the office staff use is not yet proven; see
`07-database-location-findings.md`. Two plans now replace "the order of work" below:
`08-plan-test-on-restored-copy.md` (first) and `09-plan-connect-live-database.md` (after).

**2026-11-23:** the staging pilot is done (`10`), its findings were worked through (`11` contact columns, `12`
remaining requirements, `13` administrator procedure) and the current state of everything is on one page in
`14-production-readiness-checklist.md`. Read that first; the rest of this document is the position on 2026-11-20.

## In one paragraph

The website works on demo data and is ready to read the real McLabor database in read-only mode. It is **not
connected** to the real database. Three things on the SQL Server PC stand in the way, and each needs your approval
because it changes that PC: a proven backup, a proper certificate on SQL Server, and a restricted read-only login.
A fourth, updating SQL Server, is strongly recommended. Nothing on the SQL Server PC, in the database or in the
Access application has been changed so far.

## What is ready

| Area | State |
|---|---|
| Website on demo data | Running. Sign-in, employees, customers, jobs, weekly tracking, users, AI search all work |
| Tests | 85 automated backend tests and 9 frontend tests pass. 59 end-to-end checks pass on a separate test copy |
| Web sign-in | Own password file, separate from Access passwords. Lockout after 5 wrong attempts. No default administrator in production |
| What the website may read | Exactly 33 tables and 288 columns. Checked offline over 113 queries |
| What it never reads | SSN, bank details, date of birth, citizenship, I-9 flag and notes, sex, race, dependents, Access staff passwords |
| Changes to real data | Switched off. Even when connected, only reading is possible until you approve writes separately |
| Safety checks at start-up | In production the website refuses to start with the demo secret key, with encryption off, with certificate checking off, or if any account still has the demo password |
| Status page | Administrators can see all of this in the website under **System status** |
| Connection checker | `tools\prod-check\check_readonly.py`. Reads no records. Last result: blocked at the certificate |
| Live search test | `python -m app.livecheck`. Prints counts and timings only. Works on demo data; never run on the real server |

## What is not ready, and why

| Blocker | Why it blocks | Document |
|---|---|---|
| No proven backup | No server change should happen without one. Whether any backup exists today is unknown | `01-backup-and-restore-checklist.md` |
| Unknown SQL Server administrator | Someone must be `sysadmin` to create the login and make the backup | `02-administrator-permissions.md` |
| SQL Server never updated | Version 15.0.2000.5 from 2019. Newest Microsoft security update: 2026-11-10. Recommended, not strictly required | `03-sql-server-update-plan.md` |
| No certificate on SQL Server | The website verifies the server's certificate and refuses the temporary one SQL Server shows today | `04-certificate-deployment-plan.md` |
| No restricted login | The website must not use an account that can change data or read SSNs | `05-read-only-login-procedure.md` |

## What has not been proven

- The two scripts (`proposed-certificate-setup.ps1`, `proposed-grants.sql`) have never been run. Their logic was
  reviewed and the certificate script's syntax was checked, but a first run can still surprise.
- The website's searches have never run against SQL Server. They were checked offline for the right columns and for
  wording SQL Server accepts. Speed on the real data is unknown.
- The effect of the update or the certificate on Access PCs other than this one is untested.
- Microsoft's update numbers come from a web search of Microsoft's pages on 2026-11-20, not from reading each page.

## The order of work

1. **Backup**, restore-tested, copy kept off this PC. (`01`)
2. Confirm who the **SQL Server administrator** is. (`02`)
3. **Update SQL Server** - recommended. Several minutes of downtime. (`03`, with `06`)
4. **Install the certificate.** About one minute of downtime. (`04`, with `06`)
5. **Create the read-only login.** No downtime. (`05`)
6. **Run the connection check.** Must end "READ-ONLY CONNECTION VERIFIED". Reads no records.
7. **Live search test, then a read-only pilot**: the website shows real records; compare with Access.

`06-access-maintenance-checklist.md` applies to steps 3 and 4 so nobody loses unsaved work in Access.

## Approvals needed from the owner

| # | Approval | What it allows | Interruption |
|---|---|---|---|
| 1 | Backup and restore test | A full backup, and a temporary test copy `McLabor_RestoreTest` that is deleted again | None |
| 2 | SQL Server update (recommended) | Installing Microsoft's update KB5132745 | 5 to 20 minutes |
| 3 | Certificate | Running `proposed-certificate-setup.ps1` as Windows administrator | About 1 minute |
| 4 | Read-only login | Running `proposed-grants.sql` as SQL Server administrator | None |
| 5 | Reading real records | Switching the website to production, read-only, for the live test and pilot | None |

Still open for a later decision, not part of this connection: whether pay and bill rates may be shown, hosting for
30 or more users, and whether the website may ever change real data.

## After the connection works

- Each staff member needs a web password from an administrator.
- Years in trade, will-travel and job site city/state are read from other tables in the real database. They display
  correctly but cannot be edited from the website until that is built.
- Keep `backend\web_auth_production.db` (the web passwords) in the backups.
