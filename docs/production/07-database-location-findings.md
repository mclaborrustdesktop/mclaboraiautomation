# 7. Which SQL Server does the Access application use?

> **Update 2026-11-23:** all eleven copies of the Access application on this PC were inspected
> (`tools\prod-check\inspect-access-links.ps1`) and LIVE-HOST was probed read-only (`find-live-server.ps1`). Every
> release version from 2022 to May 2026 links only to `<live-host-ip> / McLabor`; a SQL Server listens there on TCP 1433.
> The live database is therefore `McLabor` on `LIVE-HOST\SQLEXPRESS`, subject to one staff-PC confirmation
> (`staff-pc-check.ps1`). Details and the connection plan: `15-live-database-and-production-connection.md`.

Investigated 2026-11-20 with read-only methods. Nothing was opened in Access, no table was read, and nothing was
changed. Method: the Access files were read as plain bytes and searched for connection-string keywords only;
password values were not printed. Machine names were matched to addresses with name lookups, without connecting to
any SQL Server.

## Machines

| Address | Machine | Evidence |
|---|---|---|
| `<dev-pc-ip>` | **DEV-PC** (this PC) | This PC's own network address; name lookup both ways |
| `<live-host-ip>` | **LIVE-HOST** | Name lookup both ways; the address answered on the office network |

No SQL client aliases exist on this PC that would redirect either name.

## What the Access files on this PC point to

Two Access files are on this PC's Desktop, both last changed 2026-11-19 19:00:
`2026 11-06 MLS 5-44-0.accdb` (601 MB) and `Database.mdb` (137 MB).

| Linked to | Database | Sign-in | Found in |
|---|---|---|---|
| `<dev-pc-ip>` = DEV-PC | `McLabor` | SQL login `mclabor`, password stored in the file | Both files (most of the links) |
| `<live-host-ip>` = LIVE-HOST | `McLabor 20260811 Development` | SQL login `mclabor`, password stored in the file | Both files (61 mentions each) |
| QuickBooks (`QODBC`, data source "QuickBooks Data") | - | - | Both files |

Driver named in the links: `SQL Server Native Client 11.0`. The server is always given as an IP address; the names
`LIVE-HOST`, `DEV-PC` and `SQLEXPRESS` do not appear anywhere in either file.

## What this proves and what it does not

Proven:

- The Access files **on this PC** point at this PC's restored copy (`<dev-pc-ip>`, database `McLabor`) and at a
  **development** database on LIVE-HOST.
- Neither file contains a link to a database called `McLabor` on LIVE-HOST.
- The copy on DEV-PC came from `McLabor` on `LIVE-HOST\SQLEXPRESS`, backed up 2026-11-13 17:00. That database was
  created in 2022.

Not proven:

- **Which database the office staff use every day.** The files on this PC look like a developer's copies, re-pointed
  at the local copy. The staff's own Access file is on other PCs and was not inspected.
- Which of the links in these two files are current. A byte search also finds old links that Access has not yet
  cleaned out of the file, so the development links may be left-overs.

Conclusion: **not conclusive for the live system.** The most likely picture is: live database = `McLabor` on
LIVE-HOST (`<live-host-ip>`); this PC = a test copy with a test copy of the Access application. That needs one manual
check on a staff PC.

## Manual check (5 minutes, changes nothing)

On a PC where someone uses the Access application for real work:

1. Find the Access file they open (right-click their shortcut > Properties > "Target" shows the file).
2. Hold down the **Shift** key and double-click that file. Keep Shift held until Access has opened. This stops the
   application's start-up screens.
3. Click the **External Data** tab, then **Linked Table Manager**.
4. Each group in the list shows a line containing `SERVER=...;DATABASE=...`. Write down the SERVER and DATABASE
   values. Do not click "Relink", "Edit" or "Refresh".
5. Close the window, then close Access. If asked to save anything, choose **No**.

Expected if the picture above is right: `SERVER=<live-host-ip>` and `DATABASE=McLabor`.

If "Linked Table Manager" is not available: press **Ctrl+G**, type `? CurrentDb.TableDefs("tblEmployee").Connect`
and press Enter. The line that appears contains the server and database. Do not copy the password out of it.

## Evidence needed to call a server "live"

All of these, written down with the date and who checked:

| # | Evidence | How to get it | Changes anything? |
|---|---|---|---|
| 1 | The SERVER and DATABASE in the linked tables of the Access file a staff member opens for real work | Manual check above, on a staff PC | No |
| 2 | The same on a second staff PC | Manual check above | No |
| 3 | Which file their shortcut opens, and its date | Right-click the shortcut > Properties | No |
| 4 | People are connected to that database during working hours | On that server, as a SQL Server administrator: `tools\prod-check\list-active-sessions.sql` | No |
| 5 | A record entered today in Access exists in that database | The staff member tells you a job or note they added today; an administrator looks it up there | No |
| 6 | The owner states in writing which server holds the live database | Ask | No |

Items 1 and 4 together are strong. Item 5 settles it. Evidence that is **not** enough on its own: the server's
name, the 2026-11-13 backup having come from it, or the Access files on DEV-PC.

## Things the owner should know

- The SQL login `mclabor` and its password are stored readably inside the Access files. Anyone who has a copy of an
  Access file has that login. Copies exist on this PC's Desktop and in its OneDrive folder.
- The same login name exists on this PC's copy of the database.
- SQL Server on this PC accepts network connections on port 1433 from other machines (firewall rules not checked).
- A development database, `McLabor 20260811 Development`, exists on LIVE-HOST alongside the live one.
