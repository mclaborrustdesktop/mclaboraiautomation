# Feature status before production (2026-11-23; addenda 2026-11-24 below)

> **First release = search-only mirror (2026-11-24, later the same day):** the office SQL Server and Access remain the
> primary system; the cloud website shows a copy refreshed twice a day by the office sync agent and refuses every
> Add/Edit/Delete (administrators included) at the API and in the pages; a banner shows when the information was last
> refreshed and warns when it is outdated. The Add/Edit work below stays in the code (`SITE_MODE=full`) for a later
> release. Design, tests and what remains: `docs/cloud/13-one-way-sync.md`.

> **Addendum 2026-11-24 (Access-replacement phase, Railway + PostgreSQL):** Add/Edit for employees, customers, jobs
> and weekly tracking now has, in every environment: a change log per record (who, when, which fields; History
> section on the record pages and `/api/audit` for administrators), "changed by someone else" protection with row
> locking, lookup values refused when blank or inactive, tracking rules (0-24 h per day, rates, no duplicate week,
> no "do not contact" worker), and the three derived fields written correctly in the production shape (years in
> trade, will-travel, site city). The website runs on PostgreSQL (tested on PostgreSQL 16) with the schema generated
> from the SQL Server export. Counts: 185 backend tests, 9 frontend tests. Gaps against Access:
> `docs/access-replacement/01-access-workflow-audit.md`. On SQL Server environments the 423 read-only rule is unchanged.

"Works" = implemented and covered by the automated tests (148 backend, 9 frontend) and, where marked, verified on
the restored copy of the real database. "Blocked by design" = the code exists and works in the DEMO, but on real
data the website refuses it (423) until the Add/Edit stage is approved (`docs/production/16-add-edit-plan.md`).

| Area | View / list | Search and filters | AI search | Add | Edit | Delete | On real data |
|---|---|---|---|---|---|---|---|
| Employees | works (copy: 192 records opened, 0 failures) | works, exact counts proven on the copy | works, built-in parser; four pilot corrections done | works in DEMO; blocked by design | works in DEMO (licences list included); blocked by design | refused when tracking exists; otherwise DEMO only | read-only; contact columns empty in the copy (`11`) |
| Customers | works (160 opened) | works; word searches 1.6 - 3.2 s on the copy (full-text proposal) | works | DEMO only | DEMO only (contacts, notes) | DEMO only | read-only |
| Jobs | works (161 opened) | works | works | DEMO only | DEMO only | DEMO only | read-only; site city/state derived from the lookup |
| Weekly tracking | works (week grid, history) | works | - | DEMO only | DEMO only (hours, recompute) | DEMO only | read-only |
| Users and permissions | works | works | - | DEMO only | DEMO only | deactivate only | real data: `WEB_ADMINS` / `WEB_USERS` instead; Users page shows each person's website access |
| Dashboard | works (2.6 s on the copy; indexes proposed) | - | - | - | - | - | read-only |
| System status | works, administrators only | - | - | - | - | - | shows environment, server, access lists, AI service state |
| Sign-in | DEMO open; login mode with web passwords and lockout; gateway mode (proxy or Azure built-in) | | | | | | tested with forged headers and wrong addresses |

## What Add/Edit still needs before it can be switched on for real data

From `docs/production/16-add-edit-plan.md`, in priority order: write mapping for the three derived fields (years
in trade, will-travel, site city/state); per-column audit stamps the way Access writes them; validation against the
real lookup tables (blank rows exist); the duplicate rule confirmed with the office; "someone else changed this
record" protection between Access and the website; the second SQL login with INSERT/UPDATE only
(`proposed-grants-write.sql`); the write switch wiring and a change log. About two weeks, then the eleven-step
rehearsal on the restored copy.

## Smaller items open from the pilot and the reviews

| Item | Status |
|---|---|
| Pay/bill rates visible to everyone who can open a page | decision pending (`OfficeStaffHideHours` exists on the staff record and can be applied) |
| Employee contact columns empty in the copy | administrator's counts-only check pending (`13`) |
| Customer word searches at 30+ users | full-text / indexes proposals pending approval; not available on Express without Advanced Services |
| Claude for AI search with real data | off until the owner records approval; prompt already limited to lookup labels |
| Saved searches, Excel export, tracking grid conveniences | not started (`03-remaining-development.md`, B) |
| Container images built and smoke-tested | files and tests ready; needs Docker (decision 0.4 in `05`) |
