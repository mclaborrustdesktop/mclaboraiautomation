# MC Labor AI Automation

Web application for MC Labor's office staff: employee, customer and job (project) management,
weekly assignment tracking, user/permission administration, and natural-language **AI search**.

This is the **demonstration build**. It runs entirely on a local SQLite database filled with
synthetic data. It does **not** connect to or modify the production SQL Server. The ORM models
keep the production table and column names (`tblEmployee`, `tblCustomer`, `tblProject`,
`tblTracking`, `tblOfficeStaff`, `tblOfficeStaffPermission`, `tblPullDown*` …) so pointing the
app at the real database later is a connection-string change, not a rewrite.

## Environments

The app runs in one of three environments, chosen by `DATA_SOURCE` in `backend/.env`: DEMO (default, synthetic data),
STAGING (a restored copy of the real database) and PRODUCTION (the live database). See `docs/environments.md`.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15 (App Router, TypeScript), Tailwind CSS 4, lucide icons, Vitest |
| Backend | FastAPI, SQLAlchemy 2, Pydantic 2, PyJWT, pytest |
| AI search | Claude API (`claude-opus-5-5`) via the official `anthropic` SDK with structured JSON output, plus an offline heuristic parser used automatically when no API key is configured |
| Database (demo) | SQLite file `backend/mclabor_demo.db`, seeded on first start |

## Run it

```powershell
.\start.ps1
```

or manually in two terminals:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

```powershell
cd frontend
npm run dev
```

* App: http://localhost:3000
* API docs (Swagger): http://localhost:8000/docs

**Demo logins** – every seeded user has the password `mclabor2025`.

| Login | Role |
|---|---|
| `ADMIN` | Administrator – all features, user management |
| any other initials shown on the Users page | Recruiter / Sales / Dispatcher / Payroll / Accounting / Safety – limited by feature permissions |

## Enable Claude-powered search

Create `backend/.env` (see `backend/.env.example`):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Restart the backend. The dashboard badge switches from "built-in parser" to "Claude AI search on".
Without a key the built-in parser handles the same phrasing for the demo vocabulary.

## Tests

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest        # 169 API, duplicate, validation, search, access, cloud-readiness, deployment-config, synthetic-db and production-safety tests
cd backend;  .\.venv\Scripts\python.exe -m app.production schema   # check models against docs/schema CSV export
cd frontend; npm test                                      # Vitest unit tests
cd frontend; npm run build                                 # type-check + production build
```

## Project layout

```
backend/
  app/main.py        FastAPI app, CORS, startup seeding
  app/models.py      SQLAlchemy models (production table/column names)
  app/schemas.py     Pydantic request/response models
  app/ai.py          Claude + heuristic natural-language query interpreter
  app/search.py      Filter + relevance-ranking service
  app/seed.py        Synthetic demo data (32 users, 170 employees, 64 customers, 95 jobs, ~900 weekly assignments)
  app/routers/       auth, users, lookups, employees, customers, projects, tracking, search, dashboard
  tests/             pytest suite
frontend/
  src/app/           pages: dashboard, login, search, employees, customers, projects, tracking, users
  src/components/    AppShell, DataTable, SearchBar, EntityForm, charts, ui
  src/lib/           api client, auth context, form specs, formatters (+ tests)
docs/schema-notes.md Notes from the SQL Server structure/relationship CSVs
docs/environments.md DEMO / STAGING / PRODUCTION and the four databases
docs/access-without-login.md  ACCESS_MODE (open / login / gateway), WEB_ADMINS and WEB_USERS
docs/search-performance.md    what makes searches slow on the real data and what was changed
docs/production/     readiness report, backup/certificate/login procedures, staging pilot results,
                     11 (empty employee contact columns), 12 (requirements before production),
                     13 (DBA procedure, counts only), 14 (production readiness checklist),
                     15 (the live database and the production connection), 16 (Add/Edit plan)
tools/production/    store-db-password.ps1 (production password store), start-production.ps1 (website on the live database, read-only)
docs/cloud/          07 single-VM design (PRIMARY, 200 USD budget) and 08 verified pricing; 01 Azure database options (comparison);
                     02 migration and rollback; 03 remaining development; 05 cloud STAGING with synthetic data; 06 feature status
deploy/vm/           the single Windows VM deployment: SETUP.md, provisioning plan (dry run) with budget alerts, install/deploy
                     scripts (no Docker), Cloudflare tunnel config, firewall, encrypted backups and restore test
