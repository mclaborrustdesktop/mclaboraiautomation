# Using the website without a sign-in page (2026-11-20)

The website has three ways of letting people in. The setting is `ACCESS_MODE` in `backend\.env`.

| Mode | Sign-in page? | Where it is allowed | Who the visitor is |
|---|---|---|---|
| `open` | No | **DEMO only** (the default there) | Everyone is the demo administrator. Fake data only |
| `login` | Yes | Staging and production (the default there); demo if you set it | Initials + web password |
| `gateway` | No | Staging and production only | Whoever the company gateway signed in |

Real employee and customer records can never be opened anonymously:

- With `DATA_SOURCE=staging` or `production`, `open` is ignored and treated as `login`, **and** the backend refuses
  to start while `ACCESS_MODE=open` is in the file.
- `gateway` refuses to start without a `GATEWAY_SECRET` of 32 or more characters and without
  `GATEWAY_TRUSTED_PROXIES` (the address the gateway forwards from; default `127.0.0.1,::1`).
- Nothing about the database changes in any mode: same restricted read-only login, same 423 "Read-only mode".
- The SQL Server password, `JWT_SECRET` and `GATEWAY_SECRET` stay on the server. The browser receives none of them.

## Who may use the website with real data (reviewed 2026-11-23)

The Access permission table cannot be reused (it lists 1,126 Access forms and buttons, and the `Profile` flag is 0
for all 82 staff). Two lists in `backend\.env` decide instead. Each holds initials, `OfficeStaffID` numbers or e-mail
addresses, separated by commas:

| List | May do | May not do |
|---|---|---|
| `WEB_ADMINS` | Everything the website offers: look-ups, AI search, user management, system status | Change records (read-only mode applies to everyone) |
| `WEB_USERS` | Look-ups only: employees, customers, jobs, weekly tracking, AI search | User management, system status, any change |
| neither | Nothing. Sign-in answers 403 "not been given access" even with a correct web password; the gateway answers 403 for them too | |

This replaces the pilot arrangement in which only `WEB_ADMINS` existed and everyone on it was an administrator.
The lists are read on every request, so a change takes effect at the next backend restart, not when a sign-in
expires. Both empty = nobody can get in (the start-up log and the status page warn about it). The lists are
ignored in the demo, where the seeded accounts and their feature permissions apply.

What a `WEB_USERS` person sees is the view-only page set (`WEB_VIEW_FEATURES` in `security.py`). Whether pay and
bill rates may appear for them is still an open decision; today the list and record pages show them to everyone who
can open the page.

### Managing access at runtime (2026-11-23)

