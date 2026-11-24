# McLabor SQL Server connection report - 2026-11-20

**Result: BLOCKED before sign-in.** The server answered, but its encryption certificate cannot be verified by this PC.
Per the owner's decision, certificate verification was kept on and the check stopped there.
Nothing was read from or written to the database.

## What was run

- Tool: `tools/prod-check/check_readonly.py` (isolated; does not use the website's code or settings)
- Settings: `tools/prod-check/prodcheck.env` - server `DEV-PC\SQLEXPRESS`, database `McLabor`, Windows sign-in,
  `ODBC Driver 17 for SQL Server`, `ENCRYPT=yes`, `TRUST_SERVER_CERTIFICATE=no`
- Raw output: `tools/prod-check/reports/prodcheck-20261120-102736.txt` (no password in it)

## Results

| Step | Result |
|---|---|
| ODBC driver and pyodbc on this PC | OK - ODBC Driver 17 for SQL Server, pyodbc 5.5.0 |
| SQL Server reachable | Yes - `DEV-PC\SQLEXPRESS` answered and started the encryption handshake |
| Encryption certificate | **Failed** - "The certificate chain was issued by an authority that is not trusted" (self-signed certificate) |
| Windows authentication | Not tested - the connection stops before sign-in |
| Database access and permissions | Not tested |
| Schema compatibility (live) | Not tested. Offline comparison with the client's CSV export still passes (31 tables, 291 columns) |
| Automated tests | 65 of 65 pass |
| Demo website and backend | Still running, still on the local demo database. `backend/.env` does not exist; production mode and writes are off |

## Why it stopped

SQL Server Express creates its own self-signed certificate when none is installed. An encrypted connection that
verifies the server's identity rejects such a certificate. The two ways forward:

1. **Install a certificate on SQL Server that this PC trusts** (keeps verification on). This is a change to the SQL
   Server configuration and to this PC's trusted certificates. It needs an administrator, a restart of the SQL Server
   service (Access users are disconnected for a moment), and the owner's approval. Not done.
2. **Allow `TRUST_SERVER_CERTIFICATE=yes` for the check tool only.** The connection stays encrypted; only the identity
   check is skipped. The server is on this same PC, so traffic does not leave the machine. Declined on 2026-11-20.

## Certificate diagnosis (2026-11-20, read-only)

Certificate fetched with `tools/prod-check/inspect_certificate.py` (handshake only, no sign-in); saved as
`tools/prod-check/reports/server-certificate.cer`.

| Check | Finding |
|---|---|
| Certificate configured in SQL Server | None (registry value empty). SQL Server 2019 (15.0.2000.5), ForceEncryption off |
| Certificate presented | `CN=SSL_Self_Signed_Fallback`, self-signed, created 2026-11-19 19:01, 2048-bit RSA / SHA-256 |
| Chain | Fails: `UntrustedRoot`. It is its own issuer and is not in this PC's Trusted Root store |
| Hostname | Fails: the name is `SSL_Self_Signed_Fallback`, with no alternative names. It can never match `DEV-PC` |
| Stability | SQL Server creates a new fallback certificate at every service start, so it cannot be trusted permanently |
| Suitable certificate on this PC | None in the machine certificate store |
| ODBC settings | Correct (`Encrypt=yes`, verification on). Driver 17 has no setting that accepts this certificate while verifying it |

Conclusion: nothing on the application side can fix this with verification on. Trusting the fallback certificate on
this PC would not help either: the name still would not match, and it changes at the next restart. The server needs
a real certificate named `DEV-PC`.

Prepared for approval, not run: `tools/prod-check/proposed-certificate-setup.ps1`. It needs an administrator and
restarts the SQL Server service (Access users disconnected for about a minute). It changes no database content,
logins, permissions, ports or firewall rules, and includes undo steps.

## Not changed

No SQL accounts, permissions, server settings, ports, Access files or database records were touched.

## Remaining before real employee, customer and job searches

1. Get past the certificate step (one of the two options above), then rerun the check to test Windows sign-in,
   permissions and the live schema.
2. A column-restricted read-only login (`tools/prod-check/proposed-grants.sql`, not run). The current Windows account
   is likely to have more rights than the web app should use.
3. Web app change: stop selecting EmDOB, USCitizen, I9Complete and OfficeStaffPassword in production mode.
4. Staff sign-in for the web app (Access passwords are not usable as they are).
5. Read-only pilot: compare web search results with Access.
