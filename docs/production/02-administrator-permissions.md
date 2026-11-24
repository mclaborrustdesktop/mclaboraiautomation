# 2. Who is allowed to do what

> **Which database?** Names are defined in `docs/environments.md`. DEV-PC holds a **restored copy** (staging), not the live database. This document was first written believing DEV-PC was live. Use it as written for the copy; for the possible live database on LIVE-HOST see `09-plan-connect-live-database.md`.

Two different kinds of administrator are involved. Being one does not make you the other.

## Windows administrator (on the PC `DEV-PC`)

Needed for: installing a SQL Server update, running the certificate script, restarting the SQL Server service.

- Read from this PC on 2026-11-20: the Administrators group contains `DEV-PC\Administrator` and
  `DEV-PC\<windows-user>`. So the account used for this project **is** a Windows administrator.
- Programs still start without administrator rights. To use them: right-click the program and choose
  **Run as administrator**, then answer Yes.

What the certificate script uses, specifically:

| Action | Right needed |
|---|---|
| Create a certificate in the computer's certificate store | Windows administrator |
| Let the SQL Server service account read the certificate's key | Windows administrator |
| Change one SQL Server setting in the registry | Windows administrator |
| Add the certificate to "Trusted Root Certification Authorities" | Windows administrator |
| Restart the `SQL Server (SQLEXPRESS)` service | Windows administrator |

## SQL Server administrator (`sysadmin` inside SQL Server)

Needed for: creating the read-only login, backing up and restoring databases.

- **Unknown who has this.** It is usually the Windows account that installed SQL Server. Windows administrators are
  not automatically SQL Server administrators.
- How to check (changes nothing): open SSMS, connect to `DEV-PC\SQLEXPRESS` with "Windows Authentication", click
  **New Query**, type `SELECT IS_SRVROLEMEMBER('sysadmin');` and press Execute. `1` means yes, `0` means no.
- If the answer is `0`: find out which account the Access application's developer used, or whether the `sa` login
  is enabled and who knows its password. Do not guess passwords; several wrong attempts can lock a login.

What the read-only login script uses, specifically:

| Action | Right needed |
|---|---|
| `CREATE LOGIN` | `sysadmin` or `securityadmin` (server level) |
| `CREATE USER`, `CREATE ROLE`, `ALTER ROLE` in `McLabor` | `sysadmin`, or `db_owner` of `McLabor` |
| `GRANT SELECT` on the listed columns | `sysadmin`, or `db_owner` of `McLabor` |
| Back up `McLabor` | `sysadmin`, or `db_owner` / `db_backupoperator` |
| Restore to a test database | `sysadmin` or `dbcreator` |

## What the website will use afterwards

Only the new login `mclabor_web_read`: read access to 288 approved columns, nothing else. It is neither kind of
administrator. The website never uses the Windows administrator account or a `sysadmin` login.

## Approval

Each change to the SQL Server PC needs the owner's approval first, even though the account has the technical rights.
