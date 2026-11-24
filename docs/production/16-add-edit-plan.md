# 16. Adding and editing employee, customer and job records: implementation and test plan

Written 2026-11-23, for the stage AFTER the read-only website has been validated on the live database. Nothing in
this plan is switched on. Today every change is refused three times over (API, statement guard, SQL login).

## 1. What the demo already does (and will do unchanged on real data)

Add/Edit forms for employees (with licence list), customers (with contacts and notes), jobs, and weekly tracking;
reference validation (`integrity.py`); duplicate detection with a confirm step (`duplicates.py`); the editing user's
initials on the row-level entry stamps; an activity row per change. `python -m app.prodverify` lists which form
fields map straight onto a production column: all except three derived fields.

## 2. What must be built before the first real write

| # | Work | Why | Size |
|---|---|---|---|
| W1 | **Write mapping for the derived fields**: years in trade (`YearsInTradeID` from the lookup label), will-travel (`tblEmployeeB.WillTravel`, insert the extension row if missing), site city/state (`SiteStateCityID` from the city lookup; the text columns are not written in production) | They display correctly but the forms cannot save them | 1-2 days incl. tests |
| W2 | **Per-column audit stamps**: for every column that has a `<Column>UserName` / `<Column>Timestamp` pair in the schema export, set both when that column changes (a generic helper driven by the export, not hand-written per field) | Access screens show "changed by / on" per field; without this website edits look anonymous there | 1 day |
| W3 | **Lookup validation against the real lookup tables**: refuse blank or inactive lookup values (the real tables contain blank rows); `Active` flags where they exist | A save must not point at a blank status | half a day |
| W4 | **Duplicate rule confirmed with the office**: which fields make a "probable duplicate" (today: name + phone / e-mail / DOB / city) and whether confirming is allowed for everyone | A wrong rule blocks real entries or lets duplicates in | a meeting, then an hour |
| W5 | **Notes are append-only; deletes become deactivation**: no DELETE on master tables from the website (the write login will not have it); employee delete already refuses when tracking exists | Matches the Access practice and the login's rights | half a day |
| W6 | **Concurrency**: when two people edit the same record, the second save must not silently overwrite the first. Compare the row's entry/audit timestamp from when the form was opened; refuse with "changed by X at Y, reload" | Two applications (Access and web) on the same tables | 1 day |
| W7 | **Write login**: `tools\prod-check\proposed-grants-write.sql` (second login `mclabor_web_write`, INSERT/UPDATE on the form columns, INSERT only on notes, no DELETE on masters, no restricted columns); the website uses it only when writes are enabled, the read-only login for everything else | Least privilege at the database too | script written; needs approval |
| W8 | **Write switch wiring**: `*_WRITES_ENABLED=true` + `*_WRITE_APPROVAL=<reference>` select the write login and lift the 423 and the statement guard for INSERT/UPDATE (DDL stays blocked); the status page shows "writes ON since <date>, approval <reference>" in red | Explicit, visible, reversible in one line | half a day |
| W9 | **Change log**: every write records who, when, table, id and the changed columns (old and new values for non-restricted columns) in the website's own log file, not only the activity table | To answer "who changed this" and to undo a mistake | half a day |

## 3. Test plan (on the restored copy on DEV-PC, never on the live database first)

Approval reference for the rehearsal: `STAGING_WRITES_ENABLED=true`, `STAGING_WRITE_APPROVAL=<owner's reference>`.
Before: a fresh restore of the copy from the 2026-11-13 backup (so the rehearsal can be repeated), and the write login
created on the copy with `proposed-grants-write.sql` (guarded to DEV-PC).

| # | Test | Pass when |
|---|---|---|
| T1 | Automated: the existing 140 tests plus new tests for W1-W6 and W8 on SQLite | all green |
| T2 | Automated on the copy: `prodverify` with writes on reports no restricted column and no column outside the write grants | OK |
| T3 | Create one employee, one customer, one job, one tracking row through every form; open each in Access on the copy | every field, including years in trade, will-travel and site city/state, shows the same value in Access |
| T4 | Edit each of them in the website; check the per-column "changed by / on" stamps in Access | stamps show the web user's initials and the time |
| T5 | Edit the same employee in Access and then save an older form in the website | the website refuses with "changed by ... reload" (W6) |
| T6 | Try to delete an employee / customer / job via the API with the write login | 403/409 from the website; SQL Server refuses DELETE for the login |
| T7 | Try to write a restricted column (SSN, DOB) via the API with a crafted request | refused by the website and by SQL Server |
| T8 | Switch writes off (`STAGING_WRITES_ENABLED=false`); repeat one save | 423 again; the read-only login is in use again |
| T9 | Row counts and a checksum of the four main tables before and after the whole rehearsal, minus the rows the tests created | identical |
| T10 | Load test with writes on: 35 readers plus 5 writers for 10 minutes | no errors, no deadlock, read timings as before |
| T11 | Restore the copy from backup after the rehearsal | restore succeeds; the rehearsal left nothing behind |

## 4. Going live with writes, one screen at a time

1. Owner's written approval naming the environment, date, scope and the approval reference (becomes
   `PRODUCTION_WRITE_APPROVAL`). A restore-tested backup from that day.
2. Administrator runs `proposed-grants-write.sql` (live-server copy, guard changed to `LIVE-HOST\SQLEXPRESS`) on the
   live database; password stored on the web PC like the read-only one.
3. Day 1: **notes only** (employee and customer notes, append-only). Lowest risk; Access users see them immediately.
4. Day 3+: employee edits, then customers, then jobs, then weekly tracking, each after a day without problems.
5. Access users told which screens are also editable from the website and who to call. The change log (W9) is
   reviewed daily during the first two weeks.
6. Back-out at any point: `PRODUCTION_WRITES_ENABLED=false` and a backend restart; the write login can be dropped
   with three lines.

## 5. Estimated effort

About two weeks of development and testing for W1-W9 and T1-T11, plus the office's time for W4, T3 and T4.
None of it should start before the read-only website is in everyday use on the live database, because T3 and T4
depend on the live data shape (the contact columns question, `11`, is an example of what only the live data shows).
