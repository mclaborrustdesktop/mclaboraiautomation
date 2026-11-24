# 3. SQL Server 2019 update plan

> **Which database?** Names are defined in `docs/environments.md`. DEV-PC holds a **restored copy** (staging), not the live database. This document was first written believing DEV-PC was live. Use it as written for the copy; for the possible live database on LIVE-HOST see `09-plan-connect-live-database.md`.

Nothing has been downloaded or installed. Installing needs the owner's approval.

## Where the server is today (read from this PC)

SQL Server 2019 **Express**, instance `SQLEXPRESS`, version **15.0.2000.5**. That is the original 2019 release; no
update has ever been installed. Windows 11 Pro 64-bit.

## What Microsoft currently offers

Looked up on 2026-11-20 through a web search of Microsoft's own pages. I read the search results, not the full
pages, so confirm the numbers on the build-versions page on the day you install.

| Update | Build | Released | What it is |
|---|---|---|---|
| CU32 (KB5054833) | 15.0.4430.1 | 2025-02-27 | The last cumulative update for SQL Server 2019 |
| **Security update for CU32 (KB5132745)** | **15.0.4510.2** | **2026-11-10** | Newest security update for servers on the cumulative-update line |
| Security update for GDR (KB5132751) | 15.0.2210.4 | 2026-11-10 | Newest security update for servers that install security fixes only |

Microsoft publishes a new security update for SQL Server 2019 most months (March, April, July, October and November
2026 all appear in the results), so the newest one will change.

Sources:
- https://learn.microsoft.com/en-us/troubleshoot/sql/releases/sqlserver-2019/build-versions
- https://support.microsoft.com/en-us/servicing/sql/sql-server-2019/cumulative-update/kb5132745-cu32-gdr-november-2026
- https://support.microsoft.com/en-us/servicing/sql/sql-server-2019/general-distribution-release/kb5132751-november-2026
- https://support.microsoft.com/en-us/help/5054833
- https://www.microsoft.com/en-us/download/details.aspx?id=108900

## Two possible routes

| | Route A: cumulative line (recommended) | Route B: security fixes only |
|---|---|---|
| Install | KB5132745 (build 15.0.4510.2) | KB5132751 (build 15.0.2210.4) |
| Contains | All reliability fixes since 2019 plus all security fixes | Security fixes only |
| Size of change | Larger | Smallest possible |
| Later updates | Each new "security update for CU32" | Each new "security update for GDR" |

From memory, not confirmed in today's search: a server that moves to the cumulative line stays on it, and cumulative
updates apply to Express Edition. Also not confirmed: whether KB5132745 installs directly on the original release or
needs CU32 (KB5054833) first. The "Prerequisites" section of the KB article answers that; read it before starting.

Recommendation: Route A. The server has had no fixes of any kind for years, and Microsoft's general advice is to
run the latest cumulative update. Route B is the cautious alternative if the smallest possible change is preferred.

## Compatibility

- **Access application:** an update inside SQL Server 2019 does not change the database format or its compatibility
  level, so Access should behave the same. This has not been tested here; testing it is step 6 below.
- **Website:** uses ODBC Driver 17, which works with every SQL Server 2019 build.
- **Certificate:** update first, certificate afterwards, on a different day if possible.

## Plan (each step needs doing by a Windows administrator; the install needs approval)

1. Complete `01-backup-and-restore-checklist.md`, including the restore test.
2. Follow `06-access-maintenance-checklist.md` so nobody is working in Access.
3. Download the update from the Microsoft link in its KB article. Check the file name matches the KB number
   (for example `SQLServer2019-KB5132745-x64.exe`).
4. Right-click the file > Run as administrator. Select the `SQLEXPRESS` instance. Accept the defaults.
5. Expect **5 to 20 minutes** during which SQL Server is stopped. Restart Windows if asked.
6. Afterwards: in SSMS run `SELECT @@VERSION;` and check the build number. Open Access and do one normal task from
   start to finish.
7. Run `backend\.venv\Scripts\python.exe tools\prod-check\check_readonly.py --preflight`.

## Rollback

- Windows Settings > Apps > Installed apps > "View installed updates" (or Control Panel > Programs > View installed
  updates): select the SQL Server update > Uninstall. SQL Server stops again while it is removed.
- If the database itself is damaged, restore from the backup made in step 1. That loses everything entered after
  the backup, so it is the last resort.

## Afterwards

Turn on "Receive updates for other Microsoft products" in Windows Update (Advanced options), or check Microsoft's
page every month. Otherwise the server falls behind again.