With real data, administrators grant or remove website access **in the website**: the Users page (Access column:
Admin / Look-up only / No access) or `python -m app.webauth access-set INITIALS admin|user|none` on the server. The
role is written to the website's own sign-in file, never to the McLabor database, and takes effect on the person's
next request: no settings change, no restart, no redeploy. `WEB_ADMINS` / `WEB_USERS` in the settings file remain
the bootstrap administrators, changed only on the server. The Users page and the status page show how many people
are authorized and how many used the site this month; `ACCESS_SEAT_LIMIT` (20, the company maximum) refuses a further
grant and `ACCESS_SEAT_WARN` (16) turns the warning on; `ACCESS_OTHER_SEATS` (the Access PCs' WARP users) is added
when the sign-in service's own 50-seat plan is checked. Plan: `docs/cloud/09-user-access-plan.md`.

### Managing the bootstrap lists in the settings file

```
powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -List
powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -Initials XX -Role user
powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -Initials XX -Role admin -SetPassword
powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -Initials XX -Role none
```

The script edits the `WEB_ADMINS` / `WEB_USERS` lines of `backend\.env` (or the file given with `-EnvFile`, for
example `backend\.env.off` while the website is in DEMO), and with `-SetPassword` also sets the person's web
password for login mode. The McLabor database is not touched. Restart the backend afterwards. Administrators can see
the result on the Users page: each person shows **Admin**, **Look-up only** or **No website access**.

### Preparing gateway access

`deploy\gateway\` holds the reverse-proxy and sign-in templates (Caddy + oauth2-proxy, or Cloudflare Access) and a
README with the exact header rules the backend expects. `tools\gateway-check.ps1` is a read-only check of this PC
(listening addresses, firewall rules, the settings file, the browser's API address, and with `-Probe` two requests
that must be refused). Neither switches anything on.

## DEMO: active now

Open http://localhost:3000 and the dashboard appears. There is no sign-in page, no "Sign out" and no "Change
password". `/login` forwards to the dashboard. To get the sign-in page back in the demo, start the backend with
`ACCESS_MODE=login`.

## STAGING and PRODUCTION: prepared, NOT active

Today both still use the sign-in page (`login`). Nothing below is switched on.

### What "gateway" means

```
staff PC --(company VPN / Zero Trust client)--> gateway --(adds 2 headers)--> website backend on 127.0.0.1
```

1. The website keeps listening on this computer only (127.0.0.1), as it does now. It is not reachable from the
   office network or the internet directly.
2. A **gateway** in front of it is the only way in. It signs each person in with their company account
   (Microsoft 365 / Google) and only lets approved people through.
3. For every request it forwards, the gateway adds:
   - `X-Gateway-Secret`: a long random value only the gateway and the website know;
   - the person's e-mail address (`X-Auth-Request-Email`, or `Cf-Access-Authenticated-User-Email` for Cloudflare).
4. The website refuses a request that did not arrive from a trusted gateway address (401), a request without the
   right secret (401), a person whose e-mail is not an **active** record in the office staff table (403), and a
   person who is on neither `WEB_ADMINS` nor `WEB_USERS` (403). Which list they are on decides what they may see.

Products that can be the gateway: Cloudflare Zero Trust (Access + Tunnel), Tailscale or WireGuard VPN with
oauth2-proxy, Microsoft Entra Application Proxy. Which one is a company decision (cost, who administers it).

### Settings to add when the gateway exists (do not add before)

```
ACCESS_MODE=gateway
GATEWAY_SECRET=<48+ random characters; the same value is configured in the gateway>
GATEWAY_EMAIL_HEADER=Cf-Access-Authenticated-User-Email     (or leave out for oauth2-proxy)
GATEWAY_TRUSTED_PROXIES=127.0.0.1,::1                        (where the gateway forwards from; add its address if it runs elsewhere)
WEB_ADMINS=person1@mclabor.com
WEB_USERS=person2@mclabor.com,person3@mclabor.com
```

### Checklist before switching a real-data environment to `gateway`

| # | Check | Why |
|---|---|---|
| 1 | Gateway chosen, set up, and limited to named company accounts with two-step sign-in | The gateway becomes the sign-in |
| 2 | Backend and frontend listen on 127.0.0.1 only; firewall has no rule opening ports 3000 / 8000 | Nobody can go around the gateway |
| 3 | The gateway **removes** any `X-Gateway-Secret` / e-mail header sent by the visitor before adding its own, and `GATEWAY_TRUSTED_PROXIES` names only the gateway's address | Stops forged headers, and stops anyone sending them straight to the backend |
| 4 | The browser reaches the API through the gateway (same address as the site, e.g. `/api`), and `NEXT_PUBLIC_API_URL` is set to that | Today the browser calls `localhost:8000` directly, which only works on this PC |
| 5 | Staff e-mail addresses in the office staff table are correct for everyone who needs access | People are matched by e-mail |
| 6 | From outside the VPN the site does not open; with a non-approved account it answers 403 | Proof it works |
| 7 | Owner's approval | It changes how real records are reached |

Until all seven are done, staging and production stay on the sign-in page.

## Tested

`backend\tests\test_access_modes.py`: demo opens every page and the AI search with no sign-in; real data cannot be
`open`; `gateway` refuses anonymous requests, sign-in tokens, a forged e-mail without the secret, a wrong secret, an
unknown person, the right secret from an untrusted address, and accepts only trusted address + secret + an active
staff e-mail on an access list; with real data a person on neither list is refused at sign-in and on every request;
`WEB_USERS` get exactly the view-only pages; the outside AI service is never used with real data without the
owner's recorded approval, and its prompt never contains staff names or customer text.
