# Itemized Azure cost estimate and how to bring it down (2026-11-23)

> Replaced by `08-verified-pricing.md` (single-VM design, prices fetched from Microsoft's Retail Prices API). The
> figures below were from memory and are kept only to show where the first estimate went wrong.

All prices are **pay-as-you-go list prices in USD, East US, from Microsoft's published pricing pages as known
to the author; they change, and the Azure Pricing Calculator (azure.microsoft.com/pricing/calculator) is the
only binding source.** Items marked "confirm" need a check in the calculator or with Microsoft before any purchase.
Nothing has been bought. 730 hours per month.

## 1. Where the first estimate (600 - 850) went

| Item | Share |
|---|---|
| SQL Server **Standard** licence on the VM (pay-as-you-go, charged per core-hour) | about half |
| VPN gateway `VpnGw1` | about a fifth |
| Container Apps always on (2 backend + 1 frontend replicas) | about a sixth |
| VM compute and disk, backup, registry, Key Vault, logs, bandwidth | the rest |

The licence and the VPN SKU are the two levers.

## 2. Itemized estimate, three variants

| # | Item (SKU) | Unit price (approx.) | Economy | Recommended | Comfort |
|---|---|---|---|---|---|
| 1 | SQL VM compute `B2ms` (2 vCPU, 8 GB, burstable) | ~0.083/h | 61 | - | - |
| 1b | SQL VM compute `D2s_v5` (2 vCPU, 8 GB) | ~0.096/h | - | 70 | - |
| 1c | SQL VM compute `D4s_v5` (4 vCPU, 16 GB) | ~0.192/h | - | - | 140 |
| 2 | SQL Server licence: **Express** (free; 10 GB / 4 cores / 1.4 GB memory limits; database is 2.3 GB) | 0 | 0 | 0 | - |
| 2b | SQL Server licence: **Standard** pay-as-you-go, 2 cores (confirm: charged for a 4-core minimum on some images) | ~0.20/h for 2 cores (confirm) | - | 0 (see 2c) | 146 - 292 |
| 2c | SQL Server Standard via **Azure Hybrid Benefit** (a licence the company already owns, with Software Assurance) | 0 extra (confirm eligibility) | - | 0 - 146 | 0 |
| 3 | OS disk 128 GB Premium SSD `P10` | ~19.7 | - | 20 | 20 |
| 3b | OS disk 128 GB Standard SSD `E10` (enough for a 2.3 GB database with low write rates) | ~9.6 | 10 | - | - |
| 4 | Azure Backup for SQL in VM (protected instance < 50 GB + storage) | ~10 + storage | 12 | 15 | 25 |
| 5 | Container Apps backend: 1 replica, 0.5 vCPU / 1 GB, always on (consumption plan: ~0.000024/vCPU-s, ~0.000003/GB-s; first 180,000 vCPU-s and 360,000 GB-s per month free) | | 20 | - | - |
| 5b | Container Apps backend: 2 replicas, 1 vCPU / 2 GB | | - | 100 | 100 |
| 6 | Container Apps frontend: 1 replica, 0.25 vCPU / 0.5 GB | | 8 | 15 | 15 |
| 7 | Container registry `Basic` | ~5 | 5 | 5 | 5 |
| 8 | Key Vault (operations) | < 1 | 1 | 1 | 1 |
| 9 | Log Analytics (first 5 GB per billing account per month free; ~2.76/GB after) | | 0 - 5 | 5 | 10 |
| 10 | VPN gateway `Basic` (site-to-site, 100 Mbps, no SLA, policy- or route-based; confirm the office router supports it) | ~0.04/h | 27 | 27 | - |
| 10b | VPN gateway `VpnGw1` (650 Mbps, SLA, BGP) | ~0.19/h | - | - | 140 |
| 11 | Public IP (Standard, static) for the VPN gateway | ~3.7 | 4 | 4 | 4 |
| 12 | Bandwidth out (first 100 GB free; Access traffic a few GB) | ~0.087/GB | 0 - 5 | 5 | 10 |
| 13 | Staging environment: SQL VM Developer edition `B2ms` **auto-shut down** nights and weekends (about 50 h/week), 64 GB Standard SSD, Container Apps scaled to zero | | 20 | 25 | 40 |
| | **Total per month** | | **about 170 - 200** | **about 290 - 440** | **about 500 - 660** |

Reading the columns:

- **Economy** keeps SQL Server **Express** (as today) on a burstable VM with a basic VPN: the same database
  engine the office runs now, so no behaviour change; the website's performance numbers from the pilot apply as
  they are (35 users fine, 60 users with a slow tail), and the full-text index is not available **unless** the
  Azure "SQL Server Express" image is the "with Advanced Services" edition (confirm; if so full-text comes free).
- **Recommended** moves to Standard edition only through Hybrid Benefit if the company owns a licence, otherwise
  stays on Express and spends the money on a proper VM and two backend replicas. It is the 290 - 440 range.
- **Comfort** is the earlier 600 - 850 design with Standard pay-as-you-go and `VpnGw1`, slightly cheaper with the
  corrected licence figure.

## 3. The savings, in order of size

| Saving | Per month | Catch |
|---|---|---|
| Express instead of Standard pay-as-you-go | 146 - 292 | No full-text (unless Advanced Services image), 1.4 GB buffer pool, 4 cores: exactly today's limits |
| Hybrid Benefit for an owned Standard licence | 146 - 292 | Needs a licence with Software Assurance; confirm with the reseller |
| `Basic` VPN gateway instead of `VpnGw1` | 110 | No SLA, 100 Mbps, no BGP; the office router must support IKEv1/IKEv2 policy-based tunnels (confirm the router model) |
| 1 backend replica (0.5 vCPU) instead of 2 x 1 vCPU | 80 | Fewer searches in flight; fine for 35 users on the pilot numbers, a restart means a short outage |
| Burstable `B2ms` instead of `D2s_v5` | 9 | Credits run out under sustained load; fine for office hours |
| Standard SSD instead of Premium | 10 | Slower disk; irrelevant for a database that fits in memory |
| Staging auto-shutdown and scale-to-zero | 60 - 100 | Staging unavailable at night; must be started before a test |
| 1-year reserved instance for the production VM | 30 - 40 % of item 1 | Commits for a year; do it after the first stable month |
| Scale production to zero outside office hours (Container Apps) | up to 60 % of items 5-6 | The site is down at night; decide with the office whether that is acceptable (it is what they have today) |

## 4. Things that cost nothing but need a decision

- Region: East US is the usual choice for the US north-east; East US 2 prices are the same. Confirm data
  residency is acceptable (it is the United States either way).
- Microsoft 365: the company's existing tenant and licences; built-in authentication adds no cost.
- Budget alerts on each resource group at 80 % and 100 % of the chosen variant (free).

## 5. To confirm before buying (in this order)

1. Does the Azure SQL Server Express image include full-text search (Advanced Services)? If yes, Economy is enough.
2. Does the company own a SQL Server Standard licence with Software Assurance (Hybrid Benefit)?
3. Does the office router support a `Basic` VPN gateway tunnel? (Model and firmware.)
4. Current unit prices in the calculator for the chosen region, and whether the SQL Standard pay-as-you-go
   image bills 2 or 4 cores minimum.
5. Whether the office accepts the website being off at night (scale to zero) to cut the container cost.
