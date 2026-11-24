# Container deployment (prepared; not deployed)

Four containers on one host: `proxy` (Caddy: HTTPS, sign-in gate, secret header), `auth` (oauth2-proxy:
Microsoft 365 or Google sign-in), `frontend` (Next.js standalone), `backend` (FastAPI, 4 workers, ODBC Driver 18).
Only the proxy has published ports. The images are built from `backend/Dockerfile` and `frontend/Dockerfile`.

```
staff browser --HTTPS--> proxy --forward_auth--> auth (company sign-in)
                           |-- /api/* + X-Gateway-Secret --> backend:8000 --encrypted--> cloud SQL Server
                           '-- /*                       --> frontend:3000
```

The same images run unchanged on Azure Container Apps (see `docs/cloud/01-cloud-architecture.md`): there the
platform's ingress provides HTTPS and its built-in authentication can replace `auth` + the secret header
(`GATEWAY_PLATFORM=azure-easyauth`, `GATEWAY_TRUSTED_PROXIES=127.0.0.1`).

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | the four services, healthchecks, private network, secrets, memory limit; `--profile demo` runs the DEMO on containers |
| `Caddyfile` | HTTPS, forward_auth, header stripping and the secret header, security headers, JSON access log |
| `oauth2-proxy.cfg` | sign-in settings (everything secret or site-specific comes from the environment) |
| `.env.cloud.example` | site name, certificate e-mail, tenant, company e-mail domain |
| `backend.env.example` | the backend's environment (database by name, read-only, access lists, gateway) |
| `secrets/README.md` | the six secret files and how to create them |
| `azure/provision.ps1` | the Azure resources as `az` commands, dry-run by default |

## Rehearsal on any PC with Docker (no real data)

```
cd deploy\cloud
docker compose --profile demo up -d --build
# http://localhost:3000 shows the DEMO; http://localhost:8000/api/ready answers {"status":"ready",...}
docker compose --profile demo down
```

## Real data (staging copy in the cloud first, then production)

1. Fill in `.env.cloud` and `backend.env`; create the six files in `secrets/`.
2. `docker compose --env-file .env.cloud config` prints the resolved configuration: check it, especially that no
   secret appears in it except as a file reference.
3. `docker compose --env-file .env.cloud up -d --build`, then `docker compose logs backend` must show
   `Environment: PRODUCTION ... (read-only)` and `/api/ready` must answer 200 through the proxy.
4. `tools\gateway-check.ps1` has an equivalent here: from outside the host, `https://<site>/api/auth/me` without
   sign-in must answer 401, and the backend port must not be reachable at all.

## What the images do not contain

No `.env`, no databases, no secrets, no tests, no demo data file (the DEMO profile seeds its own). The schema
export in `docs/schema` is mounted read-only for the start-up schema check.
