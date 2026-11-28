# 22. Local integration with the SQL database on the office PC (2026-11-27, evening)

Owner's instruction: finish the integration with the database already accessible on the office PC; no access to the
live server; no real records to Railway without approval. Result: **the whole stack runs on the office PC against the
restored copy, with real records, password-only sign-in and the read-only login.** Nothing left the PC.

## 1. Which databases are reachable from this PC

| Database | Reachable | What it is |
|---|---|---|
| `DEV-PC\SQLEXPRESS` / `McLabor` (restored copy) | yes, Windows sign-in (administrator) and the restricted login `mclabor_web_read` | a full copy of the live database, restored 2026-11-13 18:46 from the backup taken on the live server at 17:00 that day (SQL Server 15.0.2000, 294 tables) |
| `LIVE-HOST\SQLEXPRESS` / `McLabor 20260811 Development` | no: only the Access files link to it with a saved password that is not extracted (`20`) | the development database on the live server |
| `LIVE-HOST\SQLEXPRESS` / `McLabor` (live) | no (`21`: client-performed one-time setup prepared) | the live database |

So the only usable database today is the restored copy. **It is complete but frozen at 2026-11-13 17:00**: the newest
employee entry 2026-11-13 15:27, project 16:44, assignment 16:50, staff activity 16:57; the newest week in tracking is
the week ending 2026-11-20 (entered in advance). Every week since is missing, and the dashboard's "this week" shows 0
for that reason. The same is true of every search result: correct as of 2026-11-13, two weeks old now.

## 2. Approved records available in the copy (33 approved tables, 288 columns)

| Table | Rows | | Table | Rows |
|---|---:|---|---|---:|
| tblOfficeStaffActivity | 234,466 | | tblProject (jobs) | 15,748 |
| tblTracking (weekly staffing) | 192,225 | | tblPullDownStateCities | 4,856 |
| tblCustomerContacts | 187,636 | | tblFeature | 1,126 |
| tblEmployee / tblEmployeeB | 178,993 each (176,215 non-duplicates, 219 "Active") | | tblCustomerNotes | 214 |
| tblCustomer | 106,828 | | tblOfficeStaff | 82 (16 active) |
| tblEmployeeLicenses | 55,623 | | 20 lookup tables | 2 to 65 each |
| tblOfficeStaffPermission | 27,520 | | **total** | **about 1.21 million rows** |
| tblEmployeeNotes | 25,226 | | | |

Many customer rows have no name (they sort first in the Customers list); that is how the office data is.

## 3. What was connected and how (existing files only)

- **Backend**: `backend\.env` = the pilot file of 2026-11-20 (`.env.off`, `DATA_SOURCE=staging`, server
  `DEV-PC\SQLEXPRESS`, login `mclabor_web_read`, encryption on, certificate verified, writes off) plus the password-only
  settings decided on 2026-11-27: `ACCESS_MODE=passcode`, the staging password hash, `SITE_DEFAULT_USER=RMV` (the
  owner's own active staff record, found by e-mail), `WEB_ADMINS=RMV`. Started with `tools\staging\run-in-staging.ps1`
  (password from the DPAPI store, 127.0.0.1:8000 only).
- **Frontend**: `npx next dev -p 3000 -H 127.0.0.1` with `.env.local` = `NEXT_PUBLIC_API_URL=` (empty) and
  `BACKEND_INTERNAL_URL=http://127.0.0.1:8000`: the browser calls `/api` on the site itself and the Next.js route
  handler forwards it, exactly as on Railway. (Pointing the browser straight at port 8000 is blocked by the site's own
  `connect-src 'self'` policy: that was the blank page at first.)
- **Sync agent**: `app.syncagent run --target-url sqlite:///...local-mirror-staging.db --bootstrap --full` with the
  same staging settings: source = the restored copy through `mclabor_web_read`, target = a SQLite mirror file on this
  PC. Nothing to Railway.

## 4. Results

| Check | Result |
|---|---|
| Sign-in | password-only page ("Access Password"), one field; wrong answers recorded; session as RMV |
| Dashboard | 178,993 employees (5,179 active, 85 available), 106,828 customers (1,694 active), 15,748 jobs (7,178 active), 16 staff accounts; 5.7 s |
| Lists | employees 176,215 (0.9 s), word search "electrician" 74,654 (1.0 s); customers 106,828 (0.8 s), "construction" 23,997 (1.3 s); jobs 15,748 (0.4 s); tracking 192,225 (0.6 s); 50 per page |
| AI search (built-in parser, no outside service) | "licensed electricians in Texas" → 21,611 matches with trade / qualification / status facets (2.0 s); "jobs being manned" → 7; "customers in Houston on hold" → 0 (understood, nothing matches) |
| Weekly tracking | week ending 2026-11-13: 259 assignments, 232 workers, 82 customers, shown with pay / bill / grade |
| Opening a record | 0.1 s; 52 fields; `EmDOB` and `USCitizen` appear as empty fields (never requested from SQL Server: unmapped), SSN / bank / I-9 / W-4 / race / sex / staff passwords absent |
| Changes | POST / PUT / DELETE answer 423 (read-only); the login itself cannot write (`21`, rehearsal) |
| Sync agent | reads every approved table through the restricted login and writes the mirror; about 80 rows/s into SQLite on this PC (64,000 rows after 13 minutes; a full first copy of 1.21 M rows takes about 4 hours at that rate); left running |

Two small code fixes came out of this: the web-sign-in database start-up now tolerates SQLite's "table already
exists" when two workers start together (it caught `IntegrityError`/`ProgrammingError` only), and the development
server's Content-Security-Policy allows `'unsafe-eval'` for its hot-reload runtime in development only.

## 5. Is the integration ready?

- **Code and configuration: ready.** Backend, frontend, sign-in, searches, restricted fields and the agent all work on
  real records on this PC.
- **Data: not current.** The copy is two weeks old and cannot refresh itself: the office PC has no login to the live
  database. Fresh data needs the client-performed one-time setup of `21` (read-only login + certificate on the live
  server, about 15 minutes of their administrator's time), after which the same agent reads the live database twice a day.
- **Cloud: not loaded.** The Railway production project does not exist and no real record has been sent anywhere
  (owner's approvals of `19` section D / `docs/cloud/20` still open).

To stop the local test: close the backend and frontend processes and rename `backend\.env` back to `.env.off`
(the website returns to DEMO). The `.env.local` of the frontend was backed up as `.env.local.bak-2026-11-27`.
