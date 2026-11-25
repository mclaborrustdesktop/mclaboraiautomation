# 15. Railway staging: restriction, preserved state and the recovery procedure (2026-11-25)

Two fresh Railway trial workspaces were restricted within minutes of the first multi-service deployment, both with
the same message. This page records what exists, what the restriction says, where it can be appealed, and the exact
order in which staging is brought back once the restriction is lifted. Synthetic data only; no office connection.

## 1. The restriction

Exact text returned by every deployment or source-connect command:

```
We limited this workspace after detecting unusual activity. Upgrade to a paid plan to lift this restriction automatically.
```

What happened both times: the services built and became healthy (frontend `/healthz` ok, backend `/api/ready` ok,
staging on PostgreSQL, search-only, sign-in required), the synthetic load started through the website address, and
about three minutes later Railway removed every deployment of the project (backend, frontend and PostgreSQL). Charges:
0 USD on both accounts; the 5 USD trial credit is intact.

## 2. Appeal / review (what Railway documents and what its staff answer)

- Railway's [Trust and safety](https://docs.railway.com/platform/trust-and-safety) page: some restrictions have a stated
  resolution (this one says "upgrade to a paid plan"); others need an approved appeal. A workspace admin files an
  appeal from **Workspace Settings -> Standing** (`railway.com/workspace/restrictions`). A restriction stays in effect
  while the appeal is reviewed; a restriction can generally be appealed **once** and the decision is final.
- A useful appeal explains what the workload does, addresses the stated reason, and lists the changes made. For this
  project: a search-only staff website for a 20-user company, three services (PostgreSQL, FastAPI, Next.js) deployed
  from a public GitHub repository with the Railway CLI; synthetic data; no outbound traffic except the Microsoft
  package repository during the image build; the "unusual activity" was the CLI-driven creation of the services.
