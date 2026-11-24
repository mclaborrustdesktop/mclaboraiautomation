# The single-VM Azure design (primary option, decided 2026-11-23, budget 200 USD per month)

> Revision 2026-11-23: the maximum is **20 website users**, not 30. Whether the VM can be smaller than `B4ms` for 20
> users, with measurements, is in `11-vm-size-for-20-users.md`; the access limits are in `09-user-access-plan.md`.

Replaces `01-cloud-architecture.md` as the primary plan; that document stays as the comparison of database
options and the earlier, more expensive design. Prices quoted here come from Microsoft's Retail Prices API as
fetched on 2026-11-23 (`08-verified-pricing.md`). Nothing is provisioned, bought, migrated or changed on LIVE-HOST.

## 1. Design

One Windows Server 2022 VM, `Standard_B4ms` (4 vCPU, 16 GB), SQL Server 2019 **Express** from Microsoft's
marketplace image (same major version as LIVE-HOST, so a backup moves in either direction), the FastAPI backend and
the Next.js frontend as Windows services, and a Cloudflare Tunnel as the only way in or out.

```
staff browser --HTTPS--> Cloudflare Access (company Microsoft 365 / Google sign-in, 2-step)
                               |  tunnel (outbound from the VM; no inbound port, no public listener)
                               v
                     VM 10.20.1.4: cloudflared -> 127.0.0.1:8000 backend (4 workers) / :3000 frontend  [production]
                                              -> 127.0.0.1:8100 / :3100                                 [staging]
office PC with Access + QuickBooks --WARP client--> tunnel private route --> SQL Server Express 1433 (firewall: WARP range only)
nightly: backup -> verify -> AES-256 -> Azure Blob (35 daily, 12 monthly) ;  daily Azure Backup of the VM (30 days)
```

| Requirement from the decision | How it is met |
|---|---|
| Windows-compatible services, no Docker | NSSM-registered services under virtual service accounts (`deploy/vm/deploy-app.ps1`), the same code as on this PC |
| Reverse proxy | `cloudflared` routes by hostname and path to the local ports; no Caddy/IIS needed; HTTPS is Cloudflare's |
| Staff access without a website login screen | Cloudflare Access in front; the backend **verifies the signed token** Cloudflare attaches (`GATEWAY_PLATFORM=cloudflare-access`, `backend/app/cloudflare_access.py`): signature against Cloudflare's keys, audience = the application's AUD tag, issuer, expiry; the e-mail from the verified token is matched to `tblOfficeStaff` and `WEB_ADMINS` / `WEB_USERS`. Tested with forged tokens, wrong audience, wrong issuer, expiry and wrong origin address |
| Private SQL connectivity for Access users; 1433 never public | The tunnel's private network route (`warp-routing`) carries 10.20.1.0/24 to enrolled WARP clients; the NSG denies all inbound; Windows Firewall allows 1433 only from the WARP address range and the subnet; the VM's public IP is for outbound traffic only (Azure requires explicit outbound since default outbound access was retired for new networks) |
| DEMO / STAGING / PRODUCTION separated | DEMO stays off the VM; staging and production are separate folders, env files, secrets, sign-in stores, services, ports, hostnames, Access applications (own AUD) and SQL databases; the backend's identity check refuses the other database |
| Encrypted off-server backups | `backup-sql.ps1`: `BACKUP ... WITH CHECKSUM`, `RESTORE VERIFYONLY`, AES-256 + HMAC with a key kept in the password safe, upload with a write-only token, lifecycle 35 days / 12 months; `restore-test.ps1` monthly; plus Azure Backup of the whole VM |
| HTTPS, firewall, monitoring | Cloudflare terminates HTTPS and talks to the VM over the tunnel; NSG + Windows Firewall as above; four metric alerts (CPU, memory, disk, availability), an event-log alert for backup or website errors, the 5-minute health task, the budget with four thresholds |

## 2. Can SQL Server Express carry 30 to 60 users and the McLabor database?

| Express limit | McLabor today | Verdict |
|---|---|---|
| 10 GB per database | 2.3 GB, growing about 0.2 GB a year | fine for years |
| Lesser of 1 socket / 4 cores | B4ms has 4 vCPU: Express uses all four | same as the pilot's machine |
| 1.4 GB buffer pool | the searched tables of the employee and customer tables fit; the pilot ran this exact configuration | measured: 35 users all answered, 95% within 3.5 s; 60 users all answered, 95% within 8 s |
| No SQL Agent | backups by scheduled task (`register-tasks.ps1`) | done |
| No full-text search (plain Express) | word searches stay as measured; narrow indexes (`proposed-indexes.sql`) still apply; the Azure image may be "Express with Advanced Services" (full-text included) - to confirm on the staging VM with `SERVERPROPERTY('IsFullTextInstalled')` | acceptable at 30-35 users; at 60 users the slowest searches reach 8-14 s during bursts |
| No backup compression or encryption in the engine | done outside the engine (zip + AES) | done |

The B-series note: `B4ms` runs at 90 % baseline CPU and banks credits when idle; an office that is busy eight
hours a day never runs out. If the Access forms turn out heavy over WARP, the next step is `Standard_D4s_v5`
(about 140 USD instead of 133 for the VM) rather than a database change.

