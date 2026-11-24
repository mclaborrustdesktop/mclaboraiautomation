# 5. Creating the restricted read-only login

> **Which database?** Names are defined in `docs/environments.md`. DEV-PC holds a **restored copy** (staging), not the live database. This document was first written believing DEV-PC was live. Use it as written for the copy; for the possible live database on LIVE-HOST see `09-plan-connect-live-database.md`.

Script: `tools\prod-check\proposed-grants.sql`. **Never run and not tested on a SQL Server.** Running it needs the
owner's approval and a SQL Server administrator (see `02-administrator-permissions.md`).

## What it creates

| Item | Name | Purpose |
|---|---|---|
| Login | `mclabor_web_read` | How the website signs in to SQL Server |
| Database user | `mclabor_web_read` (in `McLabor`) | Links the login to the database |
| Role | `mclabor_web_readonly` | Holds the read permissions |
| Permissions | SELECT on 288 named columns in 33 tables | Everything the website's search and record pages read |

It can not change, add or delete anything, run stored procedures, or see other tables.

Never readable through this login: in `tblEmployee`, SSN, bank name / routing / account numbers, dependents,
citizenship, country of birth, sex, race, W-4 and I-9 notes, date of birth, US-citizen flag, I-9 flag; in
`tblOfficeStaff`, the staff password.

Included on purpose, owner may still decide otherwise: pay and bill rates (`tblEmployee.BaseSalary` and the rate
columns in `tblTracking`), because the weekly tracking pages show them.

## Service impact

None. No restart, no interruption, no data change. This server already allows SQL logins.

## Steps

1. Choose a password of 16 or more characters. Write it on paper or in a password manager. Do not e-mail it or type
   it into a chat.
2. Open SQL Server Management Studio. Server name `DEV-PC\SQLEXPRESS`, "Windows Authentication", Connect.
3. Confirm you are a SQL Server administrator: New Query, `SELECT IS_SRVROLEMEMBER('sysadmin');`, Execute. It must
   show `1`.
4. File > Open > File > `Documents\MC-Labor-AI-Automation\tools\prod-check\proposed-grants.sql`.
5. Near the top, find `<<TYPE-A-LONG-PASSWORD-HERE>>` and replace it, including the `<<` and `>>`, with your
   password. Keep the single quotes around it.
6. Press **Execute** (F5).
7. Look at the Results tab:
   - first table: `288`, `33`, `SELECT`, `SELECT`
   - second table: empty
   The Messages tab must contain no red text.
8. Close the file **without saving**, so the password is not left in it.

If you forget step 5, the script prints "Replace the password placeholder..." and creates nothing.

## Check from the website's side (reads no records)

1. Open `tools\prod-check\prodcheck.env` in Notepad. Set `AUTH=sql` and `USER=mclabor_web_read`. Save.
2. In PowerShell, in `Documents\MC-Labor-AI-Automation`:
   `backend\.venv\Scripts\python.exe tools\prod-check\check_readonly.py`
3. Type the password when asked. Nothing appears while you type.
4. Expected in section 4: no write permission, sensitive columns not readable, 33 tables visible.

This check only works once the certificate is in place (`04-certificate-deployment-plan.md`).

## Rollback

In SSMS, New Query, then Execute:

```
USE [McLabor]; DROP USER [mclabor_web_read]; DROP ROLE [mclabor_web_readonly];
USE [master];  DROP LOGIN [mclabor_web_read];
```

## Keeping it safe afterwards

- The password is typed once more, into `backend\.env` on this PC, when the website is switched to production.
- Do not add this login to `db_datareader`, `db_datawriter` or `db_owner`, even temporarily.
- If the password may have leaked: `ALTER LOGIN [mclabor_web_read] WITH PASSWORD = N'new password';`
