# 9. Plan B: connect the website to the live database (read-only)

Target, **to be confirmed**: `LIVE-HOST\SQLEXPRESS` (`<live-host-ip>`), database `McLabor`. Nothing on LIVE-HOST has
been inspected or changed. Do not start Plan B until Plan A has passed on the copy.

## B0. Confirm the target (no change)

- [ ] Manual check on a staff PC (`07-database-location-findings.md`): server and database the real Access
      application uses. Written down: SERVER = __________ DATABASE = __________
- [ ] Owner confirms in writing that this is the live database and approves read-only access for the website.

## B1. Learn the state of LIVE-HOST (read-only; needs someone who can sign in to LIVE-HOST)

- [ ] SQL Server version there (`SELECT @@VERSION;`). The 11-13 backup was written by version 15.0.2000, which has
      never been updated.
- [ ] Who is a SQL Server administrator there (`SELECT IS_SRVROLEMEMBER('sysadmin');`).
- [ ] Last backup date of `McLabor`, and whether a backup routine exists.
- [ ] Whether SQL Server there has a certificate (expect: none, same as DEV-PC).
- [ ] Whether it accepts SQL logins (the `mclabor` login suggests yes).
- [ ] Other databases on it. `McLabor 20260811 Development` is known to be there; the read-only login must be
      created in `McLabor` only.

## B2. Changes on LIVE-HOST (each needs the owner's approval; all rehearsed in Plan A first)

| Step | What | Interruption for Access users |
|---|---|---|
| Backup + restore test | `01-backup-and-restore-checklist.md`, on LIVE-HOST | None |
| SQL Server update (recommended) | `03-sql-server-update-plan.md` | 5 to 20 minutes - use `06` |
| Certificate | `04-certificate-deployment-plan.md`, with the name **`LIVE-HOST`** | About 1 minute - use `06` |
| Read-only login | `05-read-only-login-procedure.md` | None |

Differences from the rehearsal on DEV-PC:

- **Real users are connected.** The Access maintenance checklist (`06`) is required for the update and the certificate.
- **The certificate name is `LIVE-HOST`**, and the website must connect by that name. The Access links use the IP
  address `<live-host-ip>`; they do not ask for encryption, so they should be unaffected, but check one staff PC after.
- **The website is on a different PC from the database.** DEV-PC must trust LIVE-HOST's certificate (its public part
  is added to DEV-PC's trusted certificates), and LIVE-HOST's firewall must allow DEV-PC to reach SQL Server.
  Whether it already does is unknown. No firewall rule is to be changed without approval.
- **Windows sign-in will not work** between the two PCs (no shared Windows domain), so the dedicated SQL login is
  the only option.
- The certificate script reads the computer name automatically, so it produces the right name when run on LIVE-HOST.

## B3. Connect (website side only)

1. `tools\prod-check\prodcheck.env`: `SERVER=LIVE-HOST\SQLEXPRESS`, `AUTH=sql`, `USER=mclabor_web_read`.
2. `check_readonly.py` must end "READ-ONLY CONNECTION VERIFIED". Reads no records.
3. `backend\.env` with `DATA_SOURCE=production` and the same server and login. Writes stay off.
4. `python -m app.livecheck`, then a read-only pilot with one or two staff, comparing with Access.

## Never part of this plan

- Using the `mclabor` login for the website. It can change data, and its password is stored in the Access files.
- Turning on changes to real data from the website.
- Reading SSN, bank, date-of-birth, citizenship, I-9 or staff-password columns.

## Back out

Rename `backend\.env` to `backend\.env.off` and restart the website: it is back on demo data. On LIVE-HOST, each
change has its own undo steps in its document; removing the login is three `DROP` lines.
