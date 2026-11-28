MC LABOR AI SEARCH - ONE-TIME SETUP ON YOUR SERVER (LIVE-HOST)
================================================================

What we are asking for
----------------------
The new MC Labor search website needs to READ a copy of the office database. We do not want your administrator
password, Remote Desktop access or any access to LIVE-HOST. Instead, we ask your administrator to run this folder ONCE
on LIVE-HOST. It creates one new, read-only database account for the website and nothing else.

What the new account can and cannot do
--------------------------------------
- CAN read 33 approved tables (customers, projects, employees' work details, tracking, lookup lists), 288 columns.
- CANNOT read: Social Security numbers, bank account and routing numbers, dates of birth, I-9 / W-4 notes, citizenship,
  race, sex, and staff passwords. These are refused by name and can never be switched on by accident.
- CANNOT add, change or delete anything, run any procedure, back up anything or see any other database.
- Your existing accounts, data, settings and backups are not changed.

What your administrator does (about 15 minutes)
-----------------------------------------------
1. Copy this whole folder to LIVE-HOST (USB stick or any file copy). It contains no passwords.
2. On LIVE-HOST, sign in as usual, right-click RUN-ME.cmd and choose "Run as administrator".
   (If your Windows account is not a SQL Server administrator, the script asks for the SQL administrator login.
   You type it there; it is never saved and never leaves the server.)
3. Answer the questions. The script asks before every change:
   a. A read-only check of the current backups. If no verified full backup exists it asks to take a safety backup
      first (a few minutes; nobody is disconnected). If the newest backup is older than a day, it recommends one.
   b. "Create the read-only login now?" - answer Y.
   c. "Install the server certificate and restart SQL Server now?" - answer Y, but only when nobody is working in the
      Access application: SQL Server restarts for about one minute and Access users have to reopen their screen.
      You may answer N and run RUN-ME.cmd again later for this step only.
4. When it says "Finished", copy the "results" folder back to us (USB stick or e-mail is fine).
   It contains: a report of what was checked and created (no data, no password), the server's public certificate,
   and the new account's password in an encrypted file that only our office PC (DEV-PC) can open.
   Nobody, including your administrator, needs to read or type the password.

What happens next, on our side
------------------------------
- We install the results on the office PC DEV-PC, which already belongs to your office. It will read the approved
  tables with the new account twice a day (06:00 and 12:30), over an encrypted connection that verifies your server's
  certificate, and copy them to the website. Nothing is written back to your database.
- Before any real data is copied, we will ask for your separate written approval.

To undo everything later
------------------------
Your administrator removes the one account in Management Studio (two lines, in the report), and, if wished, the
certificate (instructions in the report). Nothing else was added.

Questions: ray@mclabor.com
