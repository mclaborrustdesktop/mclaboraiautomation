# User access plan: a maximum of 20 authorized website users (revised 2026-11-23)

Decision: the website supports **at most 20 authorized employees** (revised down from 30). Sign-in by Cloudflare
Access (no website login screen), roles in the website (`WEB_ADMINS` everything, `WEB_USERS` look-up only), the
production budget target of 200 USD per month, East US as the region.

## 1. How access is granted and removed (no rebuild, no redeploy, no restart)

| Layer | Who manages it | What it decides |
|---|---|---|
| **Cloudflare Access policy** on `app.<domain>` | company IT in the Zero Trust dashboard | who can reach the site at all: an identity-provider group "MC Labor Web" (Microsoft 365 / Google) or a Cloudflare List of e-mails; changed in the dashboard, effective at once |
| **Website roles** in the website's own sign-in store | website administrators, on the Users page or with `python -m app.webauth access-set INITIALS admin|user|none` on the server | admin / look-up only / none; stored in `web_auth_production.db`, never in the McLabor database; effective on the person's next request |
| **Bootstrap administrators** in `backend.env` (`WEB_ADMINS`) | the server administrator | the two people who can never lock themselves out; everyone else is managed above |

Why two layers: the Access policy keeps strangers (and seat consumption) out before any request reaches the
website; the website's roles decide what each named employee may do. Adding an employee is two steps, each by the
right person: IT adds them to the identity-provider group; an administrator sets the role on the Users page.
Removing only in the website already blocks every page (403) on the next request.

Guards in the website: an administrator cannot remove their own administrator access; people named in the
settings file are changed there, not on the page; an inactive staff record cannot be granted access; the 20-user
maximum is enforced; every grant records who granted it and when.

## 2. The two limits the website tracks

| Limit | Setting | Default | What happens |
|---|---|---|---|
| **Company maximum of website users** | `ACCESS_SEAT_LIMIT` / `ACCESS_SEAT_WARN` | 20 / 16 | the 21st grant is refused (409 with the reason); from the 16th on the Users page banner, the status page and the start-up log warn. Changing a role never needs a new seat |
| **Sign-in service free plan** | `ACCESS_SERVICE_LIMIT` / `ACCESS_OTHER_SEATS` | 50 / 8 | Cloudflare counts website users and the WARP users of the Access/QuickBooks PCs in one pool; the website adds `ACCESS_OTHER_SEATS` to its own count and warns within 5 of the service limit |

Numbers shown (Users page banner, `/api/users/access-summary`, status page, start-up log): authorized website
users, administrators, look-up users, people who used the site this month, seats left, sign-in service seats used.

With the revised maximum: 20 website users + up to 8 WARP users = **28 of 50** free seats, with 22 to spare. The
free plan is no longer a constraint; the 50-seat warning stays as a safety net. The `ACCESS_OTHER_SEATS` value is
set to the real number of Access/QuickBooks PCs when they are enrolled.

## 3. If the company ever needs more than 20 (or 50 seats)

Raising `ACCESS_SEAT_LIMIT` is a settings change plus a restart of the backend; nothing else in the website
changes. Beyond 50 Cloudflare seats, in order of cost: website sign-in moved to the VM (`oauth2-proxy` + Caddy
behind the same tunnel, the website's `GATEWAY_PLATFORM=proxy` mode, already built and tested) at no cost; an Azure
VPN gateway `Basic` for the Access PCs (about 27 USD) to free WARP seats; or Cloudflare's paid plan at 7 USD per
user for every user.

## 4. Launch roster (no real names in this repository)

`deploy/vm/staff-roster.example.csv` is the template (identity, role); `tools/staging/import-access-roster.py` loads
it into the store and refuses to exceed the limit. The real roster of up to 20 is filled in by the owner, kept out
of the repository, and loaded once the staff records exist in the environment's database.

## 5. Rehearsal on synthetic staging

Load the synthetic roster (10 invented staff), confirm the banner shows the count against 20, that two test
accounts behave as administrator and look-up user, that a removed account gets 403 on its next request, and that
the limit is enforced in a test with `ACCESS_SEAT_LIMIT=4` (the automated test does the same on this PC).
