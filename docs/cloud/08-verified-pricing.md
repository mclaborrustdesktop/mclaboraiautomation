# Verified Azure pricing for the single-VM design (fetched 2026-11-23)

Source: Microsoft's **Azure Retail Prices API** (`https://prices.azure.com/api/retail/prices`), the public data
behind the Azure Pricing Calculator, queried on 2026-11-23, pay-as-you-go ("Consumption") prices, USD, no
discounts, 730 hours per month. The unit prices below are exactly as returned; the monthly figures are unit price
times quantity. Anything the API did not return is marked **unverified**. Prices change: re-run the queries (listed
at the end) before purchase, or paste the items into the calculator.

## 1. Itemized monthly estimate, East US, production VM

| # | Item | SKU / meter as returned | Unit price | Quantity | Monthly USD |
|---|---|---|---|---|---|
| 1 | VM compute incl. **Windows Server licence** | Virtual Machines BS Series Windows, B4ms | 0.182 / hour | 730 h | **132.86** |
| 2 | SQL Server 2019 Express licence | not returned by the API; Express is Microsoft's free edition | 0 | - | 0.00 **(unverified by API; confirm in the portal)** |
| 3 | OS disk 128 GB Standard SSD | Standard SSD Managed Disks, E10 LRS Disk | 9.6 / month | 1 | 9.60 |
| 3b | OS disk mount meter | E10 LRS Disk Mount | 0.91 / month | 1 | 0.91 |
| 4 | Data disk 64 GB Standard SSD (database files, local backups) | E6 LRS Disk (+ Mount 0.47) | 4.8 / month | 1 | 5.27 |
| 5 | Public IP (outbound only; inbound denied by the NSG) | IP Addresses, Standard IPv4 Static Public IP | 0.005 / hour | 730 h | 3.65 |
| 6 | Azure Backup of the VM, protected instance | Backup, Azure VM Protected Instance | 10.0 / month | 1 | 10.00 |
| 7 | Azure Backup storage (30 daily recovery points, incremental; assume 60 GB) | Backup, Standard LRS Data Stored | 0.0224 / GB-month | 60 GB | 1.34 |
| 8 | SQL backup files in Blob (35 daily + 12 monthly of about 1 GB zipped and encrypted; assume 50 GB) | General Block Blob v2, Cool LRS Data Stored | 0.0152 / GB-month | 50 GB | 0.76 |
| 9 | Internet data transfer out (website pages, WARP traffic; first 100 GB free) | Standard Data Transfer Out, tier 0 then 100 GB+ | 0.0 then 0.087 / GB | 40 GB | 0.00 |
| 10 | Metric alert rules (4; the first 10 are free) | Azure Monitor, Alerts Metric Monitored | 0.0 (tier 0) | 4 | 0.00 |
| 11 | Log alert rule, 15-minute frequency (backup / website errors) | Alerts System Log Monitored at 15 Minute Frequency | 0.5 / month | 1 | 0.50 |
| 12 | Log Analytics ingestion (event-log errors only; first 5 GB free) | Analytics Logs Data Ingestion, tier 0 | 0.0 then 2.3 / GB | < 1 GB | 0.00 |
| 13 | Cloudflare Zero Trust (Access + Tunnel + WARP) | Free plan, up to 50 users | 0 | - | 0.00 **(not Azure; free plan terms, confirm user count)** |
| | **Production total, East US** | | | | **164.89** |

Optional items:

