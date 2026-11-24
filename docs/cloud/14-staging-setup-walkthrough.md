# 14. Staging set-up walkthrough: GitHub, Railway, Cloudflare Access, backups (synthetic data only)

One step at a time, each with what it costs. Nothing in steps 1-3 is paid; step 4 (Railway) is the first paid
resource and is not started without the owner's approval. No connection to LIVE-HOST, no real records anywhere.

## Expected charges

| Item | Charge | When it starts |
|---|---|---|
| Git for Windows on DEV-PC | free | step 0 |
| GitHub private repository (personal or organization account, free plan) | free | step 1 |
| Cloudflare account, DNS for the company domain, Access (up to 50 users), one service token | free | step 2 |
| Domain name (only if the company does not already have one in Cloudflare) | about 10 USD per year | step 2 |
| Cloudflare R2 bucket for encrypted backups (10 GB and 1 million writes a month free; a payment method must be on file) | free | step 3 |
| **Railway Hobby plan** | **5 USD per month, includes 5 USD of usage** | **step 4, after approval** |
| Railway usage for STAGING with synthetic data (backend, frontend, Postgres, nightly backup) | about 15-20 USD per month while it runs; stop the services when not testing and it falls to about 2 USD (volume only) | step 4 onward |
| Railway usage for PRODUCTION later (not now) | about 18 USD per month on top | not yet |

Staging on its own, running all month: **about 20-25 USD per month**. Stopped between test days: **about 7 USD**.

## Step 0: Git on this PC (needs the owner's "yes" to install software)

DEV-PC has no Git. The one-line install (free, standard tool): `winget install --id Git.Git -e --source winget`.
After it: `git --version`. Alternative with a graphical window: GitHub Desktop (also an install).

## Step 1: the private repository (free)

1. On github.com, signed in to the company account: **New repository** -> name `mclabor-ai-automation` ->
   **Private** -> no README, no .gitignore (the project has its own) -> Create.
2. On this PC, in the project folder (I run these once Git exists; the push asks for the GitHub sign-in in a window):
   ```
   python tools\repo-check\scan_repo.py     -> must end with RESULT: CLEAN
   git init
   git add .
   git status                               -> no .env, .db, .dpapi, reports (the .gitignore keeps them out)
   git commit -m "MC Labor AI Automation: search-only mirror, sync agent, Railway configuration"
   git branch -M main
   git remote add origin https://github.com/<account>/mclabor-ai-automation.git
   git push -u origin main
   ```
3. On github.com: Settings -> General: confirm **Private**. Settings -> Collaborators: only the people who need it.
   Settings -> Code security: enable **Secret scanning** and **Push protection** (free on private repositories
   for personal accounts; on organizations it needs GitHub Advanced Security - skip if not available; the local
   scan runs before every push anyway).

## Step 2: Cloudflare (free)

1. Account at dash.cloudflare.com (the company's e-mail). Add the company domain (or register one, about 10 USD
   per year) and follow the nameserver change at the registrar. Wait until the zone shows **Active**.
2. **Zero Trust** (left menu) -> choose the **Free** plan (up to 50 users) -> team name, e.g. `mclabor`
   (this gives `mclabor.cloudflareaccess.com` = `CLOUDFLARE_ACCESS_TEAM_DOMAIN`).
3. Zero Trust -> Settings -> Authentication: add the identity provider the staff use (Google Workspace or
   Microsoft Entra ID; or One-time PIN by e-mail to start).
4. Zero Trust -> Access -> Applications -> **Add an application** -> Self-hosted:
   name `MC Labor staging`, domain `staging.<domain>`; policy **Allow** for the staff group (for staging: the test
   users' e-mails only); session 8 hours. Save, then open the application and copy the **Application Audience
   (AUD) tag** = `CLOUDFLARE_ACCESS_AUD`.
5. Zero Trust -> Access -> **Service Auth -> Service Tokens** -> create `mclabor-sync-agent`; copy the Client ID
   and the Client Secret ONCE (the secret goes into `store-sync-secrets.ps1` on the office PC, never into a file).
6. On the application from step 4, add a second policy: **Service Auth**, include the service token, path
   `/api/sync/*` (Cloudflare: add a path to the application for the policy to apply to).

## Step 3: the backup bucket (free tier; a payment method is required on the account)

Cloudflare -> **R2** -> Create bucket `mclabor-backups` (location: automatic, North America). R2 -> **Manage R2 API
tokens** -> create a token with **Object Read & Write** on this bucket only; copy the Access Key ID, the Secret
Access Key and the endpoint URL (`https://<account-id>.r2.cloudflarestorage.com`). Add a lifecycle rule: delete
objects older than 60 days (the backup script keeps 35; this is the belt).

## Step 4: Railway (PAID: 5 USD per month plus usage) - only after the owner's approval

1. railway.com -> sign up with the GitHub account of step 1 -> **Hobby** plan (5 USD per month; card on file).
2. New project `mclabor` -> **Deploy from GitHub repo** -> choose the repository -> it creates one service; rename
   it `frontend`, Settings -> Root directory `frontend`. Set variables from `deploy/railway/env/frontend.env.example`.
3. **+ New -> Database -> PostgreSQL**. Leave the TCP proxy off.
4. **+ New -> GitHub repo** again for `backend`: Root directory `/`, Settings -> Config-as-code path
   `deploy/railway/backend.railway.json`. Variables from `deploy/railway/env/backend.staging.env.example`:
   the two Railway references for the database, the Cloudflare values from step 2, `JWT_SECRET` and `SYNC_API_KEY`
   generated with `python -c "import secrets;print(secrets.token_urlsafe(48))"` and **sealed**.
5. Rename the environment to `staging`. Deploy both services; wait for the health checks (`/api/ready`, `/healthz`).
6. Custom domain: frontend service -> Settings -> Networking -> Custom domain `staging.<domain>`; add the CNAME
   Railway shows in Cloudflare DNS with the proxy ON (orange cloud). Remove the Railway-generated domain.
7. **+ New -> GitHub repo** for `backup`: Root directory `deploy/railway/backup`, variables from
   `deploy/railway/env/backup.env.example` (bucket values from step 3, passphrase generated and sealed, and written
   into the password safe). It runs at 07:00 UTC by its cron setting.

## Step 5: synthetic data and tests

From this PC (DEMO keeps running), with the staging values in `tools\sync\sync.env` pointing at a **synthetic
source**, not an office server:
```
backend\.venv\Scripts\python.exe -m app.synthdb "sqlite:///C:/MCLabor/synthetic-source.db" 0.2
backend\.venv\Scripts\python.exe -m app.syncagent run --source-url sqlite:///C:/MCLabor/synthetic-source.db --api https://staging.<domain> --key-env SYNC_API_KEY --cf-client-id <id> --bootstrap
```
Then: sign in through Cloudflare as a test user, searches, the banner shows "Information as of", the Users page
shows the roster against 20, every Add/Edit/Delete is refused, `deploy\vm\smoke.ps1 -Site https://staging.<domain>
-Expect staging`, the 20-user load test, a run of the backup service by hand and `restore-test.sh` once.

## Step 6: later, with separate approvals

The office agent against the DEV-PC copy into a local PostgreSQL (rehearsal, no cloud); the read-only login on
LIVE-HOST by the administrator; the first real copy to a **production** environment.
