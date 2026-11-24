# Read-only connection check for the McLabor SQL Server

A separate tool in `tools/prod-check/`. It does not use the website's code or settings, so the running demo stays in
demo mode. It connects once, asks the server about itself (version, permissions, table and column names), and
disconnects. It never reads a row from any business table and cannot write.

## What is needed

| Requirement | Status on this PC (DEV-PC) |
|---|---|
| ODBC driver | `ODBC Driver 17 for SQL Server` is installed and will be used. Driver 18 also works. The old `SQL Server` and `Native Client 11.0` drivers are deprecated and are not used. |
| Python driver | `pyodbc 5.5.0` is installed in `backend\.venv`. |
| Network | This PC must reach the SQL Server over the office network (or VPN). SQL Server must already accept TCP/IP connections: port 1433 for a default instance, or the SQL Server Browser service for a named instance such as `SERVER\SQLEXPRESS`. If SQL Server runs on this same PC, no network is needed. **No port is to be opened and no server setting changed without approval.** |
| Encryption | The check always asks for an encrypted connection. A server with a self-signed certificate needs `TRUST_SERVER_CERTIFICATE=yes`; the check tells you if so. |

## Windows sign-in or a SQL login?

- This PC is signed in with a **local account** (`DEV-PC\<windows-user>`), not a Windows domain account.
- Windows authentication therefore works only if SQL Server runs **on this same PC**. Against another computer it
  will be refused.
- If the server is another computer, a **dedicated read-only SQL login** is required. That needs the server to allow
  "SQL Server and Windows Authentication mode". If Access already signs in with a SQL user name, that mode is on.
  If it is off, turning it on is a server change that needs approval and a SQL Server restart.
- Do not reuse the login the Access application uses: it can change data.

## Minimum permissions

The login needs `CONNECT` to the `McLabor` database and `SELECT` on named columns only:
33 tables, 288 columns, listed in `tools/prod-check/required_schema.json`. Nothing else: no `db_datareader`,
no INSERT/UPDATE/DELETE, no EXECUTE.

Deliberately not granted:

- `tblEmployee`: SSNum, BankName, BankRoutingNumber, BankAccountNumber, BankAccountTypeID, BankAccountActionID,
  Dependents, Citizenship, EmCountryOfBirth, EmSex, EmRaceID, EmW4Notes, EmI9Notes, EmDOB, USCitizen, I9Complete
- `tblOfficeStaff`: OfficeStaffPassword

`tools/prod-check/proposed-grants.sql` is a ready-to-review script for whoever administers the server.
**It has not been run.** The check fails on purpose if the login can write, or can read any column in the list above.

Owner decisions still open:

- Pay and bill rates (`tblEmployee.BaseSalary`, `tblTracking` rates) are included because weekly tracking needs them.
  They can be withheld too.
- The demo shows date of birth, US-citizen and I-9 flags. In production these stay hidden until approved, and the
  web app must be changed to stop asking for them before it can run on the restricted login.

## How to run it

1. Open the folder `Documents\MC-Labor-AI-Automation\tools\prod-check`.
2. Copy `prodcheck.env.example` and name the copy `prodcheck.env`.
3. Open `prodcheck.env` in Notepad. After `SERVER=` type the SQL Server name exactly as Access uses it. Save.
   - Other computer: set `AUTH=sql` and `USER=` to the approved read-only login. Never type a password in the file.
   - Same PC: leave `AUTH=windows`.
4. Open PowerShell in `Documents\MC-Labor-AI-Automation` and run:

   ```
   backend\.venv\Scripts\python.exe tools\prod-check\check_readonly.py
   ```

   With `AUTH=sql` it asks for the password; typing is hidden and it is not saved.
5. The result is shown and saved in `tools\prod-check\reports\`. The report contains no password.

To test the PC and the settings without touching the network, add `--preflight`.
