# 10. Staging pilot results (2026-11-20)

The website ran against the **restored copy** of McLabor on `DEV-PC\SQLEXPRESS` (data as of 2026-11-13), read-only,
with the restricted login `mclabor_web_read`. LIVE-HOST was not contacted. Reports with every line:
`tools\prod-check\reports\staging-pilot-*.txt` and `livecheck-staging-*.txt` (counts and timings only, no records).

## How staging is run

- `backend\.env` selects `DATA_SOURCE=staging`. It holds **no database password**.
- The password is in `%LOCALAPPDATA%\MCLabor\staging-mclabor_web_read.dpapi`, encrypted for the Windows account
  `<windows-user>` on this PC. `tools\staging\run-in-staging.ps1` loads it into the one process it starts.
- Backend: `powershell -File tools\staging\run-in-staging.ps1 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4 --no-access-log`
- Frontend: `npx next dev -p 3000 -H 127.0.0.1`. Both listen on this PC only (127.0.0.1).
- The question parser is the built-in one. No outside AI service is called in staging.
- Back to demo: rename `backend\.env` to `backend\.env.off`, restart the backend the old way.

## Results

| Area | Result |
|---|---|
| Website compared with direct database counts | 17 of 17 equal (employees 176,215 non-duplicates, customers 106,828, jobs 15,748, tracking 192,225, and filters by trade, status, state, city, week, customer, employee) |
| Filtering, sorting, paging | Pass. 50 + 50 different rows on pages 1 and 2, 200 per page works, 201 refused, results past 10,000 refused with a message |
| Opening records | 192 employees, 160 customers, 161 jobs opened, 0 failures |
| Plain-English questions | 9 of 9 understood and answered |
| Restricted fields | Absent from records. SQL Server itself refuses SSN, bank account, date of birth, staff password and `SELECT *` |
| Changes | Website answers 423 to 8 kinds of change. SQL Server refuses UPDATE, DELETE and INSERT for the login. Row counts unchanged |

### Speed, one person

| Search | Time |
|---|---|
| Lists with a filter (trade, status, state, city, ZIP), jobs, tracking week | 0.05 to 0.9 s |
| First page of all employees / customers | 0.8 s / 0.5 s |
| Opening one record | 0.03 s |
| Word search in employees (last name / first + last name) | 1.4 s / 2.4 s |
| Word search in customers (name, phone digits) | 2.7 to 2.9 s |
| Dashboard | 2.6 s |
| "licensed electricians" with filter counts | 2.4 s |

### Speed, 35 people at once (a search every 2 to 6 seconds each - a stress pace)

210 searches, all answered. Typical 1.9 s, 95% within 13 s, slowest 17 s. Filtered lists stay at 0.2 to 2 s.
**Word searches are the problem**: 5 to 9 s typical, up to 17 s (the limit is 20 s). SQL Server Express uses at most
4 processor cores and each word search reads every row of a wide table.

## Problems found and fixed during the pilot

| Problem (only visible with real data) | Fix |
|---|---|
| "Newest first" failed: SQL Server refuses an ORDER BY naming a column twice | `search._unique_order` |
| Every job list failed: crew size is NULL on 15,746 of 15,748 jobs; hours and rates NULL on thousands of tracking rows | Response models show NULL numbers as 0, NULL entry dates as "-" |
| Drop-down lists failed: blank labels in lookup tables | Blank entries skipped |
| "in MA" was also read as a city: the real city list contains "Ma", "NY", "St", "P" | City names under 3 letters ignored |
| Nobody could use the website: `Profile` is 0 for all 82 staff, and the permission table lists 1,126 Access forms and buttons, not website pages | Website administrators are named in `WEB_ADMINS` in `backend\.env` (see below) |
| Tests read the real `backend\.env` | Tests ignore it (`MCLABOR_ENV_FILE=none`) |

128 automated tests pass.

## Follow-up (2026-11-23)

Findings 1 to 3 below were worked on without switching the website out of DEMO (`tools\staging\run-readonly.ps1`):

- Finding 1 (empty contact details): cause established as missing source data in the copy, not mapping or
  permissions - `11-employee-contact-findings.md`.
- Finding 2 (who may use the website): `WEB_USERS` (look-up only) added next to `WEB_ADMINS`; people on neither list
  are refused at sign-in and at the gateway - `docs/access-without-login.md`.
- Finding 3 (word-search speed): the cost was the lookup sub-selects inside the search's OR, fixed in the
  application; filter counts now take one pass; page 2 and repeated searches are served from remembered ids -
  `docs/search-performance.md`, with before/after timings.
- What is still needed before production: `12-requirements-before-production.md`.

## Findings that need a decision

1. **Employee contact details are empty in this copy.** City, state, ZIP, street, mobile phone, home phone and e-mail
   are empty for all 178,993 employees (checked with the administrator account too; customers are filled in normally).
   Either this copy was cleaned before it was handed over, or the live database keeps these elsewhere. Until that is
   known, "electricians in MA" finds nobody. Ask whoever made the backup on LIVE-HOST.
2. **Who may use the website, and what may each person see?** Access permissions cannot be reused. Today only the
   people in `WEB_ADMINS` get in, and they see everything the login can read.
3. **Word-search speed for 30+ people.** Options, cheapest first: search names with "starts with" by default; evaluate
   the keyword conditions once instead of twice per row; the indexes in `docs/search-performance.md`; a full-text
   index. The last two change the database and need approval.
4. **The question parser needs tuning on real wording.** It answered all 9 questions, but 3 were read loosely:
   "jobs in Hartford starting this month" also became status "Pending" and a customer named Hartford; "customers
   in MA with active jobs" also filtered the customer's own status; "general contractors" matches no real customer
   type label.
5. Rarely filled in the real data: years in trade (2%), will-travel (never "yes"), employee status (25%),
   license expiry date (1%). Filters on these work but find few people.

## Signing in to staging

In your own PowerShell window (it asks you to type a new web password twice; 12 or more characters):

```
cd $env:USERPROFILE\Documents\MC-Labor-AI-Automation
powershell -ExecutionPolicy Bypass -File tools\staging\add-pilot-user.ps1 XX
```

`XX` = your initials as they are in the Access staff list. Then restart the backend and open http://localhost:3000.
