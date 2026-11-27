# 19. Live database: backup status before any change (2026-11-27)

Gate before the read-only login (`18-live-server-readonly-login-procedure.md`) and before anything else on the live
server. Nothing in this document changes, restores or deletes a database.

## A. Which server and database

| Fact | Evidence | Status |
|---|---|---|
| Live instance `LIVE-HOST\SQLEXPRESS`, `<live-host-ip>`, fixed TCP port 1433 | every 2022-2026 Access release links there (`15`, section A); the name resolves to that address from the office PC and the port answers (checked again 2026-11-27, nothing sent, no sign-in) | identified; the administrator confirms with `SELECT SERVERPROPERTY('ServerName')` |
| Database `McLabor` | the copy's backup header: database `McLabor` from `LIVE-HOST\SQLEXPRESS`, SQL Server 15.0.2000, recovery model SIMPLE | identified |
| This project has **never connected** to the live server | no live login exists for it; the read-only login is not created yet | by design |

## B. What is known about its backups, and from where

Everything below was read on the office PC from the restored copy's own history (`msdb` on `DEV-PC\SQLEXPRESS`,
Windows authentication, read-only). **It describes one backup taken two weeks ago, not the live server's current
backup state.** The copy on DEV-PC is not a backup of production: it is a snapshot restored once, on 2026-11-13.

| Item | Value |
|---|---|
| Only live backup known to this project | full backup of `McLabor` on `LIVE-HOST\SQLEXPRESS`, **2026-11-13 17:00:00 to 17:00:09**, 1,706.5 MB, recovery model SIMPLE, taken by the SQL login `mclabor` |
| Type / options | FULL, **not copy-only, no checksums** (`has_backup_checksums = 0`), not marked damaged |
| File | `C:\ZZZ-SQL\McLabor_2026_11_13_170000.80.bak` on DEV-PC (1,706.6 MB, still present); the name pattern (`_yyyy_MM_dd_HHmmss.80`) is that of a scheduled backup tool, which suggests a routine exists on the live server, unverified |
| Verification | the file was restored successfully on DEV-PC on 2026-11-13 18:46 (`McLabor`), and the copy passed `DBCC CHECKDB` on 2026-11-20; that proves the 11-13 file, nothing later |
| Differential / log backups | none applicable: recovery model SIMPLE (no log backups); no differential recorded in the copy's history |
| Tested restore procedure | exists and was exercised on the copy on 2026-11-20 (backup with checksum, `RESTORE VERIFYONLY`, restore as `McLabor_RestoreTest`, `DBCC CHECKDB`, row counts, cleanup: `01-backup-and-restore-checklist.md`) |

**Is the 11-13 backup recent enough to protect the company's current records? No.** Two weeks of office work are
not in it, and whether the live server has taken newer backups cannot be seen from here.

## C. What the administrator runs (read-only, 2 minutes)

`tools/prod-check/backup/0-live-backup-status.sql` on the live server (edit `LIVE-HOST` first). It reads only the
server's backup history and database properties and prints eight grids: server and Agent presence, the database's
state and last backup dates, the newest full / differential / log backup with age, checksum flag, file path and
whether the file still exists, the last 15 backups, every restore ever done there, scheduled jobs, all databases,
and a plain-language verdict. Send the saved grids to the owner.

Decision from the grids:

| Grids show | Then |
|---|---|
| a FULL backup of `McLabor` **younger than 24 hours**, file present, `has_backup_checksums = 1`, and a restore test recorded (grid 5) or `RESTORE VERIFYONLY ... WITH CHECKSUM` run on it now | **safe to proceed** to procedure 18 |
| a recent full backup **without checksums** | the administrator runs `RESTORE VERIFYONLY FROM DISK = N'<file>'` (reads the file, restores nothing); if valid, proceed; otherwise script 4 |
| no full backup younger than 24 hours, or the file is missing, or damaged | **script 4** (below) with the administrator's approval, then proceed |

## D. Recommended if no recent verified backup: COPY_ONLY full backup with checksum (needs approval)

`tools/prod-check/backup/4-live-copyonly-backup-with-checksum.sql` (edit `LIVE-HOST` first). COPY_ONLY leaves the
server's own backup routine untouched (no differential base or chain is changed); CHECKSUM re-checks every page; the
script verifies the file with `RESTORE VERIFYONLY ... WITH CHECKSUM` and prints its header. Only reads the database;
office users keep working. About 1.7 GB, a few minutes, into SQL Server's own backup folder (administrators only);
a copy belongs outside the server (encrypted drive or administrators-only share), the client's choice.

Not run by this project; the client's administrator approves and executes it. **No RESTORE, REPLACE, DROP or any
change to the existing production database is proposed anywhere.** A restore test, if wanted on the live server,
is done into a separate database named `McLabor_RestoreTest` with the pattern of script 2 (no REPLACE), and needs
about 2.3 GB of free space there.

## E. Verdict for the owner

- Current verified backup of the LIVE database: **unknown to this project**. The only backup it has seen is from
  2026-11-13 and is not recent enough.
- Safe to proceed to the read-only login: **not yet.** Proceed only after the administrator's grids show a full backup
  younger than 24 hours that is verified (checksums plus `RESTORE VERIFYONLY`, or a restore test), or after script 4
  has run successfully. The read-only login is not created before that.
