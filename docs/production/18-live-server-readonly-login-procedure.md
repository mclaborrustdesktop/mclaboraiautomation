# 18. Live server: creating and verifying the read-only synchronization login (administrator procedure)

For the client's SQL Server administrator. Every step was rehearsed on the restored copy on 2026-11-26
(`17-readonly-login-verification.md`, section 6). Nothing here changes a business record, a server setting or an
existing permission. Budget: about 15 minutes, no downtime, no restart, no Access user disconnected.

## Before you start (owner)

- [ ] A recent, restore-tested backup of the live database exists (the usual nightly one is enough).
- [ ] You have the two files from the repository folder `tools/prod-check/`: `proposed-grants-production.sql` and
      `verify-readonly-login.sql`, and `prodcheck.env.production.example` for step 5.
- [ ] You know the live server's name as SQL Server reports it: in Management Studio run
      `SELECT SERVERPROPERTY('ServerName')`.

## Step 1: edit two placeholders in `proposed-grants-production.sql`

1. `LIVE-HOST` (two places near the top) -> the name from `SERVERPROPERTY('ServerName')`, including `\SQLEXPRESS`.
   The script refuses to run on any other server.
2. `<<TYPE-A-LONG-PASSWORD-HERE>>` -> a password of 16 or more characters that you generate (a password manager, or
   `python -c "import secrets;print(secrets.token_urlsafe(24))"`). Keep it in the company password safe. Never e-mail
   it, never paste it in a chat. It will be typed once more on the office PC (step 6).

## Step 2: run the script (Management Studio, signed in as a sysadmin, database `master` selected)

Open the file, press Execute. It is safe to run twice. Expected messages tab: no error. Expected result grids at the end
(STEP 4):

| Grid | Expected |
|---|---|
| select_column_permissions / tables | **288** / **33** |
| database_denies / column_denies | **18** / **17** |
| unexpected_role | **no rows** |

If it says "Wrong server" or "Replace the password placeholder", nothing was created: fix step 1 and run again.

What it created: one login `mclabor_web_read` (SQL authentication, password policy on, default database McLabor,
`DENY VIEW ANY DATABASE`), one database user, one role `mclabor_web_readonly`, 288 column SELECT grants, and the
explicit refusals (INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, CREATE *, ALTER ANY *, TAKE OWNERSHIP,
BACKUP) plus DENY SELECT on the 17 sensitive columns.

## Step 3: verify (Management Studio, same session, database `McLabor`)

Open `verify-readonly-login.sql`, press Execute. It impersonates the new login, asks the server what it may do, and
reverts. It reads no business row. Expected result grids:

| # | Grid | Expected on the live server |
|---|---|---|
| 1 | running_as | `mclabor_web_read` / `mclabor_web_read` / `McLabor` |
| 2 | server roles | every row `0` |
| 3 | database_role | one row: `mclabor_web_readonly` |
| 4 | database permissions | `CONNECT`, `VIEW ANY COLUMN ENCRYPTION KEY DEFINITION`, `VIEW ANY COLUMN MASTER KEY DEFINITION` (the last two are SQL Server defaults for every user; no data) |
| 5 | server permissions | `CONNECT SQL` only |
| 6 | write rights on any table/view | **no rows** |
| 7 | executable_routines | **0** |
| 8 | readable_approved_columns | **288** |
| 9 | sensitive columns | 17 rows, every `readable` = `0` |
| 10 | readable_unapproved | **no rows** |
| 11 | visible_database | `master`, `McLabor`, `tempdb` |

Any difference means the live server has a permission the copy did not have (typically a GRANT to `public`). Grids 6,
7 and 9 cannot show anything because of the DENYs; grid 10 can, and such a table must then be taken away from
`public` by you before the first synchronization. Save the output (Results -> Save as) and send it to the owner; it
contains no password and no data.

## Step 4: tell the owner the result

Owner's record: date, server name, the three STEP 4 numbers, grid 10 empty yes/no.

## Step 5: office PC, connection check with the new login (whoever runs the sync agent)

`tools\prod-check\prodcheck.env.production.example` -> copy to `prodcheck.env.production`, fill `SERVER` and
`EXPECT_SERVER_NAME` (the live server), `AUTH=sql`, `USER=mclabor_web_read`, `ENCRYPT=yes`,
`TRUST_SERVER_CERTIFICATE=no` (the server's certificate must be trusted by the office PC: `04-certificate-deployment-plan.md`).
```
backend\.venv\Scripts\python.exe tools\prod-check\check_readonly.py --config tools\prod-check\prodcheck.env.production
```
Type the password at the hidden prompt. Expected last lines: `READY - 0 problem(s), 0 warning(s)` with the 15 OK lines
seen in 17 section 6. The report file contains no password.

## Step 6: store the password for the agent (office PC, the Windows account that will run the scheduled task)

```
powershell -ExecutionPolicy Bypass -File tools\sync\store-sync-secrets.ps1 -Environment production
```
It asks for the SQL password and the website's sync key (hidden), encrypts them with Windows DPAPI for that account on
that PC, and writes nothing else. `tools\sync\sync.env` holds the non-secret settings (server, expected name, user,
`OFFICE_HOSTS`, `SYNC_API`).

## Step 7: first dry run (owner watching)

```
powershell -ExecutionPolicy Bypass -File tools\sync\run-sync.ps1 -DryRun
```
Reads the 33 tables with the new login, compares, sends nothing, prints per-table counts. Expected: exit 0, counts
close to the Access row counts, no warnings. Only after this, and separately approved: the first full run by hand,
then `register-sync-task.ps1`.

## Undo (if ever needed)

```
USE [McLabor]; DROP USER [mclabor_web_read]; DROP ROLE [mclabor_web_readonly];
USE [master];  DROP LOGIN [mclabor_web_read];
```
Removes the login and its permissions only; nothing else was created.
