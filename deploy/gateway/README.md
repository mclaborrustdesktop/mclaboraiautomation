# Gateway deployment for real data (prepared, not switched on)

Office staff reach the website only through a company gateway that signs them in with their company account.
The website itself stays bound to `127.0.0.1` and is never exposed. Nothing in this folder is active; the
backend is in DEMO and `ACCESS_MODE=login` is what the prepared staging settings use.

```
staff PC --(VPN / Zero Trust client)--> gateway (sign-in, 2-step) --> reverse proxy on the web PC
                                                                        ├─ /api/*  -> 127.0.0.1:8000 (backend, read-only)
                                                                        └─ /*      -> 127.0.0.1:3000 (frontend, `next start`)
```

The reverse proxy does three things the backend relies on (`backend/app/security.py`, `_gateway_user`):

1. **Removes** any `X-Gateway-Secret`, `X-Auth-Request-Email` or `Cf-Access-Authenticated-User-Email` header a
   visitor sent, so a forged header can never arrive.
2. **Adds** `X-Gateway-Secret: <GATEWAY_SECRET>` to every forwarded request. The backend refuses a request without
   it, and refuses it unless it arrives from an address in `GATEWAY_TRUSTED_PROXIES` (default: this PC).
3. **Adds** the signed-in person's e-mail in the header named by `GATEWAY_EMAIL_HEADER`. The backend looks the
   e-mail up in the office staff table (active records only) and then checks `WEB_ADMINS` / `WEB_USERS`.

Two templates are here:

| File | Product | Notes |
|---|---|---|
| `Caddyfile.example` | Caddy as the reverse proxy, with `forward_auth` to oauth2-proxy | One binary, automatic HTTPS inside the office network if a certificate is available |
| `oauth2-proxy.cfg.example` | oauth2-proxy signing people in with Microsoft 365 (Entra ID) or Google | Restricts to the company e-mail domain; the gateway, not the website, enforces 2-step sign-in |

Cloudflare Zero Trust (Access + Tunnel) is the alternative without a VPN: the tunnel connector runs on the web PC,
Access signs people in, and the backend reads `Cf-Access-Authenticated-User-Email` (`GATEWAY_EMAIL_HEADER`). The
proxy rules above still apply (the connector must add the secret header and strip visitor headers).

**Recommended for MC Labor (2026-11-23):** the office PCs and the web PC share one office network (<office-lan>/24),
so the simplest company-only set-up is Caddy + oauth2-proxy on the web PC, listening on its office-network address
only, with sign-in by the company's Microsoft 365 (or Google) accounts. No VPN is needed inside the office; people
working from elsewhere would use the company VPN or Cloudflare Access. Four things the company must provide before
this can be installed: the identity provider (Microsoft 365 or Google), a site name on the office network, an app
registration in that tenant (client id and secret), and an HTTPS certificate for the site name (an internal CA, or a
public name with an automatic certificate). The two programs (Caddy, oauth2-proxy) are not installed yet.

## Before switching a real-data environment to `gateway`

Run `powershell -ExecutionPolicy Bypass -File tools\gateway-check.ps1 -EnvFile backend\.env.off` (read-only),
then go through the checklist in `docs/access-without-login.md`. In short:

1. The gateway product is chosen and administered by the company; sign-in limited to named company accounts with
   two-step verification.
2. `backend\.env`: `ACCESS_MODE=gateway`, `GATEWAY_SECRET` (48+ random characters, the same value in the proxy),
   `GATEWAY_EMAIL_HEADER` for the product used, `GATEWAY_TRUSTED_PROXIES` (the proxy's address),
   `WEB_ADMINS` / `WEB_USERS` filled in (`tools\staging\manage-web-access.ps1`).
3. `frontend\.env.local`: `NEXT_PUBLIC_API_URL=` (empty) so the browser calls `/api` on the site's own address,
   and the frontend is built (`npm run build`) and served with `npx next start -p 3000 -H 127.0.0.1`.
4. Backend started with `--host 127.0.0.1`; no firewall rule opens 8000 or 3000; the proxy is the only listener
   other machines can reach.
5. Staff e-mail addresses in `tblOfficeStaff.OfficeStaffEmail` are correct for everyone on the lists.
6. Proof: from outside the VPN the site does not open; with a company account that is not on a list the site
   answers 403; `tools\gateway-check.ps1 -Probe` passes.
7. The owner's approval, because it changes how real records are reached.

## What stays the same

Read-only data access, the restricted SQL login, the environment label on every page, the 423 answer to any
change, and the separation of DEMO / STAGING / PRODUCTION settings.
