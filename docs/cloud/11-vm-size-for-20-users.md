# VM size for a maximum of 20 users: can it be smaller than B4ms? (2026-11-23)

## 1. What was measured

`tools\staging\loadtest-staging.ps1` against the restored copy on this PC's SQL Server 2019 Express (4 cores,
1.4 GB buffer pool, the Express limits a VM would have), 20 simulated people, 6 searches each from the 12-search
mix, one every 2 to 6 seconds. Two runs:

| Run | Backend | Answered | Typical | 95% within | Slowest | Backend memory |
|---|---|---|---|---|---|---|
| "B4ms-like": 4 workers, all 8 logical processors | as production | 120 of 120 | 0.33 s | 2.69 s | 6.24 s | 465 MB (6 processes) |
| "B2ms-like": 2 workers pinned to 2 logical processors | approximates a 2-vCPU VM | 120 of 120 | 0.20 s | 2.63 s | 3.01 s | 254 MB (4 processes) |

Reports: `tools\prod-check\reports\loadtest-b4ms-like-20users-*.txt`, `loadtest-b2ms-like-20users-*.txt`.
Reading: at 20 users the application tier is idle most of the time; two workers on two logical processors are
enough, and the 95th percentile is the same. The tail is the database's word searches, exactly as at 35 and 60
users.

What the test did **not** cover: SQL Server itself had four cores in both runs (this PC's instance was not
touched). On a 2-vCPU VM the database and the application share two logical processors. The per-search CPU cost of
the database is known from the pilot (0.2 to 1.6 s of CPU for a word search, milliseconds for a filtered list), and
20 people at a search every 2 to 6 seconds is about 5 searches a second with an average CPU cost of about 0.3 s:
roughly 1.5 CPU-seconds per second during a busy minute, i.e. 75 % of two logical processors in bursts.

## 2. B2ms against B4ms (East US, unit prices from Microsoft's pricing API, 2026-11-23)

| | `Standard_B2ms` | `Standard_B4ms` |
|---|---|---|
| vCPU / memory | 2 / 8 GB | 4 / 16 GB |
| Windows VM price | 0.0912 / h = **66.58** / month | 0.182 / h = **132.86** / month |
| B-series baseline CPU (sustained without credits) | 40 % of 2 vCPU = 0.8 vCPU | 90 % of 4 vCPU = 3.6 vCPU |
| Credits banked per hour / maximum bank | 36 / 864 | 108 / 2,592 |
| SQL Server Express gets | 2 cores (its limit is 4) | 4 cores |
| Memory budget: Windows Server about 2 GB, SQL Express 1.4 GB buffer + about 0.5 GB, backend 0.3 to 0.5 GB, frontend 0.2 GB, cloudflared 0.1 GB, headroom | about 4.5 GB used of 8 | about 4.7 GB used of 16 |
| 20 users, application tier (measured) | fine | fine |
| 20 users, database tier | expected fine: bursts of 75 % are covered by banked credits; a workday averaging under 40 % stays within baseline | measured fine on this PC's 4 cores |
| Risk | sustained CPU above 40 % for hours exhausts credits and the VM is throttled to 0.8 vCPU: searches would slow to several seconds until credits rebuild | none at this load |
| Resize | `az vm resize` to B4ms: about 5 minutes of downtime, no other change | - |

Smaller than B2ms (`B2s`: 4 GB, `B1ms`: 2 GB) does not fit SQL Server plus Windows plus the website in memory and
is not considered. `D2s_v5` (2 vCPU, 8 GB, no credit throttling) costs more than B4ms on Windows and gains nothing
for a bursty office load.

## 3. Recommendation: start on B2ms, measure on staging, resize only if the credit alert fires

Reasons: at 20 users the application needs two logical processors at most (measured); the database's bursts fit
the credit model of a B2ms for an 8-hour office; memory fits with 3.5 GB spare; the saving is 66 USD a month; and
the staging environment is the right place to confirm the one unmeasured part (the database on two shared vCPUs)
before production exists. Two safeguards are built in:

- the provisioning plan now creates an alert on **CPU credits remaining below 100** (the sign that the VM is about
  to be throttled) next to the CPU, memory, disk and availability alerts;
- the staging acceptance test is the 20-user load test on the staging VM itself (`05`, step 12); if its 95th
  percentile exceeds 5 seconds or the credit alert fires during the test, the VM is resized to B4ms before go-live.

## 4. Revised monthly cost (maximum 20 users, East US, unit prices from the pricing API)

| Item | B2ms configuration | B4ms configuration |
|---|---|---|
| VM compute incl. Windows licence | 66.58 | 132.86 |
| OS disk E10 (+ mount) and data disk E6 (+ mount) | 15.78 | 15.78 |
| Public IP (outbound only) | 3.65 | 3.65 |
| Azure Backup of the VM, instance + about 60 GB | 11.34 | 11.34 |
| Blob storage for encrypted SQL backups | 0.76 | 0.76 |
| Log alert rule | 0.50 | 0.50 |
| Metric alerts (5, within the free 10), Log Analytics (free tier), budget, bandwidth (within the free 100 GB), Cloudflare free plan | 0.00 | 0.00 |
| **Production total** | **98.61** | **164.89** |
| Staging VM B2ms, deallocated except about 40 hours a month, plus its disks and IP | 23.08 | 23.08 |
| **Production + mostly-off staging** | **121.69** | **187.97** |

Against the 200 USD target the B2ms configuration leaves about 78 USD of headroom with staging, or about 100 USD
without it; the B4ms configuration leaves 12 to 35 USD. The Cloudflare side stays free: 20 website users plus up
to 8 WARP users is 28 of 50 seats.

## 5. What else changes with 20 users

Nothing in the application's features or protections: the same read-only guards, access roles, token
verification, firewall and tunnel. The only numbers that changed are the limits in `09-user-access-plan.md`
(`ACCESS_SEAT_LIMIT=20`, `ACCESS_SEAT_WARN=16`, `ACCESS_OTHER_SEATS=8`) and the VM size default in
`deploy/vm/azure/provision-vm.ps1` (`Standard_B2ms`; pass `-VmSize Standard_B4ms` to keep the larger size).
