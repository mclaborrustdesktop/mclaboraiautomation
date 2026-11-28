# 21. Client-performed one-time setup of the live server (dedicated read-only login + verified TLS), 2026-11-27

Decision of the owner (2026-11-27, evening): the shared write-capable `mclabor` login is **not** approved for the
synchronization, and switching off certificate verification is **not** approved. The client owns the live server
(`LIVE-HOST`) and will not share administrator access, Remote Desktop or passwords. Therefore the one remaining path:
**the client's own administrator runs one prepared folder once on the live server**, and nothing from this project
ever needs their credentials. Everything in it was built from pieces already reviewed and rehearsed (`17`, `18`,
`19`, `04`); nothing was rebuilt.

## What the client receives

`tools\production\New-ClientSetupPackage.ps1` builds, on the office PC, the folder
`Desktop\MC Labor - one-time server setup\` (and a zip of it):

| File | Origin | Purpose |
|---|---|---|
| `RUN-ME.cmd` | `tools/prod-check/on-server/` | the one thing the administrator starts (right-click, Run as administrator) |
| `Setup-ReadOnlyLogin-OnServer.ps1` | `tools/prod-check/on-server/` | the one-time setup, steps below; office names filled in by the builder |
| `0-live-backup-status.sql`, `4-live-copyonly-backup-with-checksum.sql` | `tools/prod-check/backup/` | backup gate of `19`, byte for byte (hash-pinned) |
| `proposed-grants-production.sql` | `tools/prod-check/` | the read-only login of `18`, byte for byte (hash-pinned) |
| `verify-readonly-login.sql` | `tools/prod-check/` | the 11-grid verification of `17`, byte for byte (hash-pinned) |
| `certificate-setup.ps1` | `tools/prod-check/proposed-certificate-setup-live-host.ps1` | the server certificate of `04`, with the live server's name filled in |
| `transfer-key.cer` | created by the builder | PUBLIC half of the office PC's transfer key (below) |
| `README-for-the-client.txt` | `tools/prod-check/on-server/` | the non-technical instructions for the client |

No file in the folder is secret. The folder may travel by USB stick or e-mail.

## What the administrator's run does, in order (asks before every change)

1. **Identity.** Refuses to run unless the computer is `LIVE-HOST`, the instance calls itself `LIVE-HOST\SQLEXPRESS` and
   the database `McLabor` exists. Uses the administrator's own Windows sign-in; if that account is not a SQL Server
   administrator it asks for a SQL administrator login at a hidden prompt (kept in memory in that window only).
2. **Backup gate of `19` (read-only).** Runs the reviewed status script and `RESTORE VERIFYONLY` of the newest full backup.
3. **Safety backup.** No verified full backup → a COPY_ONLY full backup with checksum is required (asks; the run stops
   if declined). Verified but older than a day → recommended (asks). Reads the database only; disconnects nobody.
4. **The login.** Asks, then runs `proposed-grants-production.sql` with a generated 32-character password: login
   `mclabor_web_read` (policy on, default database McLabor, `DENY VIEW ANY DATABASE`), user, role `mclabor_web_readonly`,
   288 column `GRANT SELECT`s on the 33 approved tables, `DENY` of every write right (INSERT, UPDATE, DELETE, EXECUTE,
   ALTER, REFERENCES, CREATE *, ALTER ANY *, TAKE OWNERSHIP, BACKUP) and `DENY SELECT` on the 17 sensitive columns
   by name. Idempotent: on a re-run only the password is set anew. The three STEP 4 grids must read 288/33, 18/17, 0.
5. **Verification.** The 11 grids of `verify-readonly-login.sql` checked against the expected values of `17`, then a live
   sign-in AS the new login: `COUNT(FeatureID)` allowed; `COUNT(*)` over the whole table refused (it touches unapproved
   columns); `SSNum` refused; `SELECT *` on the staff table refused; `UPDATE`, `DELETE`, `INSERT` refused (all written
   with `WHERE 1 = 0`: zero rows even if a refusal had failed); a system table of another database refused.
   Like every login, it can still read SQL Server's own catalog views and the backup history in `msdb` (public
   defaults); these hold no business data.
6. **Certificate (needs an elevated window; asks).** `certificate-setup.ps1` (`04`, Microsoft's requirements checked
   before SQL Server is touched, automatic undo if SQL Server does not come back): SQL Server restarts for about one
   minute. The PUBLIC part is exported to `results\LIVE-HOST-sqlserver.cer`. Skipped with a note when the window is not
   elevated; the administrator can run `RUN-ME.cmd` again later for this step alone.
7. **Password hand-off without anyone reading it.** The generated password is encrypted with `Protect-CmsMessage` to
   `transfer-key.cer` → `results\mclabor_web_read.password.cms`. The private half of that key exists only in the
   Windows certificate store of the agent's account on the office PC (`Cert:\CurrentUser\My`, not exportable), so
   neither the administrator, nor e-mail, nor a USB stick can reveal the password. Fallback if encryption fails: the
   password is shown once on the server's screen for the administrator to hand over in person.

Output: `results\setup-report-<date>.md` (all grids, PASS/FAIL lines; no password, no data), the `.cer`, the `.cms`.
Exit code 0 only when every check passed. Undo (two lines, in the report and in `18`).

Rehearsed on 2026-11-27 on the office PC's restored copy (`DEV-PC\SQLEXPRESS`, same SQL Server 15.0.2000): backup gate
read, VERIFYONLY valid, login re-created, 288/33, 18/17, 0, **all 11 verification grids and all 8 live probes PASS**,
certificate already present → exported, password encrypted, decrypted on the office PC and used to sign in. The
rehearsal caught three defects in the new script (placeholder substitution, one-row grid handling, markdown header),
all fixed before the package was rebuilt. The staging login's password was restored afterwards.

## What happens on the office PC when the results come back

`tools\production\Import-ClientSetupResults.ps1 -Folder "<results>"`, as the Windows account that runs the agent:

1. decrypts the `.cms` and stores the password DPAPI in `%LOCALAPPDATA%\MCLabor\production-mclabor_web_read.dpapi`
   (the file `run-sync.ps1` reads; owner-only ACL; never displayed);
2. stores the cloud sync key for the agent (`sync-production.dpapi`) from the prepared production variables;
3. trusts the server's public certificate: in this account's Trusted Root store (Windows asks once, click Yes) or, in an
   elevated window, the computer's store. The agent then **verifies** the live server's certificate on every connection
   (`PRODUCTION_DB_ENCRYPT=true`, `PRODUCTION_DB_TRUST_SERVER_CERTIFICATE=false`, no waiver);
4. writes `tools\sync\sync.env` from the prepared production settings: `PRODUCTION_DB_SERVER=LIVE-HOST,1433` (fixed
   port; the Browser service does not answer), `PRODUCTION_DB_USER=mclabor_web_read`, expected name
   `LIVE-HOST\SQLEXPRESS`;
5. runs the isolated read-only connection check (`check_readonly.py`, metadata only, certificate verified) and the agent's
   **dry run** (`run-sync.ps1 -DryRun`: reads the 33 tables, compares, sends nothing). Nothing goes to the website.

## TLS plan (verified connectivity, no waiver)

| Step | Where | Status |
|---|---|---|
| Certificate for `LIVE-HOST` (CN and SAN = host name, 5 years, legacy CSP key readable by the SQL Server service account, Server Authentication EKU) installed and bound to SQLEXPRESS | live server, step 6 above | prepared; runs in the administrator's session |
| Public part exported (`.cer`, no private key) | live server, step 6 | automatic |
| Trusted on the office PC for the agent's account | office PC, import step 3 | automatic (one Yes click) |
| Agent connects by **name** `LIVE-HOST,1433` with `Encrypt=yes`, `TrustServerCertificate=no`; refuses any server not calling itself `LIVE-HOST\SQLEXPRESS` | office PC | already in the agent (`production.py`, `config.py`) |
| Renewal | 2031 | same two steps |

Until the certificate step has been run, the agent does not connect at all (no waiver is configured).

## Still needing the owner's separate approval before anything flows

1. Railway production project (`deploy/railway/create-production.ps1 -Execute`, about 12 USD a month).
2. The first import of real records into it (after the dry run above), then reconciliation.
3. The 06:00 / 12:30 schedule (`tools\sync\register-sync-task.ps1`).
4. The risk acknowledgment of `docs/cloud/20` with its two choices (`SITE_DEFAULT_USER` initials, `WEB_ADMINS` yes/no).
