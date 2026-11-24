# 15. The live database, and the production read-only connection (2026-11-23)

## A. Which database do the office staff use?

Checked read-only from DEV-PC. No sign-in to any server, no record read, nothing changed.

### Evidence from this PC's copies of the Access application

`tools\prod-check\inspect-access-links.ps1` reads an Access file as bytes and lists the SQL Server link strings
(server, database and driver only; passwords masked). All 11 copies on this PC:

| Access file (version, date) | Links to | Times |
|---|---|---|
| `MLS 4-10-34.accdb` (2022-09) | **<live-host-ip> / McLabor** | 21 |
| `2025 01-11 MLS 5-22-4.accdb` (2025-01) | **<live-host-ip> / McLabor** | 30 |
| `2025 04-18 MLS 5-26-2.accdb` (2025-04) | **<live-host-ip> / McLabor** | 37 |
| `Hold\Database.mdb` (2025-04) | <live-host-ip> / McLabor 20250317 Development | 31 |
| `2025 10-23 MLS 5-32-9.accdb` and its `_Backup` (2026-01) | <live-host-ip> / McLabor 20250918 Development, and <live-host-ip> / McLabor | 33 + 5 |
| `2026 05-15 MLS 5-40-7.accdb` (2026-05) | **<live-host-ip> / McLabor** | 61 |
| `2026 11-06 MLS 5-44-0.accdb`, `Desktop\Database.mdb` (2026-11) | <live-host-ip> / McLabor 20260811 Development, and <dev-pc-ip> / McLabor (this PC's copy) | 60 + 13 |

Every release-looking version from 2022 to May 2026 points at exactly one place: server `<live-host-ip>`, database
`McLabor`, driver SQL Server Native Client 11.0, SQL login. The "Development" databases appear only in
development builds, each named by date. Only the two newest copies, made for this PC in November, were re-pointed at
the restored copy here. QuickBooks (QODBC) links appear in all of them.

### Evidence from the network (`tools\prod-check\find-live-server.ps1`)

| Check | Result |
|---|---|
| `LIVE-HOST` resolves to | <live-host-ip>, and <live-host-ip> resolves back to `Live-Host` |
| Ping | answers |
| TCP port 1433 | **open**: a SQL Server listens there (nothing was sent) |
| SQL Server Browser (UDP 1434) | no answer, as on DEV-PC: the instance uses the fixed port 1433 |
| ODBC data sources / mapped drives on DEV-PC | none |

Together with the 2026-11-13 backup header (database `McLabor` from `LIVE-HOST\SQLEXPRESS`, version 15.0.2000,
created 2022), the picture is consistent and, for the first time, specific.

**Conclusion:** the live database is `McLabor` on `LIVE-HOST\SQLEXPRESS` (<live-host-ip>, TCP 1433). DEV-PC holds a
restored copy of it. Two pieces of evidence are still missing and are the only ones that can make this proof
rather than inference:

1. **One staff PC.** Copy `tools\prod-check\staff-pc-check.ps1` to a PC where someone uses Access for real work and
   run it (`powershell -ExecutionPolicy Bypass -File staff-pc-check.ps1 > result.txt`). It finds the Access shortcut
   the person uses, follows it, and prints the SERVER/DATABASE pairs inside that file. Expected: `<live-host-ip> /
   McLabor` as the most frequent pair. Takes a minute, reads no data, prints no password.
2. **The owner's one-line statement** naming the live database. It becomes `PRODUCTION_DB_EXPECTED_SERVER_NAME`.

Optional stronger proof, if the administrator is at LIVE-HOST anyway: `list-active-sessions.sql` during office
hours shows the staff PCs connected to `McLabor`.

## B. What the live connection needs (nothing done yet on LIVE-HOST)

The Access application connects by IP address without encryption. The website connects by **name**, encrypted,
with the certificate verified, and with its own restricted login. So LIVE-HOST needs the same three things DEV-PC
got for the pilot, and DEV-PC needs one more:

| # | Step | Where | Script (prepared, not run) | Interruption | Needs |
|---|---|---|---|---|---|
| 1 | Backup with checksum + restore test | LIVE-HOST | `backup\1-...sql`, `2-...sql`, `3-...sql` | none | sysadmin on LIVE-HOST |
| 2 | Certificate named `LIVE-HOST` on the instance | LIVE-HOST, admin PowerShell | `proposed-certificate-setup-live-host.ps1` | **about 1 minute** of SQL Server restart: every Access user is disconnected (`06-access-maintenance-checklist.md`) | explicit go-ahead for the restart window |
| 3 | Export the certificate's public part | LIVE-HOST | `export-server-certificate.ps1` | none | - |
| 4 | Trust it on the web PC | DEV-PC, admin PowerShell | `trust-server-certificate.ps1 -CerFile ... -ExpectedName LIVE-HOST` | none | local administrator |
| 5 | Read-only login `mclabor_web_read` (33 tables, 288 columns) | LIVE-HOST, Management Studio | `proposed-grants-production.sql` (guarded to `LIVE-HOST\SQLEXPRESS`) | none | sysadmin; the password handed over out of band |
| 6 | Store the password on the web PC | DEV-PC | `tools\production\store-db-password.ps1` | none | - |
| 7 | Connection check | DEV-PC | `run-prodcheck-production.ps1` (uses `prodcheck.env.production`) | none | must end READ-ONLY CONNECTION VERIFIED |
| 8 | Live search test and the contact-column check, counts only | DEV-PC | `run-readonly.ps1 -EnvFile backend\.env.production -m app.livecheck`, then `..\tools\staging\contact_check.py` | none | first time real live records are read: say so when it happens |
| 9 | Website on the live database, read-only, sign-in page | DEV-PC | copy `backend\.env.production.example` to `backend\.env`, `tools\production\start-production.ps1` | DEMO stops on this PC | access lists filled in |

The SQL Server update (`03`) stays recommended before step 2 (same restart window), but it is not required for
the connection.

### Network requirements

- DEV-PC reaches LIVE-HOST on TCP 1433 already (checked). No firewall change is needed for the connection.
- The website connects as `LIVE-HOST,1433` (name + fixed port, because the Browser service does not answer) and
  expects the server to call itself `LIVE-HOST\SQLEXPRESS`. The certificate's name must be `LIVE-HOST`; connecting by
  IP would fail verification by design.
- Nothing on LIVE-HOST needs to be opened to anyone else. Staff PCs never talk to the website's backend directly.
- The website's own ports (8000, 3000) stay bound to 127.0.0.1 on DEV-PC; only the reverse proxy is reachable.

### Settings prepared on this PC

`backend\.env.production.example` (production environment, server by name and port, expected name, read-only
login, writes off, access lists, gateway lines ready, no AI key) and `tools\prod-check\prodcheck.env.production.example`.
`tools\staging\run-readonly.ps1 -EnvFile backend\.env.production` runs any of the read-only check scripts against the
live database once steps 1-7 are done, without switching the website.

## C. Security and deployment review (state on 2026-11-23)

| Area | State | Gap |
|---|---|---|
| Data access | Read-only twice over (API 423, SELECT-only guard, SQL login without write rights); restricted columns never mapped; server identity checked on every connection | none |
| Secrets | SQL password in the Windows-protected store, loaded into the backend process only; `JWT_SECRET`/`GATEWAY_SECRET` in `backend\.env` on the web PC | `backend\.env` must be excluded from any copy or sync (OneDrive!) of the project folder |
| Who gets in | `WEB_ADMINS` / `WEB_USERS` enforced at sign-in, at the gateway and on every request; e-mail or initials matched against `tblOfficeStaff` | the lists are empty until the owner names people |
| How they get in | login mode works now; gateway mode (no website sign-in screen) is coded and tested with forged headers; proxy templates written | the gateway itself is not installed (D below) |
| Outside services | No AI key with real data unless approved; nothing else leaves the PC | none |
| Exposure | Backend and frontend on 127.0.0.1 only; no inbound firewall rule; `tools\gateway-check.ps1` verifies | HTTPS and the proxy are part of D |
| Logging | uvicorn without access log (no URLs with search words in logs); application warnings only; activity table not written while read-only | decide whether an access log at the proxy is wanted (it would hold who searched when, not what for) |
| Load | 35 users: all answered, 95% within 3.5 s; 60 users: all answered, 95% within 8 s | full-text / indexes if the live server is slower than the copy |
| Operations | `start-production.ps1` checks the settings file, the password store, the build and the gateway check before starting | no Windows service yet: the website stops when the user logs off DEV-PC. A scheduled task or service is the next step once the owner decides the web PC |

## D. Company-only access with no website sign-in screen

Recommended shape, because every office PC and the web PC are on the same office network (<office-lan>/24):

```
office PC browser --HTTPS--> https://<site name> on DEV-PC (Caddy, LAN address only)
                                 |-- sign-in with the company Microsoft 365 (or Google) account, 2-step
                                 |-- /api/* -> 127.0.0.1:8000 (secret header added, visitor headers stripped)
                                 '-- /*     -> 127.0.0.1:3000
```

No VPN is needed for office PCs; staff outside the office would need the company VPN or Cloudflare Access instead.
What is prepared: `deploy\gateway\Caddyfile.example`, `oauth2-proxy.cfg.example`, the backend's gateway mode,
`tools\gateway-check.ps1`, `frontend\.env.production.example`. What is not: the two programs (Caddy, oauth2-proxy)
are not installed, no site name exists, no app registration exists in the company's Microsoft 365 or Google tenant,
and there is no HTTPS certificate for the site name.

## E. Decisions and access needed to move forward

| # | Needed from | What |
|---|---|---|
| 1 | Any staff member (5 minutes) | Run `staff-pc-check.ps1` on their PC and send back `result.txt` |
| 2 | Owner | One line: "the live database is McLabor on LIVE-HOST (<live-host-ip>)" once 1 confirms it |
| 3 | Owner | The names (initials or e-mails) for `WEB_ADMINS` and `WEB_USERS` |
| 4 | SQL Server administrator for LIVE-HOST | Run B1 (backup + restore test), then B5 (read-only login) and hand over the password out of band |
| 5 | Owner + administrator | A date and time for the one-minute SQL Server restart on LIVE-HOST for the certificate (B2), ideally together with the SQL Server update (`03`) |
| 6 | Local administrator on DEV-PC | Run B4 (trust the certificate) |
| 7 | Owner | Go-ahead for B8/B9: the first read of live records by the website, read-only, with the sign-in page |
| 8 | Company IT / owner | Microsoft 365 or Google for sign-in; a site name (e.g. `mclabor-web.local` or an internal DNS name); who registers the sign-in app and administers the proxy; whether DEV-PC is the permanent web PC |
| 9 | Administrator | Run `contact-columns-admin-check.sql` on the live database once connected (or on the copy now) - `13` |

Nothing in this document has changed LIVE-HOST, its settings, its permissions or its data.
