# 1. Backup and restore verification checklist

> **Which database?** Names are defined in `docs/environments.md`. DEV-PC holds a **restored copy** (staging), not the live database. This document was first written believing DEV-PC was live. Use it as written for the copy; for the possible live database on LIVE-HOST see `09-plan-connect-live-database.md`.

Do this before any change to the SQL Server PC (update, certificate, login). A backup is only proven when it has
been restored once. Nothing here has been done yet.

Facts read from this PC on 2026-11-20:

- SQL Server Management Studio (SSMS) is installed. `sqlcmd` is available.
- SQL Server's default backup folder: `C:\Program Files\Microsoft SQL Server\MSSQL15.SQLEXPRESS\MSSQL\Backup`.
  It could not be read from a normal account, so **whether any backup exists today is unknown.**
- Drive C: has about 848 GB free.
- SQL Server Express has no built-in backup schedule (SQL Server Agent is disabled). Unless someone set up a
  scheduled task, backups only happen when a person makes one.

## Findings on 2026-11-20 (read with SELECT-only queries; nothing was changed)

| Question | Answer |
|---|---|
| Is this the live database? | **No. It is a copy.** Restored on this PC on 2026-11-13 18:46 from a backup taken at 17:00 that day on `LIVE-HOST\SQLEXPRESS` by the login `mclabor` |
| Database size | 2,256 MB allocated: data file 1,928 MB, log file 328 MB (files named `11-4-2021.mdf` / `11-4-2021_log.ldf`) |
| Expected backup size | About 1.7 GB (the 11-13 backup is 1,706.5 MB; Express cannot compress) |
| Recovery model | SIMPLE, so a full backup is the whole story; there are no log backups to manage |
| Page protection | CHECKSUM is on, so a backup WITH CHECKSUM re-checks every page |
| Backups ever taken of this copy | **None.** The only record is the 11-13 backup it was restored from, and that one was made without checksums |
| That backup file | `C:\ZZZ-SQL\McLabor_2026_11_13_170000.80.bak`, 1,707 MB, still on this PC |
| Free disk space | C: 848 GB of 930 GB. C: is the only disk; no external or network drive is attached |
| Scheduled SQL backups | None found |
| People connected to the copy | 0 at the time of the check |
| Logins on this SQL Server | `DEV-PC\<windows-user>` (administrator), `mclabor` (SQL login), `BUILTIN\Users`, `sa` (disabled) |

Security notes for the owner:

- `C:\ZZZ-SQL` can be read by every user of this PC, and the backup file in it contains SSNs and bank details.
- `BUILTIN\Users` is a login on this SQL Server: every Windows user of this PC can sign in to it. What they can see
  was not checked.
- Copies of the Access database files are on the Desktop and in OneDrive.

### Result: backup and restore test on the staging copy, 2026-11-20 (approved by the owner)

| Step | Result |
|---|---|
| Backup | `McLabor_DEV-PC_2026-11-20_123448_full_copyonly.bak`, 1,705.7 MB, full, copy-only, with checksums. 17 seconds |
| Verification | "The backup set on file 1 is valid" |
| Restore test | Restored as `McLabor_RestoreTest` (no REPLACE). 28 seconds including the checks |
| Consistency check | `DBCC CHECKDB` on the test copy reported no errors |
| Row counts, McLabor vs test copy | All SAME: tblEmployee 178,993; tblEmployeeB 178,993; tblCustomer 106,828; tblTracking 192,225; tblProject 15,748; tblOfficeStaff 82. 294 tables in both |
| Cleanup | `McLabor_RestoreTest` dropped; no files left behind |
| McLabor afterwards | Online, same files, same row counts. SQL Server was not restarted |

Still open: the backup exists only on DEV-PC. The client has not yet chosen a location outside this PC.

### Proposed backup destination

`C:\Program Files\Microsoft SQL Server\MSSQL15.SQLEXPRESS\MSSQL\Backup\` (SQL Server's own backup folder).
Only administrators and SQL Server can open it, which suits a file containing SSNs. File name:
`McLabor_DEV-PC_<date>_<time>_full_copyonly.bak`.

Alternative: `C:\ZZZ-SQL\` is writable by SQL Server and easier to browse, but open to every user of the PC.

### Copy outside this PC

Not possible today without a decision: no external drive or network share is connected. OneDrive is present, but
putting SSNs and bank details in a cloud folder is the client's decision. Options for the client: an encrypted
external drive kept locked away, or a folder on `LIVE-HOST` restricted to administrators.

### Prepared scripts (none run)

`tools\prod-check\backup\`: `1-full-backup-with-checksum.sql`, `2-restore-test.sql`, `3-remove-restore-test.sql`.
They do steps B and D below in one go each.

## A. Find out what exists today (changes nothing)

- [ ] In SSMS, connect to `DEV-PC\SQLEXPRESS`. Right-click `McLabor` > Properties > General. Write down
      "Last Database Backup". If it says "None" or is old, treat the database as not backed up.
- [ ] Write down the database size shown on the same page: __________ MB.
- [ ] Ask: is there a copy of any backup on another drive or another computer? Yes / No

## B. Make a full backup (reads the database; users can keep working)

- [ ] In SSMS: right-click `McLabor` > Tasks > Back Up.
- [ ] Backup type: **Full**. Tick **Copy-only backup** (so any existing backup routine is not disturbed).
- [ ] Destination: one file, named with the date, for example `McLabor_2026-11-21_full.bak`.
- [ ] Options page: tick **Verify backup when finished** and **Perform checksum before writing to media**.
- [ ] Press OK. Wait for "completed successfully".
- [ ] File size is plausible compared with the database size from A: __________ MB.

## C. Copy it off this PC

- [ ] Copy the `.bak` file to an external drive or another computer. A backup that lives only on the PC it protects
      does not protect against that PC failing.
- [ ] The file contains SSNs and bank details. Keep the copy somewhere locked, and do not e-mail it.

## D. Prove it restores (creates a temporary test copy - needs the owner's OK)

This creates a second database on the server for a few minutes. It does not touch `McLabor`.

- [ ] In SSMS: right-click Databases > Restore Database > Device > select the `.bak` file.
- [ ] **Change the "Database" name to `McLabor_RestoreTest`.** Never restore over `McLabor`.
- [ ] Files page: tick "Relocate all files to folder" so the test copy gets its own files.
- [ ] Press OK. Wait for "restored successfully".
- [ ] Open `McLabor_RestoreTest` > Tables. Right-click `dbo.tblEmployee` > Properties > Storage. The row count
      matches the same table in `McLabor`: __________ = __________
- [ ] Repeat for `dbo.tblCustomer`, `dbo.tblProject`, `dbo.tblTracking`.
- [ ] Right-click `McLabor_RestoreTest` > Delete (tick "Close existing connections"). Check you are deleting the
      **test** database.

## E. Also keep

- [ ] A copy of the Access front-end file (`.accdb`) as it is today.
- [ ] A note of who made the backup, when, and where the copies are.

## If something goes wrong later

Restoring over the live database replaces everything entered since the backup. It is the last resort, and the
decision belongs to the owner. The certificate and login steps each have their own, much smaller, undo steps.
