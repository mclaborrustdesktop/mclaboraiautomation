# 12. What is still required before production (2026-11-23)

Three questions the owner asked after the staging pilot, answered as checklists. Nothing here has been started on
LIVE-HOST, and no permission anywhere has been changed.

## A. Confirming which database the office really uses

Today the website has only ever read the **restored copy** on DEV-PC. The live database is *probably*
`McLabor` on `LIVE-HOST\SQLEXPRESS` (`<live-host-ip>`), but that is an inference from the backup history and from
developer copies of the Access files on this PC (`07-database-location-findings.md`). It is not proof.

Required, all of them, written down with the date and who checked:

| # | Requirement | Who | How | Done? |
|---|---|---|---|---|
| A1 | The SERVER and DATABASE in the linked tables of the Access file a staff member opens for real work | Any staff member + whoever supports them | `07`, "Manual check" (Shift-open, External Data > Linked Table Manager, write down `SERVER=` and `DATABASE=`; change nothing) | |
| A2 | The same on a second staff PC | Same | Same | |
| A3 | Which file each shortcut opens, and the file's date | Same | Right-click the shortcut > Properties | |
| A4 | People are connected to that database during working hours | A SQL Server administrator on that server | `tools\prod-check\list-active-sessions.sql` (read-only) | |
| A5 | A record entered in Access today exists in that database | A staff member names a job or note they added today; an administrator looks it up there | Read-only query by id | |
| A6 | The owner states in writing which server and database are live | Owner | One e-mail | |

A1 + A4 together are strong; A5 settles it; A6 is what the website's settings will cite
(`PRODUCTION_DB_EXPECTED_SERVER_NAME`). Evidence that is **not** enough on its own: the server's name, the fact that
the 2026-11-13 backup came from it, or the Access files on DEV-PC.

After A1 to A6, Plan B (`09-plan-connect-live-database.md`) applies: backup and restore test on LIVE-HOST, the
SQL Server update, the certificate with the name `LIVE-HOST`, the read-only login in `McLabor` only, the connection
check, then a read-only pilot. Each of those steps still needs its own approval.

Two things learned from the copy that must be settled before the live read-only pilot is judged:

- Employee contact columns are empty in the copy (`11-employee-contact-findings.md`). If they are empty on the
  live server too, the Access application keeps them somewhere else and the approved column list must grow.
- Word searches cost about one second of SQL Server CPU each on 179,000 employees (`docs/search-performance.md`,
  SQL Server section). With 30 people searching at once that is the limit of SQL Server Express. The application
  has been tuned as far as it can be without indexes; the next step is a decision on indexes or a full-text index
  on the live server, which is a database change.

## B. Before the website may Add or Edit real records

The website is read-only against real data by design: the API answers 423 to every change, a statement guard lets
only SELECT reach SQL Server, and the SQL login itself cannot write. Switching writes on means lifting all three.
Required first:

| # | Requirement | Why |
|---|---|---|
| B1 | A written approval from the owner naming the environment (staging first, never production first), the date and the scope (which screens may save) | It becomes `PRODUCTION_WRITE_APPROVAL` / `STAGING_WRITE_APPROVAL`; the website refuses to write without it |
| B2 | A backup taken immediately before the first write-enabled day, restore-tested | `01-backup-and-restore-checklist.md`; the only way back from a bad save |
| B3 | A second SQL login with INSERT/UPDATE on exactly the approved columns, no DELETE on `tblEmployee`/`tblCustomer`/`tblProject`, still no access to the restricted columns | The read-only login stays for reading; the write login is a separate decision and a separate script, not yet written |
| B4 | The write mapping for the fields that are stored elsewhere in the real database: years in trade (`YearsInTradeID` lookup), will-travel (`tblEmployeeB`), site city/state (`SiteStateCityID`) | Today these display correctly but the forms cannot save them (`python -m app.prodverify` lists them as "read-only in production") |
| B5 | Per-column audit stamps: the real tables keep `<Column>UserName` + `<Column>Timestamp` pairs that Access fills in. The website fills only the row-level entry stamps and the activity table | Without them, Access screens show "changed by: (blank)" for website edits |
| B6 | Lookup validation against the real lookup tables (blank lookup rows exist; see `10`) | A save must not point at a blank or inactive lookup value |
| B7 | A decision on duplicates: the website refuses a probable duplicate employee/customer unless the user confirms. Confirm that rule matches office practice | `duplicates.py`; a wrong rule either blocks real entries or lets duplicates in |
| B8 | A rehearsal on the restored copy with `STAGING_WRITES_ENABLED=true`: create, edit and delete through every form, then compare the rows in SQL Server with what Access shows | First time any website write touches real tables; done on the copy where it can be undone by a restore |
| B9 | Access users told which screens are now also editable from the website, and who to call | Two applications editing the same tables |
| B10 | Only after B8 passes on the copy: the same on the live server, one screen at a time, starting with notes (append-only, lowest risk) | Smallest possible first step |

Still outside this list and open since the pilot: whether pay and bill rates may be shown at all, and who may
use the website (now configurable: `WEB_ADMINS` for everything, `WEB_USERS` for look-up only;
`docs/access-without-login.md`).

## C. Employee records and the outside AI service (Claude)

What the website sends to Claude when it is used: the typed question, the fixed vocabulary (trade, status and
customer-type names, state codes) and the list of city names. In the demo it also sends the sales-rep names and the
industry labels. **Employee, customer and job records are never sent**: Claude only turns the question into filters,
and every result row comes from the database.

Controls now in the code (2026-11-23):

| Control | Where |
|---|---|
| With real data, Claude is only used when `CLAUDE_REAL_DATA_APPROVAL` holds the owner's approval reference. Without it the built-in parser is used even if a key is present | `config.py` (`claude_allowed`), `ai.py` |
| With real data, the website refuses to start if `ANTHROPIC_API_KEY` is set without that approval | `config.environment_problems()` |
| With real data, no staff name and no customer-derived text goes into the prompt (only cities and the fixed vocabulary) | `ai._system_prompt` |
| The staging runner clears the key for every process it starts | `tools\staging\run-in-staging.ps1`, `run-readonly.ps1` |
| The status page shows whether a key is present, whether the service is in use, whether approval is recorded, and what would be sent | `/api/system/status`, "outside_ai_service" |
| The pilot script fails if the running website reports anything but the built-in parser | `tools\staging\pilot.py` |

What the approval should cover, if the owner ever wants Claude with real data: that typed questions may contain
names (staff will type "find John Smith"), where the service keeps data and for how long (Anthropic's data retention
terms for API use), and whether a data processing agreement is needed. Until approved, the answer is simply no key.
