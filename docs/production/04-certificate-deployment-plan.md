# 4. Certificate deployment plan

> **Which database?** Names are defined in `docs/environments.md`. DEV-PC holds a **restored copy** (staging), not the live database. This document was first written believing DEV-PC was live. Use it as written for the copy; for the possible live database on LIVE-HOST see `09-plan-connect-live-database.md`.

Script: `tools\prod-check\proposed-certificate-setup.ps1`. **Never run.** Its syntax was checked; it has not been
tested against SQL Server. Running it needs the owner's approval.

## Why it is needed

SQL Server has no certificate installed, so it shows a temporary one named `SSL_Self_Signed_Fallback`. No program
can verify that certificate, and it changes every time SQL Server starts. The website is set to verify the server's
certificate and will not connect until the server has a proper one.

## Microsoft's requirements and how the script meets them

Source: Microsoft Learn, "Certificate requirements for SQL Server" (read 2026-11-20).

| Requirement | In the script |
|---|---|
| Stored in the computer's certificate store | `Cert:\LocalMachine\My` |
| SQL Server's service account can read the private key | Read permission granted to `NT Service\MSSQL$SQLEXPRESS`, then checked |
| Valid today | Valid from now for 5 years; checked |
| Marked for "Server Authentication" | Set and checked |
| Key type `AT_KEYEXCHANGE` in a legacy provider (newer key storage is "not compatible with SQL Server") | `Microsoft RSA SChannel Cryptographic Provider`, key type checked after creation |
| Name is the server's host name; alternative names list every name clients use | `DEV-PC`, plus `localhost` |
| Clients must trust the issuer | Added to this PC's trusted root certificates |

Microsoft's page does not cover: how the certificate is selected in the registry, self-signed certificates in
particular, or Express Edition. Those parts rest on common practice, not on that page.

## Hostname validation

- The website connects to `DEV-PC\SQLEXPRESS`. The certificate name `DEV-PC` matches.
- A connection that uses an IP address, `.`, or `(local)` will fail verification. Use `DEV-PC` or `localhost`.
- If the PC is ever renamed, a new certificate is needed.

## Client trust

- **This PC:** trusted after the script runs.
- **Other PCs running Access:** not changed. The script leaves "Force Encryption" off, so programs that do not ask
  for encryption keep working as before. This has not been tested on the other PCs; check one after the change.
- Any other PC that later needs a verified connection must have the certificate's public part added to its trusted
  roots. That is a separate, approved step.

## Service interruption

- SQL Server restarts once: **about one minute** without database access.
- Everyone in Access gets connection errors and can lose unsaved work. Follow `06-access-maintenance-checklist.md`.
- The demo website is not affected.
- SQL Server Agent is disabled on this PC, so nothing else stops.

## Before

- [ ] Backup made and restore-tested (`01-backup-and-restore-checklist.md`).
- [ ] Nobody in Access (`06-access-maintenance-checklist.md`).
- [ ] Owner's approval recorded: who, when.

## Run

1. Start > type `PowerShell` > right-click **Windows PowerShell** > **Run as administrator**.
2. `cd $env:USERPROFILE\Documents\MC-Labor-AI-Automation\tools\prod-check`
3. `powershell -ExecutionPolicy Bypass -File .\proposed-certificate-setup.ps1`
4. Success is a last line beginning `Done. SQL Server is running with certificate`.

## Verify

- [ ] Open Access on this PC and on one other PC. Do one normal task.
- [ ] `backend\.venv\Scripts\python.exe tools\prod-check\check_readonly.py` gets past section "3. Connection"
      with `TRUST_SERVER_CERTIFICATE=no`.
- [ ] Put the expiry date (printed by the script) in a calendar, one month early.

## Rollback

| Situation | What happens |
|---|---|
| The certificate fails a check | The script deletes it and stops. SQL Server was never touched. |
| SQL Server does not start within 90 seconds | The script restores the old setting, starts SQL Server and removes the certificate. |
| Trouble noticed later | Run the undo commands at the bottom of the script as administrator (uses `certificate-setup-state.json`). One more minute of interruption. |
| Not covered | A failure caused by something else mid-script, such as a power cut. Use the undo commands by hand. |

Microsoft states that SQL Server will not start if a configured certificate does not meet the requirements. That is
why every check happens before SQL Server is told about the certificate.