## 3. Secure employee access without a website login screen

1. The person opens `https://app.<domain>`; Cloudflare Access redirects to the company's Microsoft 365 sign-in
   (two-step verification is enforced in the tenant), then sets its own cookie and forwards the request through the
   tunnel with `Cf-Access-Jwt-Assertion`.
2. The backend accepts the request only if it came from the tunnel on this VM (`GATEWAY_TRUSTED_PROXIES`), the
   token verifies for **this** application (AUD), the e-mail belongs to an active staff record, and the person is on
   `WEB_ADMINS` or `WEB_USERS`. Otherwise 401/403. No password exists anywhere in the website for real data.
3. Sign-out is Cloudflare's (`/cdn-cgi/access/logout`); sessions last as the Access policy says (suggest 8 hours).
4. Administrators reach RDP the same way (WARP + the firewall rule), so no management port is ever public.

## 4. Private connectivity for Microsoft Access and QuickBooks

- Each office PC that runs Access installs the Cloudflare **WARP** client, enrols in the team, and is put in the
  "SQL users" group; Zero Trust network policies allow that group to reach `10.20.1.4:1433` (and nothing else).
- Access links are refreshed once (Linked Table Manager) to `10.20.1.4` or to a private DNS name, database
  `McLabor`, with ODBC Driver 18 installed on the PC. The `mclabor` SQL login is recreated on the VM for Access.
- QuickBooks and QODBC stay on the office PC; Access reaches both as before.
- Latency: office to East US about 15-35 ms per round trip; measured on staging with the real Access file
  (`05-staging-synthetic-procedure.md`, step 10). Fallback if too slow: Remote Desktop to the VM for the two or
  three heaviest Access users (RDP through WARP; Windows Server allows two administrative sessions, more needs
  RDS licensing, about 6 USD per user per month).
- Alternative if Cloudflare is not wanted for the PCs: an Azure VPN gateway `Basic` (about 27 USD per month) with
  the office router; the website part is unaffected.

## 5. Environment separation in practice

| | STAGING | PRODUCTION |
|---|---|---|
| Hostname / Access application | `staging.<domain>`, own AUD, policy: the test accounts | `app.<domain>`, own AUD, policy: the company domain |
| Folder, services, ports | `C:\mclabor\staging`, `mclabor-staging-*`, 8100 / 3100 | `C:\mclabor\production`, `mclabor-production-*`, 8000 / 3000 |
| Database | `McLaborStaging` (synthetic first; the restored copy only with approval) | `McLabor` (after the migration in `02`) |
| Secrets, sign-in store, logs | own folder, DPAPI-protected password file | own folder |
| What the backend refuses | the production database (identity check), writes, an outside AI service without approval | the staging database, writes, same |

A separate auto-shutdown staging VM (`Standard_B2ms`) costs about 10-15 USD a month when deallocated most of the
time; sharing the production VM costs nothing extra. Start shared; split if staging tests disturb production.

## 6. Synthetic testing, migration validation, rollback

- **Synthetic first**: `05-staging-synthetic-procedure.md` applies with the VM in place of Container Apps: the
  synthetic database is built into `McLaborStaging`, the staging site is validated with the smoke test in
  real-data mode, the Access file is tested over WARP against synthetic data, the backup and restore tasks run.
- **Migration**: `02-migration-and-rollback.md` Phase 1 (restored copy to the VM, with its own approval) and
  Phase 2 (cut-over) unchanged in substance; the transfer is a `.bak` uploaded to the backup container and restored
  on the VM; Access relinks go to `10.20.1.4` instead of `<live-host-ip>`.
- **Rollback**: a `.bak` from Express 2019 on the VM restores on LIVE-HOST's Express 2019 directly (same version),
  which is why the image choice is 2019 rather than 2022.

## 7. Remaining development (unchanged by the hosting decision)

`06-feature-status.md` and `03-remaining-development.md`: the read-only website is feature-complete for look-ups;
Add/Edit on real data needs the nine items in `docs/production/16-add-edit-plan.md` (about two weeks) after the
read-only site is in everyday use; the rate-visibility decision; the employee contact columns; the full-text
question. New since this decision: `deploy/vm` tooling to rehearse on the staging VM, and the Cloudflare Access
verification (done, tested).

## 8. Blockers to staying under 200 USD (see `08-verified-pricing.md`)

1. **Cloudflare Zero Trust's free plan covers 50 users.** Web users and WARP users both count. With up to 50
   staff the sign-in and the private SQL route cost nothing; with 60 the plan is 7 USD per user per month (about
   420 USD) and the budget breaks. Count the actual users; if over 50, the fallback is Cloudflare Access for the
   website only for the people who need it, and the Azure `Basic` VPN (27 USD) for the Access PCs.
2. The Express image's zero licence line is not returned by the pricing API (Express has no licence fee; confirm
   in the portal when creating the VM).
3. Prices are list prices for East US; the budget leaves about 30-45 USD of headroom at full price, less if the
   VM must grow to `D4s_v5` or a second staging VM runs more than a few days a month.
4. Bandwidth: the first 100 GB a month out of Azure are free; Access over WARP moves a few GB a month. A report
   that pulls whole tables repeatedly could exceed it (0.087 USD per GB beyond).
