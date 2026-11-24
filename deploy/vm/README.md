# Single Windows VM deployment (the budget design, primary option since 2026-11-23)

One Azure VM (`Standard_B4ms`, Windows Server 2022, SQL Server 2019 Express from the marketplace image, no
Docker) runs everything. Nothing on it is reachable from the internet: the website is published through a
**Cloudflare Tunnel** with **Cloudflare Access** in front (company sign-in, no website login screen), and the
Access/QuickBooks PCs reach SQL Server through the same tunnel's **private network route** with the Cloudflare
WARP client. Port 1433 is never exposed; the VM has no inbound rule at all.

```
staff browser --HTTPS--> Cloudflare Access (company sign-in) --tunnel--> cloudflared on the VM
                                                                           |-- /api/*  -> 127.0.0.1:8000 backend (production)
                                                                           |-- /*      -> 127.0.0.1:3000 frontend (production)
                                                                           '-- staging.<domain> -> 8100 / 3100 (staging)
office PC (MS Access + QuickBooks) --WARP client--> tunnel private route 10.20.1.0/24 --> SQL Server 1433 on the VM
nightly: SQL backup -> verify -> AES-256 encrypt -> Azure Blob (cool, 35 daily + 12 monthly); Azure Backup of the VM daily
```

| Component on the VM | Runs as | Port (localhost only) |
|---|---|---|
| `mclabor-production-backend` (uvicorn, 4 workers, read-only SQL login) | Windows service (NSSM), virtual service account | 8000 |
| `mclabor-production-frontend` (`node server.js`, Next.js standalone) | Windows service | 3000 |
| `mclabor-staging-backend` / `-frontend` (separate install folder, env file, sign-in store, SQL database `McLaborStaging`) | Windows services | 8100 / 3100 |
| `cloudflared` (tunnel; routes hostnames and the private network) | Windows service | outbound only |
| SQL Server 2019 Express (`McLabor`, `McLaborStaging`) | Windows service (from the image) | 1433, firewall-limited to the tunnel's address range |
| Backup task (`backup-sql.ps1`), restore test (`restore-test.ps1`) | Scheduled tasks | - |

## Files

| File | Purpose |
|---|---|
| `SETUP.md` | the step-by-step set-up, in order, with what needs whose approval |
| `azure/provision-vm.ps1` | the Azure resources as `az` commands, **dry run by default**; `azure/budget.bicep` the 200 USD budget with alerts at 50/75/90/100 % |
| `install-prerequisites.ps1` | on the VM: Python, Node, ODBC Driver 18, NSSM, cloudflared, AzCopy, SqlCmd (pinned downloads from the vendors) |
| `deploy-app.ps1` | on the VM: installs or updates one environment (staging or production) from a copy of this repository, builds the frontend, registers the services |
| `cloudflared-config.yml.example` | tunnel ingress for both hostnames and the private route for SQL |
| `env/backend.production.env.example`, `env/backend.staging.env.example` | backend settings per environment (Cloudflare Access platform, read-only SQL login, access lists); secrets are files in `C:\mclabor\secrets` |
| `firewall.ps1` | Windows Firewall: inbound closed except SQL (and RDP) from the tunnel's address range |
| `backup-sql.ps1`, `restore-test.ps1`, `register-tasks.ps1` | encrypted off-server backups, the monthly restore test, and their scheduled tasks |
| `smoke.ps1` | after a deployment: runs `tools/containers/smoke_test.py` in real-data mode through the public hostname |

## Environment separation on one VM

Each environment has its own folder (`C:\mclabor\production`, `C:\mclabor\staging`), env file, secrets folder,
web sign-in store, services, ports, Cloudflare hostname **and Access application (own AUD tag)**, and SQL database.
The backend's identity check (`*_DB_EXPECTED_SERVER_NAME` + database name) refuses the other database; the two
env files never hold the other environment's settings. DEMO is not installed on the VM at all (it stays on
DEV-PC and in the Compose `demo` profile).

## What the design does not include, on purpose

No public IP that answers (the IP exists only so the VM can reach the internet), no VPN gateway, no load
balancer, no container platform, no second VM for production. Scaling later means a bigger VM size (minutes of
downtime) or moving the database to its own VM; the application already supports both.
