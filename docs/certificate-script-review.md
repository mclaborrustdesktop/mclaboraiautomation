# Review of `tools/prod-check/proposed-certificate-setup.ps1`

Status: **not run, not tested against SQL Server.** It was only parsed (0 syntax errors) and its parameters were
checked against this PC's PowerShell. Reviewed on 2026-11-20 against Microsoft Learn, "Certificate requirements for
SQL Server" (page version dated 2026-02-27, applies to SQL Server 2019).

Target: SQL Server 2019 Express, instance `SQLEXPRESS` (`MSSQL15.SQLEXPRESS`, version 15.0.2000.5), service account
`NT Service\MSSQL$SQLEXPRESS`, on the workgroup PC `DEV-PC`.

## Requirement by requirement

| Microsoft requirement | Script | Verdict |
|---|---|---|
| Certificate in the local computer store (or the service account's) | Created in `Cert:\LocalMachine\My` | Meets |
| Service account can access the certificate's private key | Grants read on the key file to the service account, then checks the grant | Meets. The first draft did not check; see risk 1 |
| Current time inside "Valid from" / "Valid to" | Valid from now for 5 years; checked before use | Meets |
| Server Authentication EKU (1.3.6.1.5.5.7.3.1) | Set explicitly; checked | Meets |
| `KeySpec = AT_KEYEXCHANGE`, legacy CSP. KSP keys (KeySpec 0) "aren't compatible with SQL Server" | `-KeySpec KeyExchange` with `Microsoft RSA SChannel Cryptographic Provider`; checked after creation | Meets |
| Key usage usually includes key encipherment and digital signature | Set explicitly | Meets |
| Subject CN is the host name or FQDN; SAN lists every name clients use | CN=`DEV-PC`; SAN `DEV-PC`, `localhost` | Meets for connections that name the server `DEV-PC` or `localhost` |
| Client must trust the issuer | Adds the certificate to this PC's Trusted Root store | Meets for this PC only |

Not covered by that page (so not confirmed from it): how the thumbprint must be written in the registry, the exact
private-key permission, self-signed certificates, SQL Server Express. The page gives no minimum key length.

## Risks

1. **SQL Server will not start if the configured certificate is unusable.** Microsoft: "SQL Server won't start if a
   certificate exists in the computer store, but only meets some requirements ... and if it's manually configured ...
   through registry entries." The first draft could have set the registry value even if the key permission step had
   failed. The script now checks every requirement and the permission before touching the registry, and restores the
   previous setting and restarts SQL Server if it does not come back within 90 seconds.
2. **Restart.** The SQL Server service must restart. Everyone using Access is disconnected, and unsaved work in open
   Access forms can be lost. Run it only when nobody is in Access. `SQLAgent$SQLEXPRESS` depends on this service, but it
   is stopped and disabled on this PC, so nothing else is interrupted.
3. **Other computers.** ForceEncryption stays off, so programs that do not ask for encryption should behave as before.
   Any other PC that connects with encryption and verification would also need this certificate in its trusted store.
   Unverified on other PCs.
4. **Name matching.** Clients must connect as `DEV-PC` or `localhost`. An IP address, `.` or `(local)` will fail
   verification. If the PC is renamed, the certificate must be reissued.
5. **Trusted Root on this PC.** A self-signed certificate is placed in the machine's trusted roots. Its private key is
   marked non-exportable and its use is limited to server authentication, but anyone with administrator rights on
   this PC controls it.
6. **Expiry.** Valid 5 years. Microsoft: SQL Server "continues to run without problems if the certificate expires",
   but verifying clients such as the web app will then refuse to connect. Put the expiry date in a calendar.
7. **Unpatched SQL Server.** Version 15.0.2000.5 is the original 2019 release with no cumulative updates. This is
   separate from the certificate, but worth raising with whoever maintains the server.
8. **Rollback limits.** Automatic rollback covers "service does not start". It does not cover a failure in the
   middle of the script caused by something else (for example the PC losing power). The manual undo steps are at the
   bottom of the script and the values needed are saved in `certificate-setup-state.json`.

## After it is approved and run

Rerun `tools\prod-check\check_readonly.py` with `TRUST_SERVER_CERTIFICATE=no` (already set). A pass on the
"Connection" section confirms chain and hostname verification.
