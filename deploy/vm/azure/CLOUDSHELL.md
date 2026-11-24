# Staging in Azure, driven from Azure Cloud Shell (no software on DEV-PC)

Cloud Shell is a browser terminal in the Azure portal with the Azure CLI already signed in as you. Everything
below runs there, read-only until the one provisioning step that you approve explicitly. Costs: Cloud Shell itself
needs a small storage file share (a few cents a month) which the portal creates on first use.

## A. Before anything billable

1. Open https://shell.azure.com, choose **PowerShell** (not Bash). On first use accept the storage set-up.
2. Upload the package: the **Upload** button in the Cloud Shell toolbar, file `deploy/vm/azure/cloudshell-package.zip`
   (made on DEV-PC by `deploy/vm/azure/make-package.ps1`). Then:
   ```
   mkdir -p mclabor; cd mclabor; Expand-Archive ~/cloudshell-package.zip -DestinationPath . -Force; ls
   ```
3. Pre-flight (read-only; creates nothing):
   ```
   ./preflight-cloudshell.ps1 -Location eastus -VmSize Standard_B2ms
   ```
   It prints who you are, the subscription, your role, provider registration, the B-series vCPU quota, whether
   `Standard_B2ms` is available in East US, the SQL Server 2019 Express image SKU to use, the current list
   prices, and whether the resource group name is free. **Paste the output back to me.** If a provider is
   "NotRegistered" it says the one free command that fixes it; if East US restricts B2ms, East US 2 has the same price.
4. Dry run of the plan (prints the 29 commands, runs none):
   ```
   ./provision-vm.ps1 -Environment staging -Subscription <id from step 3> -AlertEmail you@company.com -StorageAccount stmclaborstg<4 digits>
   ```
   Storage account names must be globally unique, 3-24 lowercase letters and digits.

Then STOP. The resource list and the cost estimate are in `docs/cloud/10-staging-preflight.md` (B2ms revision:
compute 0.0912 USD/hour while running; floor about 20 USD/month while deallocated; first month about 24-28 USD).

## B. After your explicit approval: provisioning (billable from here)

```
./provision-vm.ps1 -Environment staging -Execute -Subscription <id> -AlertEmail you@company.com -StorageAccount stmclaborstg<4 digits>
```
It asks for the VM administrator password (20+ characters; put it in the password safe), then runs the 29 steps
in order, printing each; a failed step stops it and every step is safe to run again. Expected time: 10-15 minutes,
most of it the VM creation and the monitor agent. At the end: the resource group, the deny-all network, the VM
(deallocated each evening at 19:00), storage, alerts and the 50 USD budget exist.

Then the one-time door for set-up:
```
./temporary-rdp.ps1 -Add -FromIp <the office public IPv4, see https://ifconfig.me>
az network public-ip show -g rg-mclabor-staging -n pip-mclabor-outbound --query ipAddress -o tsv
```
Connect with Remote Desktop to that address as `mcladmin`. (RDP's local-drive redirection is how the repository
zip and the Cloudflare files reach the VM.)

## C. On the VM (SETUP.md steps 5-8, from the copy of the repository)

```
powershell -ExecutionPolicy Bypass -File deploy\vm\install-prerequisites.ps1
# Cloudflare: cloudflared tunnel login / create mclabor-vm / route dns staging.<domain> / route ip add 10.20.1.0/24; config.yml; cloudflared service install
powershell -ExecutionPolicy Bypass -File deploy\vm\firewall.ps1
# SQL Server: create McLaborStaging; build the synthetic data:
backend\.venv\Scripts\python.exe -m app.synthdb "mssql+pyodbc://<admin>:<pw>@<VM-NAME>\SQLEXPRESS/McLaborStaging?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes" 0.2
# the read-only login (proposed-grants.sql with the guard set to <VM-NAME>\SQLEXPRESS), the certificate (proposed-certificate-setup.ps1 with $expectedComputer = '<VM-NAME>')
powershell -ExecutionPolicy Bypass -File deploy\vm\deploy-app.ps1 -Environment staging -Source C:\mclabor\downloads\mclabor-src.zip
# edit C:\mclabor\staging\backend.env; put the login password in C:\mclabor\staging\secrets\staging_db_password; nssm start mclabor-staging-backend
powershell -ExecutionPolicy Bypass -File deploy\vm\backup-sql.ps1 -InitKey      # store the printed key in the password safe
powershell -ExecutionPolicy Bypass -File deploy\vm\register-tasks.ps1 -Database McLaborStaging
```
(Synthetic data only: the builder refuses LIVE-HOST, DEV-PC and localhost; nothing is copied from the office.)

## D. Tests, in order

| Test | Where | Command | Pass when |
|---|---|---|---|
| Smoke, from outside | DEV-PC | `deploy\vm\smoke.ps1 -Site https://staging.<domain> -Expect staging` | backend port unreachable; proxy demands sign-in; forged headers refused |
| Smoke, on the VM | VM | `backend\.venv\Scripts\python.exe tools\containers\smoke_test.py --expect staging --api http://127.0.0.1:8100` | guards pass |
| Sign-in and roles | browser | sign in with the two test accounts; `import-access-roster.py` loads the synthetic roster; a removed account gets 403 | Users page shows the count against 20 |
| Backup and restore | VM | `backup-sql.ps1 -Database McLaborStaging` then `restore-test.ps1 -Database McLaborStaging` | both log PASSED; an encrypted file appears in the `sqlbackups` container |
| Security | Cloud Shell + VM | `./temporary-rdp.ps1 -Remove`, then `./temporary-rdp.ps1 -Status` says deny-all; on the VM `Get-NetFirewallRule -DisplayName 'MC Labor *'`; from DEV-PC `Test-NetConnection <public ip> -Port 1433` must fail | no public path to SQL or RDP |
| 20-user load | VM | `powershell -File tools\staging\loadtest-staging.ps1 -People "20" -StaffId <synthetic admin id> -Workers 2` (it starts its own backend on 8001 against the staging settings) | all answered; 95% within 5 s; the CPU-credit alert does not fire |
| Access over WARP | one office PC | WARP client enrolled; a copy of the Access file relinked to 10.20.1.4 / McLaborStaging | forms and reports open; timings noted |

## E. Cleanup and rollback

```
./cleanup-staging.ps1 -DeallocateOnly -Execute     # stop compute billing (floor about 20 USD/month)
./cleanup-staging.ps1 -Execute                     # delete everything in rg-mclabor-staging (you type the name)
```
Application rollback on the VM: stop the two services, rename `app` and `app.previous` back, start them.
