# Cloud architecture for the MC Labor system (2026-11-23)

> **Superseded as the primary plan on 2026-11-23** by the single-VM design with a 200 USD monthly budget:
> `07-single-vm-plan.md` (design) and `08-verified-pricing.md` (prices from Microsoft's pricing API). This document
> stays for the comparison of the three Azure database options (section 2) and as the fallback design for later growth.

Decision taken by the owner: the final system is hosted in the cloud because the office cannot keep its PCs and
SQL Server running around the clock. Nothing is deployed and nothing has been bought; this document is the design,
the evaluation of the three Azure database options, the compatibility findings for Access and QuickBooks, the sizing
for 30+ employees, and cost estimates. The code changes that make the application cloud-ready are listed in section 8.

## 1. Recommended architecture

```
office PCs (Access + QuickBooks)            staff browsers (office, home)
        |  site-to-site VPN                          |  HTTPS
        v                                            v
+-------------------------------- Azure, one region, one VNet ---------------------------------+
|  SQL Server 2022 on an Azure VM          Container Apps environment (in the VNet)             |
|  (private address only, port 1433        +-- ca-mclabor-web  frontend image, external ingress |
|   open to the VNet and the VPN only)     |     + built-in authentication (Microsoft 365)       |
|  database McLabor, backups to a          +-- ca-mclabor-api  backend image, internal ingress   |
|  Recovery Services vault                 |     2-4 replicas x 4 workers, read-only SQL login    |
|                                          Key Vault (secrets)  Log Analytics (logs, alerts)      |
+-----------------------------------------------------------------------------------------------+
```

- **Database: SQL Server on an Azure VM** (section 2 says why), restored from a native `.bak` of the live
  database, reached only through the VNet: from the containers directly, from the office through a site-to-site VPN.
  The Access application keeps working with linked tables (section 3).
- **Website: the two container images** in `backend/Dockerfile` and `frontend/Dockerfile`, run by Azure
  Container Apps with the platform's HTTPS and **built-in authentication** against the company's Microsoft 365
  tenant. Staff never see a website login screen; the backend reads the identity the platform attaches
  (`GATEWAY_PLATFORM=azure-easyauth`) and applies `WEB_ADMINS` / `WEB_USERS`. The same images also run with
  `deploy/cloud/docker-compose.yml` (Caddy + oauth2-proxy) on any VM or for rehearsals.
- **Secrets** in Key Vault, mounted as files (`MCLABOR_SECRETS_DIR`); **logs** as JSON lines with a request id in
  Log Analytics; **health**: `/api/health` (liveness) and `/api/ready` (readiness: database and sign-in store).
- **Environments** stay strictly separate: one resource group per environment (`rg-mclabor-staging`,
  `rg-mclabor-prod`), each with its own database, container apps, Key Vault and access lists, and the website's own
  identity check (`*_DB_EXPECTED_SERVER_NAME`) refusing the other environment's server. DEMO stays on this PC and
  in the `--profile demo` containers, with synthetic data only.

## 2. The three Azure database options against the McLabor database

What the database is: SQL Server 2019 (15.0.2000) Express, one database of about 2.3 GB, 298 tables, 260 foreign
keys, SQL logins (`mclabor`, used by Access), no SQL Agent jobs on the copy, `money`, `ntext`/`nvarchar(max)` columns,
a 254-column employee table, Access linked tables through SQL Server Native Client 11.0, QuickBooks reached
from Access through QODBC on the office PC.

| | SQL Server on an Azure VM | Azure SQL Managed Instance | Azure SQL Database |
|---|---|---|---|
| Compatibility with the database as it is | **100%**: restore the `.bak`, done | Near 100%: native restore from a `.bak` in blob storage; SQL Agent, cross-database queries, SQL logins all exist | Partial: no `.bak` restore (export/import via `.bacpac` or the Data Migration Assistant), no `USE`, no cross-database queries, no SQL Agent, logins become contained users |
| Access linked tables | Unchanged (relink to the new server name; ODBC Driver 17/18 recommended instead of Native Client 11) | Same | Works, but every Access form round-trip crosses the internet; `dbo` schema fine |
| Our website's SQL (checked offline against `docs/schema`) | Runs as on the copy | Runs as on the copy | Runs; `SERVERPROPERTY('ServerName')` returns the logical server name, which the identity check compares - confirm on a trial database and set `*_DB_EXPECTED_SERVER_NAME` accordingly |
| Column-level GRANTs (the 288-column read-only login) | Yes | Yes | Yes (contained user) |
| Full-text search (what word searches need for 30 users) | Yes with Standard/Developer; **not** with the plain Express image | Yes | Yes, all tiers |
| Backups | You schedule them (Azure Backup for SQL in VM does it, with point-in-time) | Automatic, 7-35 days, point-in-time | Automatic, point-in-time |
| Patching, restarts | You (or Azure "automated patching" on a weekly window) | Azure | Azure |
| Minimum size and cost | 2 vCPU VM; licence free with Express, pay-as-you-go for Standard | **4 vCores minimum**, the most expensive option | 2 vCores or DTU tiers from small |
| Rollback to the office server | Take a `.bak`, restore on LIVE-HOST | `.bak`-style copy-only backup to blob, restore on-prem (same or lower version only: MI runs the latest version, LIVE-HOST runs 2019: **a backup from MI cannot be restored on LIVE-HOST**) | Export to `.bacpac`, import on-prem (slow, loses nothing in data but is not a native restore) |
| Fit for Access + QuickBooks today | Best | Good | Weakest (latency, and QODBC/Access patterns that assume a full SQL Server) |

**Recommendation: SQL Server on an Azure VM, Standard edition** (Developer edition for the staging copy, which is
free but not licensed for production). It is the only option that is an exact copy of today's server, keeps a
clean rollback path to LIVE-HOST (same version family), allows the full-text index, and costs less than Managed
Instance. Azure SQL Database is the right destination later, once the Access application has been replaced by the
website; until then its restrictions and the internet round-trips for Access are the risk. Managed Instance buys
automation at roughly three to four times the VM's price.

Compatibility risks to verify on the first cloud restore (staging copy, in this order): SQL login `mclabor` and
its password are recreated (logins are not inside a `.bak`); collation stays `SQL_Latin1_General_CP1_CI_AS`;
`CompatibilityLevel` stays 150 until Access and the website have been tested; QODBC continues to run on the office
PC (it is not a server component); Access forms over the VPN open in acceptable time (section 3).

## 3. Keeping Access, its forms and reports, and QuickBooks working

- **Linked tables**: Access stores `SERVER=<live-host-ip>;DATABASE=McLabor` in each link. After the move the links are
  refreshed once with the Linked Table Manager to the VM's private name. Relinking is a normal Access operation and
  takes minutes; the forms, queries and reports are unchanged.
- **Driver**: SQL Server Native Client 11.0 is deprecated; it still connects to SQL Server 2022 on a VM, but the
  relink is the moment to switch the links to "ODBC Driver 18 for SQL Server" (installed on each office PC). That
  driver encrypts by default, which the VPN makes optional but harmless.
- **Latency**: on the office network a round trip is under 1 ms; to Azure East US it is 10-40 ms. Access forms make
  many round trips. Expect list forms and reports that were instant to take a second or two, and complex reports
  longer. Measure on the staging copy with the real Access file before go-live. If it is not acceptable, the
  fallback that keeps everything else in this design is an **Azure Virtual Desktop / Remote Desktop session host in
  the same VNet** on which Access runs next to the database.
- **QuickBooks**: QODBC runs on the PC that has QuickBooks Desktop; Access reaches it locally and the database over
  the VPN. Nothing in the cloud changes that. If QuickBooks itself is ever moved (QuickBooks Online), the QODBC
  links are the part to redo.
- **The `mclabor` SQL login** Access uses must be recreated on the cloud server with the same password; the website
  keeps its own restricted logins (`mclabor_web_read`, later `mclabor_web_write`).
- **Two writers, one database**: unchanged from today. The website is read-only until the Add/Edit stage
  (`docs/production/16-add-edit-plan.md`); its concurrency rule (W6) is what protects Access users' edits.

## 4. 30+ concurrent employees

Measured on the restored copy (4-core Express, `docs/search-performance.md`): 35 people, every search answered,
typical 0.23 s, 95% within 3.5 s; 60 people, 95% within 8 s. The limit was the database's CPU on word searches.
In the cloud design:

| Component | Sizing | Reason |
|---|---|---|
| SQL Server VM | `Standard_D2s_v5` (2 vCPU, 8 GB) to start; `D4s_v5` (4 vCPU, 16 GB) if word searches dominate | Standard edition lifts Express's 4-core / 1.4 GB limits, so the whole database sits in memory; the full-text index (`tools/prod-check/proposed-fulltext.sql`, approval needed) takes word searches off the CPU |
| Backend | 2 replicas x 4 workers, 1 vCPU / 2 GB each, scale to 4 on CPU | 8-16 searches in flight; the 30-second result memory is per replica (harmless) |
| Frontend | 1-3 replicas, 0.5 vCPU / 1 GB | static pages, cheap |
| Ingress | platform HTTPS, built-in authentication | no extra component |

## 5. Security in the cloud

Same model as on the PC, moved: database on a private address only (no public IP; NSG allows 1433 from the VNet
and the VPN only); the website's SQL login reads 288 approved columns and nothing else; the backend has internal
ingress only; the frontend's external ingress is behind the platform's authentication (Microsoft 365 accounts of
the company tenant, two-step verification enforced in the tenant); `WEB_ADMINS` / `WEB_USERS` decide who may use
it; secrets in Key Vault; TLS to the database with certificate verification (the VM's SQL certificate is issued
by an internal CA or a public one for its name: `TRUST_SERVER_CERTIFICATE` stays false); logs hold request ids,
paths and timings, never search words or names; no outside AI service without the owner's recorded approval. The
VPN is what keeps the database off the internet; the office router (or a Windows RRAS box) terminates it.

## 6. Estimated monthly infrastructure cost (list prices, East US, November 2026 - verify in the Azure pricing calculator before buying; no reservation discounts applied)

| Item | Recommended | Estimate / month |
|---|---|---|
| SQL Server VM `D2s_v5` with SQL Server **Standard** pay-as-you-go, 128 GB premium disk | production | 300 - 420 |
| Same VM with **Express** (free licence; keeps today's limits; no full-text) | fallback | 100 - 140 |
| Same VM with **Developer** edition for the staging copy (free licence, non-production), running only during tests | staging | 20 - 60 |
| Azure Backup for the SQL VM (7 days + weekly 4 weeks) | production | 15 - 40 |
| Container Apps: backend 2 x (1 vCPU, 2 GB) + frontend 1 x (0.5 vCPU, 1 GB), always on | production | 110 - 160 |
| Container Apps for staging, scaled to zero between tests | staging | 5 - 20 |
| Container registry (Basic), Key Vault, Log Analytics (about 5 GB/month) | both | 15 - 35 |
| VPN gateway `VpnGw1` (site-to-site to the office) | both | 140 - 160 |
| VPN gateway `Basic` (point-to-site only, no SLA) | alternative | 25 - 35 |
| Bandwidth out (Access traffic, a few GB) | both | 5 - 15 |
| **Total, recommended (Standard VM + Container Apps + VpnGw1)** | | **about 600 - 850** |
| Total, economy (Express VM + Container Apps + Basic VPN) | | about 280 - 400 |
| For comparison: Managed Instance GP 4 vCores instead of the VM | | 750 - 1,000 more |
| For comparison: Azure SQL Database GP 2 vCores instead of the VM | | 350 - 450 (plus the Access caveats) |

Not included: the Microsoft 365 licences the company already has, a possible Remote Desktop session host for
Access (`D4s_v5` + Windows licensing, about 200 - 300), and staff time.

## 7. Risks and what mitigates them

| Risk | Mitigation |
|---|---|
| Access over the VPN too slow for daily work | Measure on the staging copy with the real file first; Remote Desktop session host in the VNet as the fallback |
| VPN or internet outage stops the office | Office keeps a local **read** copy restored nightly on LIVE-HOST for emergencies (no writes while disconnected), or accepts the outage; this is the trade-off of cloud hosting and must be decided explicitly |
| Database password of `mclabor` in every Access file | Unchanged by the move; the right moment to replace it with a per-user login or Windows authentication through Entra ID joined VMs |
| Cloud SQL Server unpatched, like LIVE-HOST today | VM automated patching window weekly; or Managed Instance later |
| Cost creep | Budgets and alerts on the resource groups; staging scaled to zero between tests |
| Data residency / contract | The owner confirms the region and signs the Microsoft customer agreement; employee records never leave the chosen region; no outside AI service |
| Rollback | `02-migration-and-rollback.md`: a `.bak` from the VM restores on LIVE-HOST in minutes because the version family is the same |

## 8. What was changed in the application for cloud hosting (2026-11-23)

| Change | Where |
|---|---|
| Secrets from files (`MCLABOR_SECRETS_DIR`, Docker/Key Vault mounts): a file named like a setting supplies it | `config.py` |
| JSON logs with request id, environment, method/path/status/duration; access log opt-in; query strings never logged | `observability.py`, `main.py`, `LOG_FORMAT`, `ACCESS_LOG` |
| `X-Request-ID` on every response (kept from the proxy when safe) | `observability.py` |
| `/api/ready` readiness (database + sign-in store, 503 until both answer), `/api/health` liveness, frontend `/healthz` | `main.py`, `frontend/src/app/healthz/route.ts` |
| Azure built-in authentication as a gateway platform (`GATEWAY_PLATFORM=azure-easyauth`): identity from `X-MS-CLIENT-PRINCIPAL-*`, trusted-proxy check kept, no shared secret | `config.py`, `security.py` |
| Connection retry for transient cloud errors (`ConnectRetryCount`/`Interval`), login timeout | `production.py`, `database.py`, `DB_CONNECT_*` |
| Container images, Compose stack with HTTPS proxy and sign-in, DEMO profile, Azure provisioning plan (dry run) | `backend/Dockerfile`, `frontend/Dockerfile`, `deploy/cloud/*` |
| Next.js standalone output | `frontend/next.config.ts` |
| AI search: four pilot corrections (customer status vs. "active jobs", city vs. customer name, "starting this month", real customer-type labels, number words) | `ai.py`, `search.vocab` |

Tests: `backend/tests/test_cloud_ready.py` and the additions in `test_api.py`.
