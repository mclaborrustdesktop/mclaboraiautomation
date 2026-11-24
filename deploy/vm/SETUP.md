# Setting up the single VM, step by step

Order matters. Nothing before step 3 costs money; steps 3 and 7 need the owner's go-ahead because they create
Azure resources and open the first (temporary) way in. Synthetic data first (`docs/cloud/05`); the restored copy
and the live database come only with their own approvals (`docs/cloud/02`).

| # | Where | What | Needs |
|---|---|---|---|
| 1 | Cloudflare dashboard | Create a free Zero Trust account for the company; add the company's domain (or a cheap new one for `app.` and `staging.` names); add the Microsoft 365 (or Google) identity provider under Settings > Authentication; create two **Access applications** (`app.<domain>`, `staging.<domain>`) with policies "allow e-mails in @mclabor.com" and note each application's **AUD tag**; create an **Access group** "SQL users" for the Access/QuickBooks PCs | company IT; no cost up to 50 users |
| 2 | This PC | `deploy\vm\azure\provision-vm.ps1` dry run; fill in subscription id, alert e-mail, storage account name; confirm the Express image SKU name with `az vm image list-skus` | - |
| 3 | This PC | `provision-vm.ps1 -Execute` for the staging-first set-up (the same VM later becomes production; or `-ResourceGroup rg-mclabor-staging -VmSize Standard_B2ms` for a separate, auto-shutdown staging VM) | **owner's go-ahead to spend** |
| 4 | Azure portal | Open a **temporary** NSG rule: RDP (3389) from the office's public IP only, 2 hours, then delete it after step 6 (or use the portal's just-in-time access) | administrator |
| 5 | On the VM (RDP) | `install-prerequisites.ps1`; `cloudflared tunnel login`, `cloudflared tunnel create mclabor-vm`, `cloudflared tunnel route dns mclabor-vm app.<domain>` and `staging.<domain>`, `cloudflared tunnel route ip add 10.20.1.0/24 mclabor-vm`; copy `cloudflared-config.yml.example` to `C:\mclabor\cloudflared\config.yml`; `cloudflared service install`; `firewall.ps1` | - |
| 6 | On the VM | SQL Server: create `McLaborStaging` (synthetic: `python -m app.synthdb` from this PC through WARP, or on the VM), run `proposed-grants.sql` with the guard set to the VM's name, give the service a certificate (`proposed-certificate-setup.ps1` with `$expectedComputer` = the VM's name), note the server's own name (`SELECT SERVERPROPERTY('ServerName')`) | - |
| 7 | On the VM | `deploy-app.ps1 -Environment staging -Source <zip of this repository>`; edit `C:\mclabor\staging\backend.env` (VM name, team domain, staging AUD tag, access lists with the two test accounts); put the login's password in `C:\mclabor\staging\secrets\staging_db_password`; `nssm start mclabor-staging-backend` | - |
| 8 | On the VM | Backups: `backup-sql.ps1 -InitKey` (store the printed key in the password safe), a write-only SAS for the `sqlbackups` container into `C:\mclabor\secrets\backup.sas`, `register-tasks.ps1 -Database McLaborStaging`, then run `backup-sql.ps1 -Database McLaborStaging` once by hand and `restore-test.ps1` once | - |
| 8b | This PC or the VM | Roster: `import-access-roster.py` with `deploy\vm\staff-roster.example.csv` (synthetic staff) against the staging store; the Users page shows the count against the maximum of 20; from now on administrators add or remove people on the Users page, no restart (`docs/cloud/09-user-access-plan.md`) | - |
| 9 | Any PC | `https://staging.<domain>` asks for the company sign-in and shows the STAGING label; `deploy\vm\smoke.ps1 -Site https://staging.<domain> -Expect staging` passes; a third account not on the lists gets 403 | - |
| 10 | One office PC | Install the Cloudflare WARP client, enrol in the Zero Trust team, join the "SQL users" group; in Access, relink a **copy** of the application to `10.20.1.4` / `McLaborStaging` (synthetic data) and time the forms and reports | one staff member |
| 11 | Azure portal | Delete the temporary RDP rule from step 4. From now on administrators reach RDP through WARP too (`firewall.ps1` allows 3389 from the WARP range only) | administrator |
| 12 | This PC | Load tests against staging (`tools\staging\loadtest.py` with the staging hostname through Access needs a service token: Zero Trust > Service Auth; or run it on the VM against 127.0.0.1:8100) | - |

Production, later, is steps 6-9 again with `McLabor`, `-Environment production`, the production AUD tag and the
real access lists, after `docs/cloud/02` Phase 2.

## Updating the website later

Copy the new zip to the VM, `deploy-app.ps1 -Environment production -Source <zip>`: the previous version stays in
`C:\mclabor\production\app.previous`; to roll back, stop the two services, swap the folders back, start them.

## Everyday operation

| Task | How |
|---|---|
| Is it up? | `https://app.<domain>/api/ready` after sign-in; the 5-minute health task writes an Error event (and an alert e-mail) when not |
| Logs | `C:\mclabor\<env>\logs\` (JSON lines with request ids), `C:\mclabor\logs\backup.log`, `cloudflared.log`; Azure portal for VM metrics and alerts |
| Add or remove a person | `WEB_ADMINS` / `WEB_USERS` in `C:\mclabor\<env>\backend.env` (initials or e-mail as they sign in), then `nssm restart mclabor-<env>-backend`; and the Cloudflare Access policy if the policy lists people rather than the domain |
| Restart | `nssm restart mclabor-production-backend` (10 seconds) |
| Costs | Azure portal > Cost Management; the budget e-mails at 50 / 75 / 90 / 100 % |
