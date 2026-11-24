# Railway + PostgreSQL deployment (prepared 2026-11-24; nothing deployed, nothing purchased)

> **First release (decided 2026-11-24): the office SQL Server and Access stay the primary system.** The Railway
> database is a **search-only mirror** refreshed twice a day by the office agent (`docs/cloud/13-one-way-sync.md`,
> `tools/sync`). The services below are the same; the backend runs with `SITE_MODE=search-only` and `SYNC_API_KEY`,
> and the Cloudflare Access application gets a second policy for the agent's **service token** on `/api/sync/*`.
> No migration of data happens: the mirror is filled by the agent, and rebuilt by it if ever lost.

Three Railway services and a cron service in one project, two environments (staging with synthetic data first;
production only after the owner approves pointing the agent at the live server), Cloudflare Access in front for
sign-in without a website login screen, encrypted backups outside Railway.

```
 browser ──HTTPS──> Cloudflare (DNS proxy + Access policy: 20 named employees) ──> Railway edge ──> frontend (Next.js)
                                                                                                      │ /api/*  private network
                                                                                                      ▼
                                                                                      backend (FastAPI) ──> Postgres (Railway)
                                                                                                                 ▲
                                                                                      backup (cron, pg_dump + AES-256) ──> R2/S3 bucket
```

