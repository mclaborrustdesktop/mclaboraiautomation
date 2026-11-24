# 8. Plan A: staging - test everything on the restored copy

Reviewed 2026-11-20. Target: the **restored copy**, `DEV-PC\SQLEXPRESS`, database `McLabor` (see
`docs/environments.md`). The website runs it as the **STAGING** environment. Nothing in this plan touches LIVE-HOST.

No office user depends on the copy. It does contain real SSNs, bank details and staff passwords, so the website's
restrictions stay on and every step that changes DEV-PC needs the owner's approval.

**Status 2026-11-20:** A0 to A6 are done and the automated part of A7 passed. Results, fixes and open decisions:
`10-staging-pilot-results.md`. The table below is the plan as written before the work.

## Changes made to this plan on review

- Added step A0: the staging settings, prepared and checked offline.
- A5 must use the restricted login. With the Windows account the check correctly fails, because that account is a
  SQL Server administrator.
- Removed "A3 is optional". Without the certificate the website cannot connect at all, because certificate checking
  stays on. The certificate is required for the pilot.
- The pilot needs one web password for an administrator (step A7).
- Corrected: the copy is used by the two Access files on this PC's Desktop. Close them before A3.

## Steps

| Step | What | Changes DEV-PC? | Interruption | Ready? | Needs approval? |
|---|---|---|---|---|---|
| A0 | Staging settings prepared: `backend\.env.staging.example`, `tools\prod-check\prodcheck.env` | No | None | **Done** | No |
| A1 | Backup with checksums, then verify (`backup\1-full-backup-with-checksum.sql`) | One new backup file, about 1.7 GB | None | Script ready, never run | **Yes** |
| A2 | Restore test as `McLabor_RestoreTest`, check it, remove it (`backup\2-...`, `3-...`) | A temporary database, about 2.3 GB | None | Scripts ready, never run | **Yes** |
| A3 | Certificate for `DEV-PC` (`proposed-certificate-setup.ps1`) | Certificate, one SQL Server setting, **restart of DEV-PC's SQL Server** | About 1 minute, this PC only | Script ready, never run | **Yes** |
| A4 | Read-only login `mclabor_web_read` (`proposed-grants.sql`) | One login, one role, 288 column permissions | None | Script ready, never run | **Yes** |
| A5 | Connection check with the new login (`check_readonly.py`) | No | None | Ready; passes only after A3 and A4 | No (reads no records) |
| A6 | Switch the website to STAGING and run the live search test (`python -m app.livecheck`) | No | Demo website is replaced by staging while this runs | Ready | **Yes** - first time the website reads real records |
| A7 | Read-only pilot (below) | No | None | Ready | **Yes** |

Order: A1, A2, then A3 and A4 in either order, then A5, A6, A7.

## The read-only pilot (A7)

Purpose: find out whether the website shows the same people, customers and jobs as Access, and how fast.

Set-up (after A5 passes):

1. Copy `backend\.env.staging.example` to `backend\.env`. Fill in a new `JWT_SECRET` and the login's password.
2. Restart the website's backend. The page header must show the amber **STAGING - test copy** label.
3. Give one administrator a web password:
   `backend\.venv\Scripts\python.exe -m app.webauth set-password INITIALS` (their initials from the staff table).
4. Sign in. Open **System status**: environment STAGING, only server allowed `DEV-PC\SQLEXPRESS`, changes disabled.

What to compare, with the Access file on this PC's Desktop open beside it (it uses the same copy):

| Check | In the website | In Access | Same? |
|---|---|---|---|
| Number of employees | Dashboard | Employee list count | |
| Number of customers / jobs | Dashboard | Lists | |
| 5 employees by name | Employees > search | Find the same people | |
| One trade in one state, e.g. electricians in MA | AI search | Same filter | |
| 3 customers by name, with their job count | Customers | Same | |
| 3 jobs: site, customer, start date, crew size | Jobs | Same | |
| Years in trade, will-travel, site city/state on 5 records | Record pages | Same records | |
| Date of birth, SSN, bank details | Must **not** appear anywhere | - | |
| Any Save / Create button | Must answer "Read-only mode" | - | |

Record: the slowest search and how long it took (the live search test prints timings).

Known before starting:

- Data is as of 2026-11-13. Compare with the Access file that uses the same copy, not with live Access.
- Years in trade, will-travel and site city/state come from other tables in the real database. This pilot is the
  first real test of that mapping.
- Search now filters and pages inside the database (`docs/search-performance.md`). It is fast on synthetic data of the real
  size, but has never run on SQL Server; step A6 gives the first real timings. If name or note searches are slow
  there, `tools\prod-check\list-indexes.sql` (read-only) shows which indexes exist before any are proposed.

Ending the pilot: rename `backend\.env` to `backend\.env.off`, restart the backend, and the website is back on demo.

## If something goes wrong on the copy

The copy can be removed and restored again from `C:\ZZZ-SQL\McLabor_2026_11_13_170000.80.bak`. That is a restore
over the copy and needs approval like any other change.

## What Plan A does not prove

Anything about LIVE-HOST: whether it holds the live database, its certificate, its administrators, its backups, or
whether DEV-PC can reach it. That is Plan B (`09-plan-connect-live-database.md`).
