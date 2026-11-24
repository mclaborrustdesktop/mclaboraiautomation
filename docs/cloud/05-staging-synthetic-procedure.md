# Cloud STAGING with synthetic data only: the procedure

Goal: prove the whole cloud design (VM database, containers, sign-in, VPN, monitoring, costs) with a
McLabor-**shaped** database that contains not one real record, before any money beyond the staging environment is
spent and before any real data moves. Estimated running cost while it exists: 20 - 40 USD per month with the VM shut
down outside tests (`04-cost-estimate.md`, item 13).

What is already prepared on this PC: the two container images and the Compose stack (`deploy/cloud`), the
synthetic database builder (`python -m app.synthdb`), the smoke test in both modes (`tools/containers/smoke_test.py`),
the Azure provisioning plan (`deploy/cloud/azure/provision.ps1`, dry run by default), and the settings templates.

## Step 0 - decisions and access (the only things that cannot be done from here)

| # | Needed | From |
|---|---|---|
| 0.1 | An Azure subscription in the company's name, with the owner as subscription owner and the developer as Contributor on **one resource group** (`rg-mclabor-staging`) only | owner, Microsoft account sign-up |
| 0.2 | The region (East US unless told otherwise) and a monthly budget alert on the resource group (suggest 60 USD) | owner |
| 0.3 | The Microsoft 365 tenant: an app registration for the staging site (redirect URL known once the site name exists) and the names of two test accounts allowed to sign in | company IT |
| 0.4 | Whether Docker may be installed on DEV-PC (or which other PC), or whether images are to be built in Azure only | owner |

## Step 1 - local rehearsal (no Azure)

`deploy/cloud/BUILD-AND-TEST.md`, sections 2 and 4: the DEMO stack passes the smoke test on this PC, and the
real-data stack is rehearsed against the synthetic database in a local SQL Server container with sign-in through
the real Microsoft 365 app registration (section 0.3). This finds the configuration mistakes before they cost anything.

## Step 2 - staging resources (first spend)

```
powershell -ExecutionPolicy Bypass -File deploy\cloud\azure\provision.ps1 -ResourceGroup rg-mclabor-staging -SqlVmName vm-mclabor-sql-stg -SqlImage MicrosoftSQLServer:sql2022-ws2022:sqldev-gen2:latest -SqlVmSize Standard_B2ms
```

prints the plan; the same with `-Execute` creates it after the placeholders are filled in. Two changes for
staging: **Developer edition** (free licence, not for production), and an **auto-shutdown** schedule on the VM
(`az vm auto-shutdown --time 1900`). No VPN gateway yet: for synthetic data a temporary **point-to-site** VPN or the
Azure Bastion-free alternative (a just-in-time RDP rule) is enough; the site-to-site gateway is a production item.

## Step 3 - the synthetic database on the staging VM

1. On the VM (RDP through the point-to-site VPN or a just-in-time rule): create the database `McLaborSynthetic`
   with the collation `SQL_Latin1_General_CP1_CI_AS`, and the certificate with
   `proposed-certificate-setup.ps1` adapted to the VM's name (or an internal CA certificate).
2. From this PC through the VPN, or from the VM itself:
   ```
   backend\.venv\Scripts\python.exe -m app.synthdb "mssql+pyodbc://<admin>:<pw>@vm-mclabor-sql-stg,1433/McLaborSynthetic?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes" 0.2
   ```
   builds the 33 tables and about 36,000 invented employees, 21,000 customers, 3,000 jobs and 38,000 tracking rows
   (scale 1.0 for the full size of the real database when load-testing).
3. `proposed-grants.sql` with its server guard changed to the VM's name creates `mclabor_web_read` with the same 288
   column permissions as on the copy; `check_readonly.py` with a `prodcheck.env` for the VM must end
   READ-ONLY CONNECTION VERIFIED.

## Step 4 - the website in Container Apps (staging)

1. Images built (`az acr build`, or pushed from a PC with Docker), Container Apps created by the plan with
   `DATA_SOURCE=staging`, `STAGING_DB_SERVER=<vm>,1433`, `STAGING_DB_EXPECTED_SERVER_NAME=<what the VM calls itself>`,
   the password in Key Vault, `ACCESS_MODE=gateway`, `GATEWAY_PLATFORM=azure-easyauth`, `GATEWAY_TRUSTED_PROXIES=127.0.0.1`,
   `WEB_ADMINS=<test account e-mail>`, `WEB_USERS=<second test account>`.
2. Built-in authentication on the frontend app pointed at the app registration; unauthenticated action
   "redirect to login".
3. Checks, in order: `/api/ready` through the ingress answers 200 only after sign-in; the smoke test in `--expect
   staging` mode passes; the status page shows STAGING, the VM's name, read-only, no outside AI service; the
   second test account sees the look-up pages only; a third account not on the lists gets 403.
4. `tools/staging/search_timing.py`, `search_equivalence.py` and `loadtest.py` against the staging stack (they run
   from a PC on the VPN, or from a small job container in the environment): the cloud numbers replace the on-prem
   numbers in `docs/search-performance.md`.

## Step 5 - what the rehearsal must answer before real data moves

| Question | Measured by |
|---|---|
| Does sign-in with company accounts work without a website login screen, and are the access lists enforced? | step 4.3 |
| Does the website meet the pilot's numbers in the cloud (35 and 60 users)? | step 4.4 |
| Does Access over the VPN perform acceptably? | a copy of the Access file relinked to the **synthetic** database on the staging VM: forms, list screens, three reports, timed |
| What does a month of staging actually cost? | the resource group's cost view after 30 days, against `04-cost-estimate.md` |
| Backup and restore on the VM | Azure Backup restore of the synthetic database to a point in time |
| Rollback drill | `02-migration-and-rollback.md`, "after C4" path, rehearsed with the synthetic database and a spare VM |

Only after these are answered does `02-migration-and-rollback.md` Phase 1 (the restored copy in the cloud) start,
with its own approval for the first transfer of real records.

## Step 6 - tearing it down

`az group delete --name rg-mclabor-staging` removes everything at once; nothing real was ever in it.
