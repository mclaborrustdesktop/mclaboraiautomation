# Office synchronization agent (one way: office SQL Server -> cloud mirror)

The office SQL Server and the Access application stay the primary system. Twice a day this agent reads the 33
approved tables (approved columns only, no sensitive columns) with the restricted read-only login and sends what
changed to the cloud website's ingest API. Nothing flows back. Design: `docs/cloud/13-one-way-sync.md`.

| File | Role |
|---|---|
| `sync.env.example` | settings (which office server, the website's address, the Cloudflare service token id); copy to `sync.env` |
| `store-sync-secrets.ps1` | stores the SQL password, the sync key and the service token secret encrypted with DPAPI for the task's Windows account |
| `run-sync.ps1` | one run (`-DryRun`, `-Full`, `-Bootstrap`, `-Tables`, `-Limit`); loads the settings and secrets into its own process only |
| `register-sync-task.ps1` | the Windows scheduled task (`-Times "06:00,12:30"` by default; `-Remove`) |
| `backend/app/syncagent.py` | the agent itself (`python -m app.syncagent run ...`, `status`) |

## Set-up on the office PC that runs it (DEV-PC or another PC that can reach the SQL Server)

1. The read-only login `mclabor_web_read` exists on the server (`tools/prod-check/proposed-grants*.sql`, by the administrator).
2. Copy `sync.env.example` to `sync.env`; fill in the server, the website address and the service token id.
3. `store-sync-secrets.ps1 -Environment production` (as the account that will run the task).
4. `run-sync.ps1 -Bootstrap -DryRun` (creates the mirror tables, compares, sends nothing), then `run-sync.ps1` for the first full copy.
5. `register-sync-task.ps1`. Check `%LOCALAPPDATA%\MCLabor\sync\logs\sync-<date>.log` after the first scheduled run.

The website's status page (administrators) shows the runs as the cloud saw them; `python -m app.syncagent status`
shows them as this PC saw them.

Exit codes of `run-sync.ps1`: 0 = done; 2 = done but some deletions were **skipped** by the guard (a table shrank
by more than 10 % or came back empty: check the office database, then rerun with `-AllowMassDelete` if it is
right); 1 = failed (see the log; the next run resumes). A limited run (`-Limit`, `-Tables`) never deletes anything.
