# Remaining development before production (2026-11-23)

What the application still needs, independent of the hosting decisions. Everything listed is application work
that can be done and tested on this PC against the demo data and the restored copy.

## A. Must have before the read-only website goes to staff

| # | Task | Why | Estimate |
|---|---|---|---|
| A1 | **Rehearse the container images** on a PC with Docker (DEMO profile), then the staging stack against the restored copy on the staging VM | The Dockerfiles and Compose stack were written without Docker on DEV-PC; they have not been built | 1 day |
| A2 | **Full-text switch**: `SEARCH_FULLTEXT=true` makes the keyword predicates use `CONTAINS(...)` (with the same ranking and filters), with the equivalence script extended to compare both modes on the copy | Word searches for 30 users; the index itself needs approval, the code can be ready | 2 days |
| A3 | **Pay/bill rate visibility** decided and enforced per person (`OfficeStaffHideHours` exists on the staff record; apply it to list and record pages for `WEB_USERS`) | Open decision from the pilot | 1 day after the decision |
| A4 | **Employee contact columns**: if the administrator's check (`docs/production/13`) finds the data in `EmAddress`, `EmSmartPhone`, `TextMsgAddress` or `tblEmployeeB`, map them (model, grants, `required_schema.json`) | Lists and search by city/phone are empty otherwise | 1 day after the answer |
| A5 | **Session handling behind the gateway**: a visible "signed in as" with the gateway's sign-out link; the 8-hour cookie life agreed with the office | Staff must be able to switch accounts on a shared PC | half a day |
| A6 | **Operational runbook**: start/stop, where logs are, how to add a person, how to roll a container image back, who is on call | Everyday operation by the office, not by the developer | half a day |

## B. Should have in the first months

| # | Task | Why |
|---|---|---|
| B1 | Saved searches per person (the real database already has `WebEmployeeSearchPreset` / `WebCustomerSavedView` tables from an earlier web front-end; reuse them) | Recruiters repeat the same searches daily |
| B2 | Export of a list page to Excel (bounded to the page, or to 2,000 rows with a warning) | Replaces the Access report for the common "give me the list" |
| B3 | Weekly tracking grid: week navigation by keyboard, totals per customer, print view | The dispatcher's daily screen |
| B4 | AI search: Claude with real data once the owner approves (`CLAUDE_REAL_DATA_APPROVAL`), with the vocabulary limited to lookup labels as already coded | Better understanding of free-text questions than the built-in parser |
| B5 | Employee record: a map/distance helper from the ZIP (needs an outside geocoding service: approval, and no names sent) | "electricians within 20 miles of the job" |

## C. Add / Edit stage

`docs/production/16-add-edit-plan.md`: nine pieces of work (W1-W9), the rehearsal on the restored copy
(T1-T11), the screen-by-screen rollout. About two weeks of development plus the office's time. Starts only after
A1-A6 and the read-only website is in everyday use.

## D. Later, when Access is retired

Move the database from the VM to Azure SQL Database (automatic patching and backups, lower cost), replace the
`mclabor` SQL login, retire the VPN if QuickBooks no longer needs it, and move the remaining Access reports into
the website.
