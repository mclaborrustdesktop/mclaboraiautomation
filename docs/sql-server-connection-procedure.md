# Procedure: a trusted, read-only connection to the McLabor SQL Server

Written for the owner. Nothing in this procedure has been carried out. Steps marked **APPROVAL** change the SQL
Server PC and must be approved by the owner and done by someone signed in as a Windows administrator who is also a
SQL Server administrator.

Server: `DEV-PC\SQLEXPRESS` (SQL Server 2019 Express, version 15.0.2000.5), database `McLabor`, on the same PC as
the website. The server already accepts SQL logins as well as Windows accounts, so no server setting needs changing.

## What will be different afterwards

- SQL Server shows a certificate named `DEV-PC`, so programs on this PC can check they are talking to the right server.
- One new login exists, `mclabor_web_read`. It can read 288 approved columns in 33 tables and nothing else.
- The Access application, its logins and all data are unchanged.

## Step 0 - Before anything (no approval needed, changes nothing)

1. Pick a time when **nobody is using Access**. Step 2 disconnects everyone for about a minute and unsaved work in
   open Access screens can be lost.
2. Have a current **backup of the McLabor database** that you know can be restored. The steps below do not touch
   data, but no server work should be done without one. In SQL Server Management Studio: right-click `McLabor` >
   Tasks > Back Up > Full. Copy the `.bak` file to another drive.
3. Keep a copy of the Access front-end file (`.accdb`) as it is today.
4. Know who to call if SQL Server does not start. With no IT team, decide this before starting.

## Step 1 (optional, recommended) - Update SQL Server - **APPROVAL**

The server has never been updated since installation. See `docs/sql-server-update-review.md`. This is a separate
decision; the certificate and the login work without it. If you do it, do it first, with its own backup and its own
quiet time, and confirm Access still works before continuing.

## Step 2 - Install the certificate - **APPROVAL**

Script: `tools\prod-check\proposed-certificate-setup.ps1` (reviewed in `docs/certificate-script-review.md`; never run).

What happens, in order:

1. A certificate for `DEV-PC` is created on this PC, valid 5 years.
2. The script checks it meets SQL Server's requirements. If not, it deletes it and stops. Nothing else has changed.
3. SQL Server's own service account is allowed to read the certificate's key. Checked.
4. One SQL Server setting is changed: which certificate to use. The old value is saved in
   `tools\prod-check\certificate-setup-state.json`.
5. The certificate is added to this PC's list of trusted certificates.
6. **SQL Server restarts. Service interruption: about one minute.** Access shows connection errors during that time.
   The demo website is not affected (it uses its own demo data).
7. If SQL Server is not running again within 90 seconds, the script puts the old setting back and starts it again.

How to run it:

1. Click Start, type `PowerShell`, right-click **Windows PowerShell**, choose **Run as administrator**.
2. Type: `cd $env:USERPROFILE\Documents\MC-Labor-AI-Automation\tools\prod-check` and press Enter.
3. Type: `powershell -ExecutionPolicy Bypass -File .\proposed-certificate-setup.ps1` and press Enter.
4. The last line must start with `Done. SQL Server is running`. Then open Access and confirm it works.

Rollback (if Access misbehaves afterwards): the undo commands are at the bottom of the script. They put the old
setting back, restart SQL Server (another minute of interruption) and remove the certificate.

## Step 3 - Create the read-only login - **APPROVAL**

Script: `tools\prod-check\proposed-grants.sql` (never run). No restart, no interruption, no data change.

1. Open SQL Server Management Studio and connect to `DEV-PC\SQLEXPRESS` as an administrator.
2. File > Open > File, choose `proposed-grants.sql`.
3. Near the top, replace `<<TYPE-A-LONG-PASSWORD-HERE>>` with a password of 16 or more characters. Write it down
   somewhere safe. Do not e-mail it or paste it into a chat. If you forget to replace it, the script stops and
   creates nothing.
4. Press **Execute**.
5. At the bottom of the results: the first table must show `288` and `33` and `SELECT`; the second must be empty.

Rollback: the three `DROP` lines at the bottom of the script remove the login completely.

## Step 4 - Run the read-only check (no approval needed; reads no records)

1. Open `tools\prod-check\prodcheck.env` in Notepad. Change `AUTH=windows` to `AUTH=sql` and `USER=` to
   `USER=mclabor_web_read`. Leave `TRUST_SERVER_CERTIFICATE=no`. Save.
2. In a normal PowerShell window:
   `cd $env:USERPROFILE\Documents\MC-Labor-AI-Automation`
   `backend\.venv\Scripts\python.exe tools\prod-check\check_readonly.py`
3. Type the login's password when asked (nothing appears while you type).
4. The last section must say **READ-ONLY CONNECTION VERIFIED** with no `[FAIL]` lines. The report is saved in
   `tools\prod-check\reports\`.

## Step 5 - Live search test (developer step, read-only)

Only after Step 4 passes. This is the first time employee, customer and job records are read by the website's code.

1. Create `backend\.env` from `backend\.env.example`: a new random `JWT_SECRET`, `DATA_SOURCE=production`, the server
   name, `PRODUCTION_DB_USER=mclabor_web_read` and its password. Writes stay off.
2. `cd backend` then `.venv\Scripts\python.exe -m app.livecheck`. It prints counts and timings only.
3. Give the first administrator a web password: `.venv\Scripts\python.exe -m app.webauth set-password INITIALS`.
   There is no default administrator password in production.
4. Start the website and compare a few searches with the same searches in Access.

To go back to the demo at any time: rename `backend\.env` to `backend\.env.off` and restart the website.

## What needs whose approval

| Step | Changes the SQL Server PC? | Interruption | Approval |
|---|---|---|---|
| 0 Backup and timing | No | None | - |
| 1 SQL Server update | Yes | Several minutes, restart | Owner |
| 2 Certificate | Yes | About 1 minute | Owner |
| 3 Read-only login | Yes (adds a login) | None | Owner |
| 4 Read-only check | No | None | - |
| 5 Live search test | No (reads records) | None | Owner, for reading real records |
