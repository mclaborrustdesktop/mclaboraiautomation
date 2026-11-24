# Staging pre-flight: what will be created, what it costs, what is verified (2026-11-23)

Decision: first cloud deployment = a separate STAGING environment in East US with synthetic data only; production
budget 200 USD; a maximum of **20** website users (revised from 30 on 2026-11-23; VM sizing for 20 users is in
`11-vm-size-for-20-users.md`). Nothing below has been created. Provisioning waits for the owner's explicit approval
of this page. Decision 2026-11-23: the Azure CLI is **not** installed on DEV-PC; everything runs in Azure Cloud
Shell, step by step in `deploy/vm/azure/CLOUDSHELL.md` (pre-flight script `preflight-cloudshell.ps1`, upload
package `cloudshell-package.zip`, temporary set-up door `temporary-rdp.ps1`).

## 1. Azure sign-in and subscription - NOT YET VERIFIABLE from this PC

The Azure CLI is not installed on DEV-PC and no Azure sign-in exists here. Two things are needed before any
check against Azure can run, both yours to approve or do:

1. Install the Azure CLI on this PC: `winget install --id Microsoft.AzureCLI -e` (a software install; it adds the
   `az` command and nothing else). Alternative: run the plan from the Azure Cloud Shell in the portal, which has
   `az` built in, by uploading `deploy/vm/azure`.
2. Sign in: `az login` (opens the browser), then `az account show` must print the company's subscription name and
   your account. If more than one subscription is visible, `az account set --subscription <id>` picks the right one
   and that id goes into `provision-vm.ps1 -Subscription`.

## 2. Image, size and region availability - RUNS AFTER STEP 1

```
az vm image list-skus --location eastus --publisher MicrosoftSQLServer --offer sql2019-ws2022 --output table
az vm list-skus --location eastus --size Standard_B4ms --output table
az vm image terms show --publisher MicrosoftSQLServer --offer sql2019-ws2022 --plan express-gen2
```

Expected: a SKU named `express-gen2` (or `express`) for SQL Server 2019 Express on Windows Server 2022; `Standard_B4ms`
listed for `eastus` without a `NotAvailableForSubscription` restriction; no marketplace terms to accept (Microsoft
first-party image). If the SKU name differs, it is passed with `-Image`; if B4ms is restricted in East US, East US 2
has the same price (`08-verified-pricing.md`).

## 3. The exact resources (`provision-vm.ps1 -Environment staging`, dry run printed 2026-11-23)

| # | Resource | Name | Notes |
|---|---|---|---|
| 1 | Resource group | `rg-mclabor-staging` | tags `environment=staging data=synthetic-only`; the cleanup script refuses any group without these tags |
| 2 | Network security group | `nsg-mclabor` | one rule: **deny all inbound**; no allow rule exists |
| 3 | Virtual network + subnet | `vnet-mclabor` 10.20.0.0/16, `snet-vm` 10.20.1.0/24 | |
| 4 | Public IP, Standard static | `pip-mclabor-outbound` | outbound internet for the VM only; every inbound packet is denied by the NSG |
| 5 | Network interface | `nic-mclabor`, private 10.20.1.4 | |
| 6 | Virtual machine | `vm-mclabor-stg`, `Standard_B2ms` (revised for 20 users; `-VmSize Standard_B4ms` keeps the larger size), image `MicrosoftSQLServer:sql2019-ws2022:express-gen2:latest`, OS disk 128 GB Standard SSD | Windows Server licence included in the VM price; SQL Server Express licence free; B2ms compute 0.0912 / hour, so the first-month figures below (which assumed B4ms at 0.182) halve for the running hours |
| 7 | Data disk | `disk-mclabor-data`, 64 GB Standard SSD | database files and local backups |
| 8 | SQL IaaS agent registration | `connectivity-type PRIVATE` | management only; no public SQL endpoint |
| 9 | Boot diagnostics, automatic patching | | |
| 10 | **Auto-shutdown 19:00** daily with e-mail | | deallocates the VM: compute billing stops every evening |
| 11 | Storage account + container | `stmclabor stg<unique>` / `sqlbackups`, cool tier, TLS 1.2, no public access, lifecycle 35 daily / 12 monthly | synthetic backup files only |
| 12 | Log Analytics workspace | `log-mclabor`, 30-day retention | event-log errors only |
| 13 | Action group | `ag-mclabor-owner` | e-mail to the owner |
| 14 | Metric alerts (4) | CPU, memory, disk queue, VM availability | the first 10 metric alerts are free |
| 15 | Azure Monitor agent + data collection rule | Application-log errors from `MCLaborBackup`, `MCLaborWeb`, SQL Server | |
| 16 | Log alert | backup failed or website not ready, every 15 min | 0.50 USD/month |
| 17 | Budget | `mclabor-monthly-staging`, **50 USD**, alerts at 50 / 75 / 90 / 100 % actual and 100 % forecast | free |

Not created for staging: Azure Backup (synthetic data), a VPN gateway, a load balancer, any inbound rule.

