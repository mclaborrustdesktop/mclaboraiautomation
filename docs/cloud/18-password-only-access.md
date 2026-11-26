# 18. Password-only entrance (ACCESS_MODE=passcode) and the second access boundary

Requested 2026-11-26: the website asks for ONE password, no user name, no e-mail, no one-time PIN, no registration.
Implemented in `backend/app/sitepass.py`, `security.py` (`resolve_site_identity`, `_site_user`), `routers/auth.py`
(`POST /api/auth/unlock`, `GET /api/auth/unlock-log`) and the sign-in page (`PasscodeForm`). Tests:
`backend/tests/test_passcode.py`.

## 1. How it works

| Item | Behaviour |
|---|---|
| Screen | A clean MC Labor page with a single "Access password" field and an "Enter" button, before the search dashboard |
| Storage | The password exists only as a PBKDF2-SHA256 hash (120,000 rounds, random salt) in the hosting service's variable `SITE_PASSWORD_HASH`. The hash is produced on a PC with `python -m app.webauth site-password` (hidden prompt, prints the hash only). The password is never in the code, the repository, a file or a log; the server never echoes it, and the audit rows never contain it |
| Check | `POST /api/auth/unlock {password}`; a wrong password answers 401 "Incorrect password." and nothing more |
| Brute force | per address: 5 failures within 15 minutes = that address is refused for 15 minutes, doubling with every further failure (30, 60, 120, 240 min); for everyone: 50 failures from any addresses within 15 minutes = the site is refused for 15 minutes (a distributed guess). Locked = 429 with `Retry-After`; the right password is refused too while locked. The hash check itself costs about 0.1 s, which caps guessing speed before the counters do. Counters live in the sign-in store (PostgreSQL), shared by all workers and replicas |
| Session | An unlock issues a signed token (`mode: site`, environment-bound) valid `SITE_SESSION_MINUTES` (default 480 = 8 h, maximum 12 h); then the password screen returns. A token from the old user-name sign-in is not accepted in this mode, and the old `/api/auth/login` answers 403 |
| Search-only | unchanged: every Add/Edit/Delete stays refused (423) for everyone |
| Audit | every attempt is recorded: time, address, identity (see 2), client software, outcome (`ok`, `wrong`, `locked:address`, `locked:everyone`, `no-identity`). Administrators: `GET /api/auth/unlock-log`; the system status page shows the 24-hour summary |
| Rotation | `SITE_PASSWORD_LABEL` names the secret in use. The set-up password is labelled `initial`; **production refuses to start** with the labels `initial`, `staging`, `test`, `demo` or none, so a new, unique production secret must be generated and labelled (e.g. `production-2026-12`) before real records exist. Rotation = new hash + new label in the hosting service, redeploy (two minutes); every open session ends at its own expiry |

## 2. Who is behind the password: the second boundary (no e-mail sign-in)

One shared password is deliberately not the only control for confidential employee records. The site password is
the **knowledge** factor; the second boundary is the **possession** factor and is what makes people individual:

**Cloudflare Access with per-employee client certificates (mutual TLS).** Each of the up to 20 employees receives
a personal certificate (a `.p12` file installed once on their office PC or phone) issued from a company certificate
authority that is uploaded to Cloudflare Zero Trust. The Access policy on `search.<domain>` is "valid client
certificate from the MC Labor CA" with the list of allowed certificate common names (one per employee, e.g.
`ARI`, `JCH`). Nobody without a certificate even sees the password screen; no e-mail, no PIN, no registration.

What that gives, and how the website uses it:
- **Individual control**: an employee is added by issuing a certificate and adding its common name to the policy;
  removed by deleting the name from the policy (immediate, no need to revoke the certificate). The website's own
  roster (WEB_ADMINS/WEB_USERS and the Users page, 20 seats) still decides who may *use* the site: the certificate's
  common name is matched to the staff record's initials (or e-mail) by `resolve_site_identity`.
- **Individual audit**: Cloudflare logs every request with the certificate identity; the website records every
  unlock with `cloudflare:<name>` and binds the session to that identity (a session cannot be reused by another
  certificate holder). The identity shows in the unlock log and in the backend's access log.
- **The Railway address is not a way around it**: in this mode the backend requires the verified Cloudflare token on
  every request (`_site_user` checks the identity on each call), and the Railway-generated domain is deleted once
  the custom hostname works (`17-security-handover.md`, section 7).

Alternatives considered and why not: office IP allow-list only (one boundary, no individual accountability, breaks
for remote staff); Cloudflare WARP device enrollment (needs an identity-provider or e-mail PIN login to enrol).

Until Cloudflare is in front (staging today), `SITE_DEFAULT_USER` names the staff record everyone acts as (a
synthetic administrator on staging). Production refuses `passcode` mode without either a Cloudflare identity or a
default user, and the owner's choice for production is the certificate boundary above.

## 3. Operating it

1. Generate: on any PC with the backend's virtual environment, `python -m app.webauth site-password`; copy the printed
   `SITE_PASSWORD_HASH=...` line into Railway > backend > Variables (seal it). Set `SITE_PASSWORD_LABEL`.
2. Switch on: `ACCESS_MODE=passcode`, `SITE_DEFAULT_USER=<initials>` (until Cloudflare), `SITE_SESSION_MINUTES=480`.
   Optional tuning: `SITE_LOCK_FAILURES`, `SITE_LOCK_MINUTES`, `SITE_GLOBAL_LOCK_FAILURES`.
3. Hand the password to the employees in person or by the company's password safe; never by e-mail or chat.
4. Watch: the system status page's `site_unlock` block and `GET /api/auth/unlock-log` (administrators). A burst of
   `locked:everyone` rows means a guessing attack: rotate the password and review the Cloudflare log.
5. Rotate every quarter and whenever an employee leaves (a shared secret is only as private as its last holder).

## 4. Staging now (2026-11-26)

Staging runs `ACCESS_MODE=passcode` with the owner's initial set-up password (label `initial`), `SITE_DEFAULT_USER=ARI`
(synthetic data). The same configuration on production is refused by design until a production secret is set.
