# Building and testing the containers, step by step

For someone who has not used Docker before. Everything below runs on your own PC with invented data; nothing
reaches the office servers, the cloud or anyone else. Expect 20 to 40 minutes the first time (downloads).

## 0. Is this PC suitable?

```
powershell -ExecutionPolicy Bypass -File tools\docker-readiness.ps1
```

On DEV-PC (checked 2026-11-23): Windows 11 Pro, 32 GB memory, 840 GB free, virtualization on. Two warnings: WSL 2 is
not installed yet, and this PC also runs SQL Server with the restored copy. Docker Desktop installs WSL 2 and
**reboots the PC once**; SQL Server is not affected. Decide before installing:

- **Install on DEV-PC** (fine; the simplest), or
- **use another development PC** (cleaner, because DEV-PC holds the copy of real data and is the DEMO host), or
- **skip local Docker entirely** and let Azure build the images (`az acr build`, section 6) once a subscription exists.

Licensing: Docker Desktop is free for companies under 250 employees and under 10 million USD revenue. The
alternative with the same commands is the free Rancher Desktop (choose the "dockerd (moby)" engine).

## 1. Install Docker Desktop (needs your approval and a local administrator)

1. Download Docker Desktop for Windows from docker.com and run the installer with the default options
   ("Use WSL 2 instead of Hyper-V" ticked).
2. Reboot when asked. Sign in to Windows again; Docker Desktop starts and finishes its WSL 2 set-up.
3. Open a new PowerShell window and check:
   ```
   docker --version
   docker compose version
   docker run --rm hello-world
   ```
   The last command prints "Hello from Docker!". If it says the daemon is not running, start Docker Desktop
   from the Start menu and wait for the whale icon to stop animating.

## 2. Build the two images and run the DEMO stack with one command

```
cd $env:USERPROFILE\Documents\MC-Labor-AI-Automation
powershell -ExecutionPolicy Bypass -File tools\containers\run-smoke.ps1
```

What it does: builds `backend/Dockerfile` and `frontend/Dockerfile`, starts them with synthetic data on ports
**8001** and **3001** (so the normal DEMO on 8000/3000 keeps running), runs `tools\containers\smoke_test.py`
(23 checks: health, readiness, request ids, open access, every list page, AI search, a write, the frontend), shows
Docker's own health verdict, and stops everything again. Expected last lines:

```
  [PASS] frontend home page
RESULT: PASSED
NAME                      STATUS
mclabor-backend-demo-1    Up (healthy)
mclabor-frontend-demo-1   Up (healthy)
4. Stopping the DEMO stack
```

Add `-KeepRunning` to leave it up and open http://localhost:3001 in a browser; stop later with
`cd deploy\cloud; docker compose --profile demo down -v`.

## 3. Doing the same by hand (to understand what the script does)

```
cd deploy\cloud
docker compose --profile demo build            # builds both images (3-10 minutes the first time)
docker compose --profile demo up -d            # starts them in the background
docker compose --profile demo ps               # both should say "healthy" within a minute
docker compose --profile demo logs backend-demo --tail 20   # JSON log lines, one per request
curl http://localhost:8000/api/ready           # {"status":"ready",...}
docker compose --profile demo down -v          # stops and removes everything, including the demo data volume
```

## 4. Rehearsing the real-data stack WITHOUT real data

The full stack (proxy with HTTPS, sign-in, backend in STAGING mode) can be rehearsed against the **synthetic
McLabor-shaped database** instead of the restored copy. That needs a SQL Server to put it in; on this PC that must
NOT be the SQLEXPRESS instance with the copy (the builder refuses it). Options: a SQL Server container
(`mcr.microsoft.com/mssql/server:2022-latest`, Developer edition, free for non-production) started by Docker, or
the cloud staging VM (section 5 of `docs/cloud/05-staging-synthetic-procedure.md`). With a container:

```
docker run -d --name sql-synth -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD=<a long password> -p 127.0.0.1:14333:1433 mcr.microsoft.com/mssql/server:2022-latest
cd backend
.venv\Scripts\python.exe -m app.synthdb "mssql+pyodbc://sa:<password>@127.0.0.1,14333/master?driver=ODBC+Driver+17+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes" 0.1
```

(Create the database `McLaborSynthetic` first and use it in the URL instead of `master`; the builder refuses
"localhost" and "127.0.0.1" by default to protect the office instance, so pass the container's own address
`host.docker.internal` or run the builder inside the Compose network. The loopback refusal is deliberate.)
Then `proposed-grants.sql` with the guard changed to the container's server name creates `mclabor_web_read`, and
the stack starts with `DATA_SOURCE=staging` in `backend.env`, the six secret files, and `--env-file .env.cloud`.
The smoke test then runs in its other mode:

```
backend\.venv\Scripts\python.exe tools\containers\smoke_test.py --expect staging --api http://127.0.0.1:8000 --through-proxy https://localhost
```

which must report the backend port as unreachable and the proxy demanding sign-in.

## 5. What "healthy" means and where to look when it is not

| Symptom | Where to look |
|---|---|
| `backend-demo` restarts or stays "starting" | `docker compose --profile demo logs backend-demo`: a `Refusing to start` line names the setting at fault |
| `/api/ready` answers 503 | its JSON says which check failed: `database` (connection, password, server identity) or `sign_in_store` (volume not writable) |
| frontend shows "cannot reach the server" | the browser's API address: the DEMO profile builds the frontend with `http://localhost:8000`; behind the proxy it must be empty |
| the sign-in loop never ends (real-data stack) | oauth2-proxy logs: redirect URL, tenant and client secret must match the app registration exactly |

## 6. Building in the cloud instead of locally

With a subscription and a container registry, `az acr build --registry <name> --image mclabor-backend:latest backend`
builds the image on Azure's side from the same Dockerfile (a few cents per build). No Docker on any PC is then
needed, but the smoke test still needs a place to run the containers: the Container Apps environment itself.
