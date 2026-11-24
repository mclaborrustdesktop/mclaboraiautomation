# 13. Procedure for the database administrator: where are the employees' contact details?

For whoever administers the McLabor SQL Server. About 15 minutes. Counts only: no name, phone number, address
or e-mail is displayed, copied or sent. Nothing is changed. **Run it on the restored copy on DEV-PC**
(`DEV-PC\SQLEXPRESS`, database `McLabor`). Do not run it on LIVE-HOST unless the owner asks for that separately.

## Background (one paragraph)

The website reads the approved employee contact columns `EmStreet`, `EmStateCityID`, `EmCity`, `EmState`,
`EmZip`, `EmHomePhone`, `EmMobilePhone`, `EmEmail`. On the copy they are NULL for all 178,993 employees, including
the 1,213 who worked in the last two years, while names, trades and entry stamps are filled and customer phone
numbers are 62% filled (`11-employee-contact-findings.md`). The website's login may not read the other address and
phone columns, so only an administrator can tell whether the data is elsewhere or was removed from the copy.

## Steps

1. Open SQL Server Management Studio on DEV-PC and connect to `DEV-PC\SQLEXPRESS` with an administrator account.
   Choose the database `McLabor`.
2. Open `tools\prod-check\contact-columns-admin-check.sql` (File > Open) and read it: three SELECT statements,
   every column wrapped in `COUNT` or `SUM(CASE ...)`. There is no UPDATE, no INSERT, no DELETE, no EXEC.
3. Execute it (F5). Three result grids appear. Each cell is a number.
4. Save the three grids as text (right-click a grid > Save Results As, or copy and paste into an e-mail) and send
   them back. They contain counts only.
5. Close Management Studio. Do not save anything else.

What the result means:

| Result | Meaning | Next step |
|---|---|---|
| Grid 1: `EmMobilePhone`, `EmHomePhone`, `EmEmail`, `EmStreet`, `EmCity` all **0**, and grid 3 (the "mobile phone changed on" stamps) is **empty** | The values were never in this copy: they were cleared, and the stamps with them, before or after the backup | Ask whoever produced the backup; the live server most likely has the data and the website needs no change |
| Grid 1: those columns **0** but grid 3 **has rows** | The values were entered and later removed; the stamps stayed | Same as above; the removal was deliberate |
| Grid 1: `EmAddress`, `EmSmartPhone` or `TextMsgAddress` **filled** while the approved columns are 0 | The Access application stores the data in those columns | The owner decides whether they may be added to the website's approved column list (`proposed-grants.sql`, `required_schema.json`); then the website maps them |
| Grid 2: `EmMobilePhone2`, `EmHomePhone2` or `EmEmail2` **filled** | Extra numbers live in the extension table | Same decision for `tblEmployeeB` columns |
| Grid 1: approved columns **filled** | The copy on DEV-PC differs from what the website saw, which should not be possible | Send the numbers; the website's read path will be re-checked |

## What this procedure deliberately does not do

- It does not read a single value. If a step is needed that shows values (for example, checking the format of
  phone numbers), it is a separate request with its own approval, and the output stays on the server.
- It does not touch LIVE-HOST. If the live server needs the same check later, the owner approves it and the same
  script is used (its first lines then need the live server's name).
- It does not change a permission. Granting the website more columns is a separate script and approval.
