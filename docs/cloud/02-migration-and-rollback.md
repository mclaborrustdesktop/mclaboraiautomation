# Cloud database migration and rollback plan

For the recommended design (SQL Server on an Azure VM, `01-cloud-architecture.md`). Nothing here has been
started. Every step that touches LIVE-HOST or moves real records needs the explicit go-ahead named in column
"needs". Real records are never copied to the cloud before step M4.

## Phase 0 - prerequisites (no real data involved)

| # | Step | Needs |
|---|---|---|
| P1 | Live database confirmed (`docs/production/15`, staff-PC check + owner's statement) | staff member, owner |
| P2 | Azure subscription in the company's name, region chosen, budget alert set | owner |
| P3 | `deploy/cloud/azure/provision.ps1` executed for **staging** (`rg-mclabor-staging`): VNet, SQL VM (Developer edition), Container Apps, Key Vault, logs, VPN gateway | owner's go-ahead to spend; Azure administrator |
| P4 | Site-to-site VPN between the office router and the VNet; from an office PC the staging VM's private address answers on 1433 | network administrator |
| P5 | Container images built from this repository and started with the **DEMO profile** in the cloud; `/api/ready` answers; sign-in through Microsoft 365 works for one test account | none (synthetic data) |

## Phase 1 - staging rehearsal with the restored copy (real data, test environment)

| # | Step | Needs |
|---|---|---|
| M1 | A **copy-only** backup with checksum of the restored copy on DEV-PC (`tools/prod-check/backup/1-...sql`, which is exactly this) | approval to run it (it reads the copy, changes nothing) |
| M2 | Upload the `.bak` to a private blob container of the staging resource group over HTTPS (`azcopy` with a short-lived SAS token); delete the local upload copy afterwards | **approval to move real records to the cloud (staging)**: this is the first time employee records leave the office |
| M3 | Restore on the staging VM (`RESTORE DATABASE McLabor FROM URL`), `CHECKDB`, recreate the `mclabor` login for Access and `mclabor_web_read` with `proposed-grants.sql` (guard changed to the VM's name) | Azure administrator |
| M4 | Point the staging website at it (`deploy/cloud/backend.env`, `DATA_SOURCE=staging`); `check_readonly.py` with a `prodcheck.env` for the VM must end READ-ONLY CONNECTION VERIFIED; `app.livecheck`, `contact_check.py`, `search_timing.py`, `loadtest.py` with 35 and 60 users | none further |
| M5 | Access rehearsal: on one office PC, a **copy** of the Access file relinked to the staging VM over the VPN; open every form and report used daily; time them; QuickBooks tasks from that PC | one staff member, half a day |
| M6 | Full-text index on the staging VM (`proposed-fulltext.sql`), repeat M4's timings | approval for the index |
| M7 | Decision: go / no-go for production, with the measured Access timings in hand | owner |

## Phase 2 - production cut-over (the live database moves)

Planned for an evening or a weekend. Estimated downtime for the office: 1 to 3 hours (backup, upload, restore,
relink, checks). Rollback at any point returns to LIVE-HOST unchanged.

| # | Step | Needs |
|---|---|---|
| C1 | Freeze: everyone out of Access (`06-access-maintenance-checklist.md`); `list-active-sessions.sql` shows nobody; LIVE-HOST's SQL login `mclabor` disabled for the duration **(the only change made to LIVE-HOST before the move, reversible with one statement)** | owner's go-ahead; LIVE-HOST administrator |
| C2 | Full backup with checksum of the live `McLabor` on LIVE-HOST, verified (`RESTORE VERIFYONLY`); a second copy kept on an office disk | LIVE-HOST administrator |
| C3 | Upload to the production blob container; restore on the production VM; `CHECKDB`; row counts of the four main tables compared with LIVE-HOST; logins recreated; `mclabor_web_read` created; compatibility level unchanged | Azure administrator |
| C4 | Access files on every office PC relinked to the production VM (Linked Table Manager; a script is possible with the DAO `TableDef.Connect` property); one real task per PC | whoever supports the PCs |
| C5 | Production website pointed at the VM (`backend.env`, `DATA_SOURCE=production`), read-only, access lists filled, `/api/ready` 200, sign-in test by two staff | none further |
| C6 | LIVE-HOST's `McLabor` set to **READ_ONLY** (not deleted): the office's emergency copy and the rollback source | LIVE-HOST administrator |
| C7 | First working day: a person on call; `az containerapp logs` and the SQL VM's error log watched; the change log of the website reviewed | - |

## Rollback

| When | How | Time |
|---|---|---|
| Before C3 finishes | Nothing moved: re-enable `mclabor` on LIVE-HOST, unfreeze | minutes |
| After C4, same day, no new data of value in the cloud | Relink Access to LIVE-HOST, set LIVE-HOST's database READ_WRITE again, re-enable the login; the cloud copy is discarded | under an hour |
| Days later, with new data in the cloud | Copy-only backup on the VM (SQL Server 2022 Standard writes a backup that **LIVE-HOST's 2019 cannot restore**: either the VM runs SQL Server **2019** for the first months, which this plan recommends for exactly this reason, or the data is moved back with a schema+data export) | hours |

Decision for the owner embedded here: run SQL Server **2019 Standard** on the VM until the rollback option is no
longer wanted, then upgrade in place. The `.bak` compatibility rule (restore only to the same or a newer version)
is what makes this matter.

## What is never done

Records are never uploaded by hand, by e-mail or by any service other than the encrypted backup transfer; nothing
is sent to an AI service; LIVE-HOST is not modified before C1, and after the move it keeps a read-only copy until
the owner decides to retire it (and its backups) deliberately.