## 4. Costs (unit prices from Microsoft's Retail Prices API, 2026-11-23, East US, USD)

| Item | Unit price | Billed while deallocated? | Monthly |
|---|---|---|---|
| VM compute B4ms Windows | 0.182 / hour | **no** | 0.182 × hours running |
| OS disk E10 (+ mount meter) | 9.60 + 0.91 | yes | 10.51 |
| Data disk E6 (+ mount meter) | 4.80 + 0.47 | yes | 5.27 |
| Public IP Standard static | 0.005 / hour | yes | 3.65 |
| Storage account (synthetic backup files, about 5 GB cool) | 0.0152 / GB | yes | 0.10 |
| Log alert rule (15 min) | 0.50 | yes | 0.50 |
| Metric alerts, Log Analytics (free tiers), budget, auto-shutdown, Cloudflare free plan | 0 | - | 0.00 |
| **Floor while deallocated** | | | **20.03** |

| Scenario | Running hours | Total |
|---|---|---|
| First month: set-up day plus four test days (about 40 hours) | 40 | 20.03 + 7.28 = **27.31** |
| First month, heavy testing (80 hours) | 80 | 20.03 + 14.56 = **34.59** |
| Ongoing: two test days a month (16 hours) | 16 | 20.03 + 2.91 = **22.94** |
| Forgotten running all month (what the 50 USD budget alerts would catch) | 730 | 20.03 + 132.86 = 152.89 |

Important: "Stop" inside Windows does **not** stop billing; only **deallocate** (the auto-shutdown, the portal's
Stop button, `az vm deallocate`) does. The 19:00 auto-shutdown deallocates.

## 5. Cost alerts and cleanup

- Budget 50 USD on the resource group, e-mails at 25, 37.50, 45 and 50 USD actual, and at a 50 USD forecast.
- `deploy/vm/azure/cleanup-staging.ps1`: `-DeallocateOnly -Execute` stops compute (floor 20 USD); `-Execute`
  deletes the whole resource group after the name is typed (floor 0). It refuses any group not tagged
  `environment=staging data=synthetic-only`. Cloudflare's tunnel entry and hostname are removed in the dashboard.

## 6. Scripts and rollback - verified

| Check | Result |
|---|---|
| All nine PowerShell scripts in `deploy/vm` parse (`PSParser`) | 0 errors |
| `provision-vm.ps1` dry run for staging | 27 steps printed above; `-Execute` refuses to run while any `<placeholder>` remains |
| Deployment configuration tests (`tests/test_deploy_config.py`) | pass: no inbound allow rule, B4ms, 2019 Express, Standard SSD, budget thresholds 50/75/90/100, lifecycle 35/366, backup scripts verify + encrypt, services bound to 127.0.0.1 |
| Application rollback | `deploy-app.ps1` keeps `app.previous`; swap folders and restart the two services |
| Environment rollback | delete the resource group (synthetic data; nothing to keep) |
| Website | 169 backend tests, 9 frontend tests, production build |

## 7. No MC Labor employee or customer record will be uploaded - confirmed

The staging database is built by `python -m app.synthdb` (33 tables in production shape, invented rows; test
`test_synthdb.py` proves every e-mail is `@example.com`, every restricted column is empty). The roster is the
synthetic staff list. No script in the staging procedure reads, copies or transfers a `.bak`, a CSV or a row from
the office; the transfer of the restored copy is a later, separately approved phase (`02`, Phase 1).

## 8. No connection to LIVE-HOST or DEV-PC SQL Server is required - confirmed

The synthetic build runs on the staging VM's own SQL Server Express. `synthdb.refuse_office_servers()` raises on
`LIVE-HOST`, `DEV-PC`, `<live-host-ip>`, `<dev-pc-ip>`, `localhost` and `127.0.0.1` (tested). Nothing in `deploy/vm`
references either office server.

## 9. Access only through Cloudflare, SQL port never public - confirmed by configuration and tests

NSG: deny all inbound, no allow rule (test). Windows Firewall: inbound blocked by default, 1433 and 3389 only from
the WARP range and the subnet (`firewall.ps1`). Website ports bound to 127.0.0.1 (`deploy-app.ps1`, test). The only
way in is the Cloudflare Tunnel (outbound from the VM); Cloudflare Access protects both hostnames and the backend
verifies the Access token on every request (`cloudflare_access.py`, tests). Port 1433 is reachable only through the
tunnel's private route by enrolled WARP clients in the "SQL users" group.

## Decision needed from the owner

Approve, in one line, (a) installing the Azure CLI on DEV-PC (or using Cloud Shell), (b) signing in with the
company subscription, and (c) creating the 17 resources above in East US with the expected first-month cost of
about 27 to 35 USD and an ongoing cost of about 20 to 25 USD while mostly deallocated. After the sign-in, the
image and size checks in section 2 run first; if they pass, provisioning starts; if a SKU or size is unavailable,
the alternative is reported before anything is created.
