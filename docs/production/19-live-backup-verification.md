# 19. Live database: backup status before any change (2026-11-27)

Gate before the read-only login (`18-live-server-readonly-login-procedure.md`) and before anything else on the live
server. Nothing in this document changes, restores or deletes a database.

## A. Which server and database

| Fact | Evidence | Status |
|---|---|---|
| Live instance `LIVE-HOST\SQLEXPRESS`, `<live-host-ip>`, fixed TCP port 1433 | every 2022-2026 Access release links there (`15`, section A); the name resolves to that address from the office PC and the port answers (checked again 2026-11-27, nothing sent, no sign-in) | identified; the administrator confirms with `SELECT SERVERPROPERTY('ServerName')` |
| Database `McLabor` | the copy's backup header: database `McLabor` from `LIVE-HOST\SQLEXPRESS`, SQL Server 15.0.2000, recovery model SIMPLE | identified |
| This project has **never signed in** to the live server | no live login exists for it; the read-only login is not created yet | by design |
| 2026-11-27 read-only probe (authorized by the owner): one connection attempt with the office PC's Windows identity, nothing typed, nothing written | `LIVE-HOST\SQLEXPRESS` by instance name: not found (the SQL Browser service is silent, so the fixed port must be given); `tcp:LIVE-HOST,1433`: a SQL Server answered and refused the sign-in as `LIVE-HOST\Guest` (error 18456). The office PC is not in a domain with the server, so **no administrator access exists from this PC**; one failed Guest sign-in is now in the server's log | the administrator runs the check |

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

## C0. Server identity: why the first session runs ON the server (2026-11-27)

From the office PC, a SQL connection to the live server is encrypted but the server's certificate cannot be verified:
the instance has no certificate the office PC trusts (it uses a self-signed one that SQL Server regenerates at every
start). Pinning it is impossible without first connecting; installing a proper certificate changes the server
configuration and restarts SQL Server for about a minute (`tools/prod-check/proposed-certificate-setup-live-host.ps1`,
prepared, needs approval; it is required later anyway for the sync agent, which verifies the certificate).

Therefore the **first production session runs on the live server itself**, over Remote Desktop, with Windows
authentication on the local instance (shared memory, no network TLS): `tools/prod-check/backup/Run-LiveBackupChecks-OnServer.ps1`.
No password is typed into anything of this project, nothing is stored, and the identity of the server is certain
because the script runs on it (it refuses to run if the instance is not on the same computer). It performs only the
backup-status report and `RESTORE VERIFYONLY` of the newest full backup, writes `live-backup-report-<date>.md` next to
itself and copies the report to the clipboard. WinRM (port 5985) is open on the server too, but in a workgroup it
offers no server authentication either and needs a client setting on the office PC, so it is not used.

Order of preference for the later sessions (read-only login, its verification):
1. the same Remote Desktop session with Management Studio or `sqlcmd` on the server (identity certain, nothing stored);
2. after the certificate is installed and trusted on the office PC (approval + 1-minute restart): `Invoke-LiveAdmin.ps1`
   from the office PC with certificate verification on (`TrustServerCertificate=no`), prompted credential, nothing stored.

## C. What the administrator runs (read-only, 2 minutes)

Exact steps for the authorized SQL Server administrator, on the live server or any PC with Management Studio that
can reach it:

1. Open SQL Server Management Studio. Server name: `LIVE-HOST\SQLEXPRESS` (if that is not found, `LIVE-HOST,1433`:
   the instance listens on the fixed port and the Browser service is off). Authentication: a sysadmin login.
2. Run `SELECT SERVERPROPERTY('ServerName')` and write the result down: it is the live server's identity and goes into
   the two scripts and into the website's settings.
3. Open `tools/prod-check/backup/0-live-backup-status.sql` (in the owner's package). Replace `LIVE-HOST` at the top with
   the name from step 2, including `\SQLEXPRESS`. Query > Results to Grid. Execute. Nothing is changed: the script reads
   only the server's own backup history (`msdb`) and database properties, and asks Windows whether the backup files
   still exist and how much disk space is free.
4. Nine grids: server and Agent status, the database's state and last backup dates, the newest full / differential /
   log backup with age in hours, checksum flag, file path and whether the file exists, the last 15 backups, every
   restore ever done there, scheduled jobs, all databases, a plain-language verdict, free space per drive.
5. Results > Save As (CSV or report), send the file to the owner. It contains no password and no business data.
6. If grid 3 shows the newest full backup without checksums, also run
   `RESTORE VERIFYONLY FROM DISK = N'<file from grid 3>'` (reads the file, restores nothing; a minute or two) and
   add its message to the report.

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

Storage: grid 9 of the status script shows the free space per drive and the default backup folder; about 1.8 GB is
needed (database 2.26 GB allocated, backup 1.7 GB; Express cannot compress). Operational impact: `BACKUP DATABASE`
is an online operation, nobody is disconnected and Access keeps working; it reads the whole data file once, so for
a few minutes the server's disk is busier (the same 1.7 GB backup took 17 seconds on the office PC; on an older
server expect 1 to 5 minutes). Do it at a quiet moment, not in the 6:00 or 12:30 synchronization windows once those
exist.

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