| Service | Root directory | Config | Image | Public? |
|---|---|---|---|---|
| `frontend` | `frontend` | `frontend/railway.json` | `frontend/Dockerfile` | yes: custom domain only, behind Cloudflare Access |
| `backend` | `/` (repository root) | `deploy/railway/backend.railway.json` (set as the service's config path) | `deploy/railway/backend.Dockerfile` | **no**: private network only (`backend.railway.internal`) |
| `Postgres` | Railway template | - | Railway's PostgreSQL 16 | **no**: private URL only; no TCP proxy |
| `backup` | `deploy/railway/backup` | `deploy/railway/backup/railway.json` (cron 07:00 UTC) | `deploy/railway/backup/Dockerfile` | no |

## 1. Why this shape

* The browser only ever talks to the frontend's address. Its `/api/*` route handler (`frontend/src/app/api/[...path]/route.ts`)
  forwards each request over Railway's private network to the backend and passes on the sign-in headers
  (Cloudflare's token, the website's bearer token). The backend has no public domain at all.
* Cloudflare Access signs every request with a token for this application; the backend verifies the signature,
  audience, issuer and expiry (`GATEWAY_PLATFORM=cloudflare-access`). `GATEWAY_TRUSTED_PROXIES=any` is accepted only
  with this platform, because Railway's own edge is the visible client address and the token is the proof.
  Hitting the frontend's Railway-generated `*.up.railway.app` address directly yields 401 from the backend for every
  API call (no token); that address is removed after the custom domain works, leaving the Cloudflare route only.
* The Postgres service is reached by its private URL; Railway's "TCP proxy" (public port) is never enabled.
  Schema and synthetic data are applied from this PC through a temporary public URL **or** from a one-off run of
  the backend service (`python -m app.pgschema apply ...` on the private URL); the second is the default.
* Secrets (`JWT_SECRET`, the backup passphrase, the bucket keys) are Railway **sealed** variables: written once,
  never readable again in the dashboard. The database URL is a Railway reference, never typed anywhere.
* The website's own store (web passwords, access roles, change log) is in the same PostgreSQL database
  (`WEB_AUTH_DATABASE_URL` = the same reference), so one backup covers everything.

## 2. First deployment (staging, synthetic data) - step by step

1. Railway account on the **Hobby** plan (5 USD per month, includes 5 USD of usage; cron and custom domains need it).
   Create project `mclabor`, environment `staging` (rename the default), connect the GitHub repository.
2. Add **Postgres** from the template. Do not enable the TCP proxy. Note that `DATABASE_PRIVATE_URL` exists.
3. Add service **backend**: root directory `/`, config file path `deploy/railway/backend.railway.json`, variables from
   `env/backend.staging.env.example` (seal `JWT_SECRET`). Deploy. Private networking is on by default.
4. Add service **frontend**: root directory `frontend`, variables from `env/frontend.env.example`. Deploy. Generate a
   Railway domain for now.
5. Build the database (one-off command on the backend service, Railway > service > "Run command", or a shell):
   ```
   python -m app.pgschema apply "$STAGING_DATABASE_URL" --indexes --constraints
   python -m app.synthdb "$STAGING_DATABASE_URL" 0.2 --fill-existing
   python -m app.webauth set-password ARI        (a synthetic administrator; then grant others on the Users page)
   ```
   Restart the backend; `/api/ready` must answer `ready`.
6. Cloudflare: add `staging.<domain>` as a proxied CNAME to the frontend's Railway domain; create an Access
   application for that hostname with a policy allowing the staff identity-provider group; copy the AUD tag into
   `CLOUDFLARE_ACCESS_AUD`; set `CLOUDFLARE_ACCESS_TEAM_DOMAIN`. Add the custom domain to the frontend service in
   Railway. Remove the Railway-generated domain.
7. Add service **backup**: root directory `deploy/railway/backup`, variables from `env/backup.env.example` (bucket in
   Cloudflare R2 with its own API token; seal the keys and the passphrase). It runs at 07:00 UTC; run it once by hand.
8. Tests (section 4). Then the 20-user load test from this PC against `https://staging.<domain>` with a service
   token for Access (`tools/staging/loadtest.py` with the token header), and the Users page roster rehearsal.

Production is the same with environment `production`, `env/backend.production.env.example`, a separate Access
application, and the migrated data (section 7 of `docs/cloud/12-railway-plan.md`) - not before the owner's approval.

## 3. Secrets and separation

| Item | Where | Note |
|---|---|---|
| `JWT_SECRET` | sealed variable per environment | different in staging and production; the sign-in token carries the environment name and is refused elsewhere |
| database URL | Railway reference `${{Postgres.DATABASE_PRIVATE_URL}}` | never pasted; staging and production are different Postgres services, and the app refuses identical URLs |
| Cloudflare AUD / team domain | plain variables | not secret; the AUD differs per application (staging vs production) |
| backup passphrase, bucket keys | sealed variables + the password safe | without the passphrase a backup cannot be read, by anyone |
| `ANTHROPIC_API_KEY` | not set | an outside AI service with real data needs the owner's written approval first (`CLAUDE_REAL_DATA_APPROVAL`) |

## 4. Health, tests, rollback

* Health: Railway restarts a service whose health check fails (`/api/ready`: database and sign-in store answer;
  `/healthz` on the frontend). The status page (administrators) shows backend, shape and warnings.
* Smoke from this PC: `deploy/vm/smoke.ps1 -Site https://staging.<domain> -Expect staging` (proxy demands sign-in,
  forged headers refused). On the backend: `python tools/containers/smoke_test.py --expect staging --api http://127.0.0.1:$PORT`.
* Backups: `backup.sh` nightly; `restore-test.sh` monthly as a one-off run of the backup service; keep its output.
* Rollback: Railway keeps every deployment; "Redeploy" an earlier one from the service's deployment list (seconds).
  Database: restore the newest backup into a fresh Postgres service and switch the reference variable.
* Logs: Railway's log drain per service (JSON lines with request ids; the access log never contains query strings).

## 5. Monthly cost for 20 employees (Railway list prices read 2026-11-24, docs/cloud/12-railway-plan.md)

| | USD / month |
|---|---|
| Hobby plan (includes 5 USD of usage) | 5.00 |
| backend 0.25 vCPU + 0.5 GB average | 10.00 |
| frontend 0.1 vCPU + 0.3 GB average | 5.00 |
| Postgres 0.1 vCPU + 0.5 GB average + 2 GB volume | 7.30 |
| backup cron (minutes a day), egress under 5 GB, R2 bucket under 10 GB | 0.50 |
| **production estimate (usage above the included 5 USD)** | **about 23** |
| staging kept running all month | + about 15 |
| **worst case** if every service sat at 1 vCPU / 2 GB all month | about 90 |

Cloudflare (DNS, Access for up to 50 users, R2 under 10 GB) stays on free plans.
