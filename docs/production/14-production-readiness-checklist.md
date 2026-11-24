# 14. Production readiness checklist (2026-11-23)

One page, one line per item, with where it stands today. "Done" means done and tested on this PC; "needs a person"
means a decision, an approval or a hands-on step that the code cannot replace. Details are in the numbered
documents in this folder and in `docs/access-without-login.md`, `docs/search-performance.md`, `docs/environments.md`.

## A. The live database

| # | Item | Status |
|---|---|---|
| A1 | Which server and database the office uses every day, written down from a staff PC (Linked Table Manager) | needs a person (`07`, `12`) |
| A2 | Owner's written statement naming the live database | needs the owner |
| A3 | SQL Server administrator for that server identified | needs a person (`02`) |
| A4 | Proven backup with a restore test on that server | scripts ready, never run; needs approval (`01`) |
| A5 | SQL Server update (15.0.2000 has never been patched) | recommended; needs approval and 5-20 min downtime (`03`) |
| A6 | Certificate installed on the live server, named after it | rehearsed on the copy; needs approval (`04`) |
| A7 | Restricted read-only login `mclabor_web_read` on the live server (33 tables, 288 columns, no SSN/bank/DOB) | rehearsed on the copy; needs approval (`05`) |
| A8 | Connection check from the web PC ends "READ-ONLY CONNECTION VERIFIED" | tool ready (`check_readonly.py`) |
| A9 | Firewall: the live server reachable from the web PC on the SQL port, nothing else opened | unknown; needs the administrator |
| A10 | Employee contact columns: found where the Access application keeps them | needs the administrator (`13`); website correct meanwhile |

## B. Staff and permissions

| # | Item | Status |
|---|---|---|
| B1 | List of staff who may use the website, and who is an administrator | needs the owner; entered with `tools\staging\manage-web-access.ps1` |
| B2 | `WEB_ADMINS` (everything) and `WEB_USERS` (look-up only) enforced at sign-in, at the gateway and on every request | done, tested |
| B3 | Staff e-mail addresses correct in `tblOfficeStaff` (gateway matches by e-mail) | needs a person |
| B4 | Decision: may pay and bill rates be shown, and to whom | needs the owner (today: everyone who can open the page) |
| B5 | Web passwords (login mode) set by an administrator, 12+ characters, lockout after 5 attempts | done; or none at all with a gateway |
| B6 | Users page shows each person's website access (admin / look-up only / none) | done |

## C. Secure deployment

| # | Item | Status |
|---|---|---|
| C1 | Backend and frontend listen on 127.0.0.1 only; no firewall rule opens 8000 / 3000 | done on this PC; `tools\gateway-check.ps1` verifies |
| C2 | Company gateway (VPN or Zero Trust) with two-step sign-in in front of the site | templates prepared (`deploy\gateway`); product choice needs the company |
| C3 | Gateway header rules: strips visitor headers, adds the shared secret, named in `GATEWAY_TRUSTED_PROXIES` | done in the backend; proxy template written; tested with forged headers |
| C4 | HTTPS between staff PCs and the proxy | part of the gateway set-up |
| C5 | Frontend built (`npm run build`) and served with `next start`, `NEXT_PUBLIC_API_URL` empty behind the proxy | build passes; switch at deployment |
| C6 | Secrets (`JWT_SECRET`, `GATEWAY_SECRET`, SQL password) in the environment or the protected store, never in files that are copied | done for staging (DPAPI store); repeat for production |
| C7 | No outside AI service with real data unless the owner approves in writing (`CLAUDE_REAL_DATA_APPROVAL`) | done, enforced at start-up |
| C8 | Hosting for 30+ users: 4 backend processes, 8 searches at once each, 20 s statement limit | done; load-test results in `docs/search-performance.md` |
| C9 | Who restarts the website, where the logs are, who is called when it is down | needs the company |
| C10 | The web PC itself: Windows updates, local administrator accounts, physical access | needs the company |

## D. Backups

| # | Item | Status |
|---|---|---|
| D1 | Full backup with checksum of the live database, restore-tested, copy kept off the server | scripts ready (`backup\`); needs approval |
| D2 | A backup routine (daily) and someone who checks it ran | needs the company |
| D3 | `backend\web_auth_production.db` (web passwords) and `backend\.env` included in the web PC's backup | needs the company |
| D4 | A backup immediately before the first write-enabled day (if writes are ever approved) | later |

## E. Before Add / Edit of real records

| # | Item | Status |
|---|---|---|
| E1 | Owner's written approval naming environment, date and scope | needs the owner (`12` B1) |
| E2 | A second SQL login with INSERT/UPDATE on approved columns only; no DELETE on the master tables | not written; needs approval |
| E3 | Write mapping for years in trade, will-travel, site city/state | not built (`12` B4) |
| E4 | Per-column audit stamps (`<Column>UserName`, `<Column>Timestamp`) filled like Access does | not built (`12` B5) |
| E5 | Lookup validation against real lookup tables; duplicate rule confirmed with the office | partly (`duplicates.py`); needs review |
| E6 | Rehearsal on the restored copy with writes on, every form, compared with Access | later |
| E7 | Access users informed; go live one screen at a time, notes first | later |

## F. Performance

| # | Item | Status |
|---|---|---|
| F1 | Word searches on employees halved; filter counts one pass; page 2 from memory | done, proven identical (`search-performance.md`) |
| F2 | Load tests with 35 and 60 users on the copy | done; results in `search-performance.md` |
| F3 | Customer word searches (1.6 to 3.2 s): full-text index or indexes | proposals written (`proposed-fulltext.sql`, `proposed-indexes.sql`); full-text is NOT installed on the copy's Express instance; needs approval |
| F4 | Load test again after any index change | later |

## What this means for "everyday use"

Staff could use the website today for look-ups against the **restored copy** (staging), on this PC, through the
sign-in page, with the people on the access lists. Everyday use against the **live** database needs A1-A9 (the
live server has never been touched), B1 and B3 (who gets in), C2-C4 (how they reach it from their desks) and D1-D2
(a backup that is known to work). Everything in E is only for Add/Edit and can wait.
