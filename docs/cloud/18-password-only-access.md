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
| Brute force | per address: 5 failures within 15 minutes = that address is refused for 15 minutes, doubling with every further failure (30, 60, 120, 240 min); site-wide: 50 failures from any addresses within 15 minutes puts the site under pressure for 15 minutes: attempts are refused only from addresses that have never unlocked successfully in the last 30 days, so a guessing attack from the internet cannot lock the company out (the office and the staff's known addresses keep working; a brand-new device waits 15 minutes). Locked = 429 with `Retry-After`; the right password is refused too while locked. The hash check itself costs about 0.1 s, which caps guessing speed before the counters do. Counters live in the sign-in store (PostgreSQL), shared by all workers and replicas |
| Session | An unlock issues a signed token (`mode: site`, environment-bound) valid `SITE_SESSION_MINUTES` (default 480 = 8 h, maximum 12 h); then the password screen returns. A token from the old user-name sign-in is not accepted in this mode, and the old `/api/auth/login` answers 403 |
| Search-only | unchanged: every Add/Edit/Delete stays refused (423) for everyone |
| Audit | every attempt is recorded: time, address, identity (see 2), client software, outcome (`ok`, `wrong`, `locked:address`, `locked:everyone`, `no-identity`). Administrators: `GET /api/auth/unlock-log`; the system status page shows the 24-hour summary |
| Rotation | `SITE_PASSWORD_LABEL` names the secret in use. The set-up password is labelled `initial`; **production refuses to start** with the labels `initial`, `staging`, `test`, `demo` or none, so a new, unique production secret must be generated and labelled (e.g. `production-2026-12`) before real records exist. Rotation = new hash + new label in the hosting service, redeploy (two minutes); every open session ends at its own expiry |

## 2. Who is behind the password: the second boundary (no e-mail sign-in), verified 2026-11-26

One shared password is deliberately not the only control for confidential employee records. The second boundary has
to make people individual (who may enter, who did enter) without an e-mail sign-in, and it has to be affordable.

**Correction.** The first version of this page proposed Cloudflare Access with per-employee client certificates
(mutual TLS) as a free boundary. Cloudflare's documentation states, verbatim: *"Access mTLS is available with Enterprise
and pay-as-you-go Zero Trust plans. It is not included in the Free plan."* (developers.cloudflare.com, page "Mutual TLS",
read 2026-11-26). The pay-as-you-go plan is priced per user (about 7 USD per user per month according to Cloudflare's
public plan listings as reported by several price trackers; Cloudflare's own plans page did not return the figures to
an automated read), i.e. about **140 USD per month for 20 employees**. The same page also notes that Access mTLS is
meant for *Service Auth* policies (machines), not for naming people. So that design is withdrawn.

**Options evaluated**

| Option | Individual control and audit | Monthly cost for 20 | E-mail needed | Verdict |
|---|---|---|---|---|
| A. **Approved devices** (built into the website) | yes: each device is approved by an administrator and labelled with the employee's name; revoked per device; every unlock and search is logged per device | 0 | no | **recommended** |
| B. Cloudflare Access, pay-as-you-go, mTLS or identity provider | yes | about 140 USD | mTLS no; IdP yes | too costly for the value |
| C. Cloudflare Access Free with one-time PIN | yes | 0 | **yes** | excluded by the requirement |
| D. Office IP allow-list (Cloudflare WAF rule, Free) + the password | no (everyone behind the office address looks the same; remote staff excluded) | 0 | no | useful as an extra layer, not as the boundary |
| E. Passkeys (WebAuthn) per employee, built in | yes, strongest | 0 | no | possible later; changes the single-field screen into "password, then your device's passkey" |

**Option A, built (2026-11-26): cryptographically bound devices.** A copyable browser token was rejected as the device
identity. Instead each device holds a **WebAuthn credential**: a key pair created inside the device's own
authenticator (Windows Hello with the TPM, Touch ID / Face ID, Android, or a USB security key). The private key is
non-exportable: it cannot be copied out of the browser or the operating system, so copying cookies, local storage or
the whole browser profile to another machine gives nothing. The website stores only the public key.

Every entry is: the site password, then the device signs a fresh server challenge (valid 3 minutes, bound to the
visitor's address and to a 5-minute ticket that only a correct password yields). The server verifies the signature
with the stored public key, checks the sign counter and the origin, and issues a session **bound to that device**
(revoking the device ends the session at the next request).

- Unknown device: it registers itself (the authenticator creates the key pair; the user confirms with Windows Hello or
  the device PIN) and the screen shows a **pairing code** and "waiting for an administrator's approval". Nothing is
  readable in that state.
- An administrator opens the Users page, sees the pending device (code, time, address, browser), chooses the employee
  and a label, and approves it. Or rejects it. Approved devices can be revoked in one click, and a revoked device
  cannot be re-approved (the employee registers again, which is a new key).
- Limits: `SITE_DEVICE_LIMIT` (default 40 = 20 employees with up to two devices).
- First device ever: the owner enters the one-time `SITE_DEVICE_BOOTSTRAP_CODE` (a sealed variable) on the waiting
  screen; it approves that single device as `SITE_DEFAULT_USER` while no approved device exists, and never again.
- Audit: the unlock log records `password-ok`, `device-registered`, `device-pending`, `device-approved-by:<admin>`,
  `device-revoked-by:<admin>`, `device-bad-signature`, `device-unknown`, and every successful entry as
  `device:<id>:<label>` with the address and the browser. Each employee is therefore individually identified by the
  device(s) approved in their name, without any e-mail.

Implementation: `backend/app/devices.py` (py_webauthn), the `/api/auth/device/*` and `/api/auth/devices*` routes in
`routers/auth.py`, `frontend/src/lib/webauthn.ts`, the device step in the sign-in page, `components/DevicesPanel.tsx`
on the Users page; tests `backend/tests/test_devices.py` with a software authenticator that produces real signatures.

**Limitations to know**
- Credentials are bound to the website's host name (`WEBAUTHN_RP_ID`). When the site moves from the Railway address
  to `search.<domain>`, every device registers again (one approval each). Set the final host before rolling devices out.
- The device needs a platform authenticator: Windows 10/11 with Windows Hello (PIN at least), macOS/iOS with Touch ID
  or Face ID, Android 9+, or a security key. Office PCs without Windows Hello set up are prompted to set a PIN once.
- A device is the browser's authenticator, not the PC: Chrome and Edge on the same Windows PC share Windows Hello
  (one device), Firefox on the same PC is another registration.
- The approved-device check runs on every request (one small query); the session itself still expires after
  `SITE_SESSION_MINUTES`.
- Automated verification: the software authenticator in the tests exercises the exact server code path; the browser
  prompt itself (Windows Hello dialog) is verified by hand on staging.

Settings: `SITE_DEVICE_APPROVAL=true`, `WEBAUTHN_RP_ID=<host>`, `WEBAUTHN_ORIGIN=https://<host>`, `SITE_DEVICE_LIMIT`,
`SITE_DEVICE_BOOTSTRAP_CODE` (one-time, sealed, then deleted).

**Decision taken (owner, 2026-11-26)**: option A, built and tested on staging; Cloudflare postponed.

Until the chosen boundary exists, `SITE_DEFAULT_USER` names the staff record everyone acts as (staging today); production
refuses `passcode` mode without a configured identity source.

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