backend/app/cloudflare_access.py  verifies the Cloudflare Access token on every request (GATEWAY_PLATFORM=cloudflare-access)
docs/cloud/10-staging-preflight.md  the staging resource list, costs incl. deallocated floor, cleanup, and the approval request
docs/cloud/09-user-access-plan.md  maximum 20 website users, runtime access management (Users page / webauth access-set),
                     unique-user count, the 20-user limit and the 50-seat sign-in service check; roster template deploy/vm/staff-roster.example.csv
docs/cloud/11-vm-size-for-20-users.md  measured 20-user load on 4 and on 2 logical processors; B2ms vs B4ms; revised budget
deploy/vm/azure/CLOUDSHELL.md  staging from Azure Cloud Shell: read-only pre-flight, approval stop, provisioning, set-up, tests, cleanup
docs/cloud/14-staging-setup-walkthrough.md  GitHub, Cloudflare Access, R2, Railway (paid, after approval), synthetic staging: one step at a time with charges
docs/cloud/15-railway-staging-recovery.md  the Railway trial restriction (exact text, appeal path), what is preserved (volume, variables, domain), recovery order
docs/cloud/16-staging-deployment-report-2026-11-26.md  the live STAGING on Railway Pro: services, synthetic load, all tests passed, persistence, backups, next steps
docs/cloud/17-security-handover.md  history clean-up procedure, administrator password hand-over, backup restore, Cloudflare Zero Trust plan (20 users),
                     bypass prevention, security checklist for the twice-daily synchronization, items needing approval
tools/repo-check/scan_repo.py  run before every push: lists what the root .gitignore keeps out and scans the rest for secrets and real data
docs/cloud/13-one-way-sync.md  FIRST RELEASE: office SQL Server -> one-way sync -> Railway PostgreSQL -> search-only website; agent, reconciliation,
                     schedule, security, tests, costs, what remains. tools/sync = the office agent's scripts (DPAPI secrets, Task Scheduler)
docs/cloud/12-railway-plan.md  the Railway + PostgreSQL decision (2026-11-24): what was built, networking, backups, cost for 20 users, migration
deploy/railway/README.md       service layout, step-by-step first deployment, secrets, health, rollback; deploy/railway/postgres = generated schema
docs/access-replacement/01-access-workflow-audit.md  2,196 Access forms / 384 reports grouped by workflow; what the website covers; the gaps (G1-G16)
backend/app/pgschema.py        PostgreSQL schema from the SQL Server export (288 tables); app/audit.py change log + record versions; app/derived.py
tools/containers/    run-smoke.ps1 (build + DEMO stack + smoke test), smoke_test.py (23 checks, two modes)
tools/docker-readiness.ps1  can this PC run Docker (read-only)
backend/app/synthdb.py      synthetic McLabor-SHAPED database (33 tables, production shape, invented rows) for a staging rehearsal
deploy/cloud/BUILD-AND-TEST.md  beginner steps to build and test the containers
deploy/cloud/        container images (backend/Dockerfile, frontend/Dockerfile), Compose stack with HTTPS proxy and sign-in,
                     DEMO profile, Azure provisioning plan (dry run). Nothing deployed.
backend/app/observability.py  JSON logs, request ids, access log; /api/ready readiness
tools/staging/       read-only scripts for the restored copy; run-readonly.ps1 runs them while the website stays in DEMO;
                     loadtest-staging.ps1 (35/60-user load test on a second backend); manage-web-access.ps1 (WEB_ADMINS / WEB_USERS)
tools/prod-check/    connection check, proposed scripts (never run without approval: grants, certificate, indexes, full-text), reports;
                     verify-readonly-login.sql = read-only effective-permission report of the sync login (docs/production/17)
docs/production/17-readonly-login-verification.md  the strictly read-only sync account: column grants + DENY layer, rehearsal on the copy, live-server procedure, risks
tools/gateway-check.ps1  read-only readiness check for gateway access
deploy/gateway/      reverse-proxy and sign-in templates for gateway access (not active)
```

## Next steps toward production

1. Add `pyodbc` + `DATABASE_URL=mssql+pyodbc://…` (read-only account first) and set `SEED_ON_STARTUP=false`.
2. Map the remaining production columns you want on screen (models only declare what the UI uses).
3. Replace the demo JWT secret and demo password; consider Windows/Azure AD sign-on.
4. Move keyword ranking into SQL Server full-text search for the full employee table.