- Forum answers from Railway staff on similar cases ([1](https://station.railway.com/questions/workspace-restricted-suspicious-activi-f42c3aa8),
  [2](https://station.railway.com/questions/formal-appeal-remediation-plan-worksp-6f5b6222),
  [3](https://station.railway.com/questions/railway-trial-plan-abuse-restriction-pre-ee2c8325),
  [4](https://station.railway.com/questions/workspace-restricted-review-request-5be00ea9)): trial eligibility is
  automated (GitHub account age and activity) and is not re-evaluated by hand; for some restrictions staff state that
  a paid plan does *not* lift it and only the appeal can; for others the only offered path is the paid plan. The
  support form is "Get Help with Railway" on [Central Station](https://station.railway.com).
- The public API exposes no appeal or standing field; the appeal is a dashboard action by the workspace admin
  (brian@mclabor.com for the current workspace).

Decision for the owner: file the one appeal from the Standing page (free), and/or approve the Hobby plan
(5 USD per month plus usage, card required). Nothing is created or upgraded without that approval.

## 3. What is preserved in the current project (account brian@mclabor.com, workspace "mclaborsources's Projects")

| Item | State | Notes |
|---|---|---|
| Project `mclabor-staging` | exists | id `f0b04765-ffb0-443f-9b81-75a8c46a56d4`; Railway's default environment is named `production` (id `5a9e21d9-d1be-4843-bf0c-fbf9bc502978`); the application runs as **staging** (`DATA_SOURCE=staging`) |
| `Postgres` service | deployment REMOVED, service and **volume kept** | `postgres-volume`, state READY, 83.6 of 500 MB used, mounted at `/var/lib/postgresql/data`: the mirror tables, the first synthetic batches and the sign-in store are on it. Variables `DATABASE_URL`, `PGPASSWORD`, ... still set. No TCP proxy, no domain |
| `backend` service | deployment REMOVED, settings kept | source `mclaborrustdesktop/mclaboraiautomation` branch `main`; root `/`; Dockerfile `deploy/railway/backend.Dockerfile`; health `/api/ready`; all 21 variables set (`STAGING_DATABASE_URL`/`WEB_AUTH_DATABASE_URL` = `${{Postgres.DATABASE_URL}}`, `SITE_MODE=search-only`, `ACCESS_MODE=login`, `WEB_ADMINS=ARI`, `JWT_SECRET`, `SYNC_API_KEY`, `WEB_BOOTSTRAP_PASSWORD`, `CORS_ORIGINS`, ...). No domain |
| `frontend` service | deployment REMOVED, settings kept | same source; root `frontend`; Dockerfile `Dockerfile`; health `/healthz`; variables `BACKEND_INTERNAL_URL=http://backend.railway.internal:8000`, `PORT=3000`, `HOSTNAME=::`; public HTTPS domain `https://frontend-production-8f250127.up.railway.app` |
| Secrets | set in Railway; local copies only in the session's temporary folder | if the local copies are gone, generate new values and set `JWT_SECRET`, `SYNC_API_KEY`, `WEB_BOOTSTRAP_PASSWORD` again (`python -c "import secrets;print(secrets.token_urlsafe(48))"`); the agent needs the sync key, the first sign-in needs the bootstrap password |
| Old workspace (kei29miz) | restricted, project `mclabor` | not used any more; can be deleted from its dashboard later |

Railway free-trial limits that matter: 2 projects, 5 services per project, 500 MB volumes, 1 GB memory per container,
2 service domains. The staging stack fits.

## 4. Recovery, in order, once the restriction is officially lifted

Checks before anything is deployed (read-only):
```
railway whoami                                   -> brian@mclabor.com
railway status --json                            -> volume postgres-volume READY
railway variable list --service backend --json   -> names only; never paste the output anywhere
```
1. **PostgreSQL first.** `railway redeploy --service Postgres -y`. Wait for SUCCESS. The volume re-attaches; nothing is
   re-created. Verify from the backend later (`/api/ready` reports `database: ok`).
2. **Backend.** `railway redeploy --service backend --from-source -y` (builds the latest `main`). Wait for SUCCESS and
   `https://<frontend domain>/api/ready` = `ready` after step 3. If the sign-in store tables already exist (they do), the
   start-up tolerates it.
3. **Frontend.** `railway redeploy --service frontend --from-source -y`. Then `/healthz` = ok, `/api/health` shows
   `environment: staging, database: postgres, site_mode: search-only, access_mode: login, writes: false`.
4. **Verify secrets.** `railway variable list --service backend --json` must still list `JWT_SECRET`, `SYNC_API_KEY`,
   `WEB_BOOTSTRAP_PASSWORD`; the local copies must match (the agent's bootstrap call answers 401 if the key differs; set a
   new key on both sides in that case).
5. **Synthetic import, safely restarted.** The interrupted run (run 1) is recorded on the mirror as not finished; the
   agent's state file remembers only acknowledged rows. Run again with `--full` so every table is compared and sent
   again (rows already present are upserted, nothing is deleted by a partial state):
   ```
   backend\.venv\Scripts\python.exe -m app.synthdb "sqlite:///<folder>/synthetic-source.db" 0.2      (only if the file is gone)
   set SYNC_API_KEY=<the key>
   backend\.venv\Scripts\python.exe -m app.syncagent run --source-url sqlite:///<folder>/synthetic-source.db --api https://<frontend domain> --bootstrap --full --force --state <folder>\agent-state.db --log-file <folder>\sync.log
   ```
   `--force` clears the "still running" mark of the interrupted run. Expect ~150 batches; exit code 0.
6. **Tests.** Health, anonymous and forged requests refused, sign-in (wrong password 401; the bootstrap password only for
   `ARI` and only once; `must_change_password: true`), employees/customers/projects/tracking lists from the mirror, AI
   search, `/api/sync/status` with a last successful run, every Add/Edit/Delete refused with 423 even for the
   administrator, no SSN/bank fields in any payload, only the frontend has a public domain. The script used for this is
   kept with the session notes; it is a plain `httpx` script against the public address.
7. **Hand-over.** Give the owner the address and the one-time bootstrap password; after the first sign-in and password
   change, delete `WEB_BOOTSTRAP_PASSWORD` (`railway variable delete WEB_BOOTSTRAP_PASSWORD --service backend`).

Do not: retry blocked deployments in a loop (each attempt is logged against the workspace), create another trial
account or project, add a card or change the plan without the owner's approval, expose the backend or PostgreSQL,
connect to the office servers, or load anything but the synthetic file.