| Item | Monthly USD | Note |
|---|---|---|
| Separate staging VM `B2ms` Windows, deallocated except about 40 hours a month, plus its 128 GB disk | 66.576 × 40/730 = 3.65 + 9.60 + 0.91 = **14.16** | compute billed only while running; disks always |
| Staging on the same VM (separate database and services) | 0.00 | the recommended start |
| `Standard_D4s_v5` Windows instead of `B4ms` if Access over WARP needs it | **unverified** (not fetched); Microsoft lists it near 140 for the VM | re-query before changing |
| 1-year reservation for `B4ms` | **unverified**: the API returned no reservation price for B4ms in East US | Microsoft publishes about 35 % off compute; verify in the portal's reservation page |
| Cloudflare Zero Trust beyond 50 users | 7 per user per month (Cloudflare's published price, not verified here) | the main budget risk |

**Realistic monthly total: 165 USD for production alone, about 180 USD with a mostly-off staging VM, at
list prices, under 50 Cloudflare users.** Headroom to 200: 20-35 USD.

> Revision 2026-11-23 for a maximum of 20 users (`11-vm-size-for-20-users.md`): with `Standard_B2ms` (66.58 instead
> of 132.86) the production total is **98.61 USD**, and **121.69 USD** with the mostly-off staging VM.

## 2. Region comparison (B4ms Windows, the only item whose price differs)

| Region | B4ms Windows / hour | Monthly | B2ms Windows / hour | Monthly | Production total |
|---|---|---|---|---|---|
| East US | 0.182 | 132.86 | 0.0912 | 66.58 | 164.89 |
| East US 2 | 0.182 | 132.86 | 0.0912 | 66.58 | 164.89 |
| West US 2 | 0.182 | 132.86 | not fetched | - | 164.89 (disk and IP prices assumed equal; re-query) |
| North Central US | 0.182 | 132.86 | not fetched | - | 164.89 (same assumption) |
| Central US | 0.216 | 157.68 | 0.108 | 78.84 | 189.71 |
| South Central US | 0.216 | 157.68 | not fetched | - | 189.71 |

East US or East US 2 for a New England office: lowest price and lowest latency (about 15-25 ms from Boston).
East US 2 is the better choice when East US shows capacity restrictions for B-series at creation time. Central and
South Central cost 19 % more for the VM and add latency.

## 3. Budget and alerts

`deploy/vm/azure/budget.bicep`: a monthly budget of 200 USD on the resource group with e-mail alerts at 50, 75, 90
and 100 % of actual spend and at 100 % of the forecast (the forecast alert fires early in the month if the run
rate would exceed 200). Deployed by the last step of `provision-vm.ps1`. Budgets are free.

## 4. What is unverified or assumed

| Item | Status |
|---|---|
| SQL Server Express licence line = 0 | API returned no "Virtual Machines Licenses" item for Express; Express is free by Microsoft's licensing; confirm the image's "software plan" shows 0 in the portal |
| B4ms reservation price | API returned no item; verify in the portal before committing a year |
| D4s_v5 price | not fetched |
| Backup storage and blob quantities (60 GB, 50 GB) | estimates from a 2.3 GB database; actuals appear in the first month's bill |
| Bandwidth 40 GB | estimate; the free tier is 100 GB |
| Cloudflare free-plan limits | Cloudflare's published terms; not an Azure item |
| Prices themselves | list prices on 2026-11-23; Microsoft changes them; no enterprise or CSP discount applied |

## 5. The API queries used (repeatable)

```
https://prices.azure.com/api/retail/prices?$filter=armSkuName eq 'Standard_B4ms' and priceType eq 'Consumption' and (armRegionName eq 'eastus' or armRegionName eq 'eastus2' or armRegionName eq 'centralus' or armRegionName eq 'southcentralus' or armRegionName eq 'westus2' or armRegionName eq 'northcentralus')
https://prices.azure.com/api/retail/prices?$filter=armSkuName eq 'Standard_B2ms' and priceType eq 'Consumption' and (armRegionName eq 'eastus' or armRegionName eq 'eastus2' or armRegionName eq 'centralus')
https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Storage' and armRegionName eq 'eastus' and productName eq 'Standard SSD Managed Disks' and (skuName eq 'E10 LRS' or skuName eq 'E6 LRS' or skuName eq 'E4 LRS')
https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Virtual Network' and armRegionName eq 'eastus' and productName eq 'IP Addresses'
https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Backup' and armRegionName eq 'eastus'
https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Storage' and armRegionName eq 'eastus' and productName eq 'General Block Blob v2' and meterName eq 'Cool LRS Data Stored'
https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Bandwidth' and armRegionName eq 'eastus' and contains(meterName, 'Data Transfer Out')
https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Azure Monitor' and armRegionName eq 'eastus' and (contains(meterName, 'Alert') or contains(meterName, 'Data Ingestion'))
https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Log Analytics' and armRegionName eq 'eastus' and contains(meterName, 'Data Ingestion')
```
