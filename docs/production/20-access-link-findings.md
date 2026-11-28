# 20. The Access application's connection on the office PC, and what the sync agent can reuse (2026-11-27)

Read-only inspection of the Access files on the office PC (`DEV-PC`), with the saved credentials never printed, stored
or passed anywhere. Access was not started; the newest file was opened read-only through the Access ODBC driver.

## Findings

| Question | Answer |
|---|---|
| Which SQL Server does the Access application on this PC link to? | `<live-host-ip>` (the live server), database **`McLabor 20260811 Development`**, 60 linked tables; and `<dev-pc-ip>` (this PC), database `McLabor` (the restored copy), 13 linked tables. QuickBooks (QODBC) links aside. |
| Does it link to the production database `McLabor` on the live server? | **No.** Not one link in the files on this PC points at `<live-host-ip>` / `McLabor`. This PC holds a development front-end; the staff PCs' releases link to production (`15`, section A). |
| Which login do the links use? | the SQL login **`mclabor`**, with its password saved inside the Access file (that is why Access never asks). |
| Can the saved links read? | Yes: `SELECT COUNT(*) FROM [tblFeature]` through the Access driver answered (1,126 rows). The 33 approved tables and all 288 approved columns are visible by name through the links, split between the two targets. |
| Can the sync agent use "that connection"? | Not as it is. The agent speaks to SQL Server directly (keyset paging, server identity check, SELECT-only guard); the only thing the Access links hold that the agent lacks is the `mclabor` credential, and it is not to be extracted from the file. Reading through Access's own engine would mean rewriting the agent for the Access SQL dialect and would still reach only the development database from this PC. |
| Does `mclabor` reach production? | Evidently yes: the staff PCs use it for `McLabor` on the live server, and the 2026-11-13 production backup was taken by it (`19`). Its rights are at least backup rights, so it is a write-capable login, not a read-only one. |
| TLS to the live server | The live instance has no certificate the office PC trusts; the agent refuses an unverified certificate by default. A waiver setting now exists (`PRODUCTION_DB_TLS_WAIVER`, owner's written statement) so the agent can connect encrypted but unverified, the level Access itself works at (unencrypted). |

## Result: CLIENT APPROVAL REQUIRED (no server administration, no Remote Desktop, no password in chat)

> **Superseded on 2026-11-27 (evening):** the owner declined both the shared `mclabor` login and the TLS waiver.
> The path now is the client-performed one-time setup of `21-client-one-time-setup.md` (dedicated read-only login,
> verified certificate). The text below is kept as the record of the alternative that was considered.

The shortest path that reuses everything already built:

1. **The holder of the `mclabor` password** (the client; it is the Access application's login) types it once at the hidden
   prompt of `tools\sync\store-sync-secrets.ps1 -Environment production` on this PC. It is stored encrypted (DPAPI)
   for the Windows account that runs the agent; nobody else sees it. `PRODUCTION_DB_USER=mclabor` in `sync.env`.
2. **The owner's written TLS waiver** in `sync.env`: `PRODUCTION_DB_TRUST_SERVER_CERTIFICATE=true` and
   `PRODUCTION_DB_TLS_WAIVER=<who approved, when>`, until a trusted certificate can be installed on the live server.
3. Then, automatically: the agent's dry run against production (read-only, counts only), the Railway production
   project (its own approval), the import (its own approval), reconciliation, the schedule (its own approval).

What this trades away compared with the dedicated `mclabor_web_read` login (`17`, `18`): the agent runs under a login
that *could* write and *can* see the 17 sensitive columns; the protection is then the agent's own SELECT-only
statement guard, its approved-column list (sensitive names refused by list and by pattern) and the server identity
check, instead of server-side DENYs. The dedicated login remains the recommended end state whenever the client's
administrator has ten minutes; everything for it is prepared and nothing in this path prevents switching later (one
line in `sync.env`, one stored password).

Not done and not needed for this path: no login created, no permission changed, no backup taken, no server setting
changed. The backup gate of `19` still applies before the first write-capable step on the live server, which this path
does not contain.
