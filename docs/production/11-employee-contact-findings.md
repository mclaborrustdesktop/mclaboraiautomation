# 11. Why employee contact details are empty (2026-11-23)

Question from the staging pilot: on the website every employee shows no city, state, ZIP, street, phone or e-mail.
Checked read-only on the **restored copy** (`DEV-PC\SQLEXPRESS`, data of 2026-11-13) with the website's own
restricted login. Counts only; no record was read or printed. Report: `tools\prod-check\reports\contact-check-20261123-092014.txt`
(repeat with `powershell -File tools\staging\run-readonly.ps1 ..\tools\staging\contact_check.py`; the website stays in DEMO).

## The four possible causes, and which one it is

| Cause | Checked how | Result |
|---|---|---|
| **Application mapping** - the website asks for the wrong columns | Model column names compared with the client's schema export | Not the cause. All eight columns (`EmStreet`, `EmStateCityID`, `EmCity`, `EmState`, `EmZip`, `EmHomePhone`, `EmMobilePhone`, `EmEmail`) exist in `tblEmployee` under exactly those names and are the ones the website reads |
| **Permissions** - the login may not read them | `HAS_PERMS_BY_NAME` per column, and the counts below succeeded | Not the cause. The login may read all eight (and the pilot displayed them: empty) |
| **Backup age** - the copy is too old | Newest entry stamps in the copy | Not the cause. Employees entered up to 2026-11-13, tracking to 2026-11-20, notes to 2026-11-13: the copy is current to the day of the backup |
| **Source data** - the columns are empty in the copy | NULL / blank / filled counts | **This is the cause.** All eight columns are NULL (not blank) for **every one of the 178,993 employees**, including the 1,213 employees who worked in the last two years |

Evidence that the rows themselves are real and that other contact data was *not* removed:

| Column | Filled |
|---|---|
| `tblEmployee.EmFirstName` / `EmLastName` | 178,993 (100%) |
| `tblEmployee.EmTradeID` | 178,103 (100%) |
| `tblEmployee.EmEntryUserName` / `EmEntryTimestamp` | 178,977 / 178,980 (100%) |
| `tblEmployee.EmLicensedIn` | 46,995 (26%) |
| `tblCustomer.Phone` | 66,728 of 106,828 (62%) |
| `tblCustomer.City` | 86,638 (81%) |
| `tblCustomerContacts.CustomerContactEmail` | 122,102 of 187,636 (65%) |
| `tblPullDownSalesman.PullDownSalesmanCell` | 34 of 51 (67%) |

So only the **employee** address, phone and e-mail columns are empty, and they are empty for 100% of rows. Data
that is merely incomplete never looks like this. Two explanations remain, and the website's login cannot tell them
apart because it may not read the other columns:

1. **The copy was scrubbed before hand-over.** Whoever made the 2026-11-13 backup on LIVE-HOST (or restored it here)
   set these columns to NULL to keep workers' personal details off this PC. Then the live database is fine and the
   website will show the details as soon as it reads the live database.
2. **The Access application keeps them in other columns.** `tblEmployee` also has `EmAddress`, `EmMailStreet`,
   `EmMailCity`, `EmMailState`, `EmMailZip`, `EmSmartPhone`, `TextMsgAddress`, and `tblEmployeeB` has
   `EmMobilePhone2..4`, `EmHomePhone2..4`, `EmEmail2..6`. None of these is in the website's approved column list,
   so the restricted login cannot look at them (confirmed: permission 0 on each).

A side finding: 3,646 employee notes contain something shaped like a phone number, and the most common note type
is "Quick Note" (16,781). Staff may type contact details into notes. The website's word search already covers notes.

## What to do (needs a person, not code)

1. **Ask whoever made the backup** whether employee contact columns were cleared. One sentence settles it.
2. If they were not cleared: a SQL Server administrator runs `tools\prod-check\contact-columns-admin-check.sql`
   on the copy. It returns counts only (how many employees have something in each candidate column, and whether the
   "mobile phone changed on" stamps are set). The result says which columns the Access application really uses.
3. If other columns turn out to hold the data, the owner decides whether they may be added to the website's
   approved list (`proposed-grants.sql` and `required_schema.json` change; the website's model then maps them).

Until then the website is **correct**: it shows what the copy contains. Nothing was invented or filled in, and the
searches "in MA", "in Boston", by ZIP and by phone digits find nobody on this copy because nobody has those values.

## What was NOT done

- No column outside the approved list was read (the login cannot).
- No value was displayed, exported or logged. Every query returned a count, a year or a length.
- LIVE-HOST was not contacted.
