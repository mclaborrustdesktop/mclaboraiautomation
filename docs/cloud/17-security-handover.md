# 17. Security and hand-over after the first STAGING deployment (2026-11-26)

Companion to `16-staging-deployment-report-2026-11-26.md`. Nothing here connects to the office database, registers the
scheduler, creates a production project or changes billing.

## 1. Staging report: verified

The report in 16 was re-read against the live project on 2026-11-26: services, variables (names), domains, volume,
backup schedule, the synthetic load summary and both test runs match what Railway and the website return. The
report names the office machines only by their placeholders (LIVE-HOST, "the development PC").

## 2. Public Git history review (office host names)

The working tree and the current commit are clean (repository scanner: 0 blocking findings; the office-names rule is
active). Two commits in the public history of `mclaborrustdesktop/mclaboraiautomation` carry the two office host names
in their diffs, three lines each, in `docs/cloud/16-...md` only:

| Commit | Why |
|---|---|
| `150dbd9` | the report was pushed with the real names in three sentences before the scanner result was read |
| `4d18cab` | the fix: its diff shows the removed lines |

What is exposed: two Windows computer names. No addresses, no credentials, no records. Both names are also the kind of
thing visible to anyone on the office network, so the exposure is low; the clean-up below is still recommended
because the repository is public.

## 3. Safest clean-up procedure (needs the owner's authorization: it rewrites public history)

Preparation, no risk:
1. Full safety copy of the repository as it is now, kept outside the project folder:
   `git bundle create %USERPROFILE%\MCLabor-repo-before-rewrite.bundle --all` and a plain `git tag pre-rewrite-2026-11-26`.
2. Confirm nobody else has cloned or branched (one collaborator; Railway only reads `main` at deploy time).

Rewrite (one command sequence, run by the owner or with the owner's explicit go-ahead):
```
git reset --soft 4d18cab~2            (keeps every file exactly as it is now; squashes the two commits)
git commit -m "Docs: Railway Pro staging deployment report (2026-11-26)"
git push --force-with-lease origin main
git tag -d pre-rewrite-2026-11-26     (after the push is verified)
```
`--force-with-lease` refuses to overwrite anything pushed by someone else in the meantime. The code on `main` is
byte-for-byte unchanged; only the two commit objects disappear from the branch. Railway keeps deploying the same
tree (the next deployment picks the new commit hash).

After the rewrite:
3. GitHub keeps unreachable commits for a while and still serves them by direct hash. To have them purged, open a
   request at https://support.github.com (category "Remove data", give the two hashes). Optional for host names.
4. `git log -p main | findstr /i /g:tools\repo-check\local-names.txt` must print nothing (the names are in the ignored
   `tools/repo-check/local-names.txt`; the scanner enforces the rule on every future commit).

If the owner prefers not to rewrite: leave it. The current tree is clean and the scanner prevents a repeat.

## 4. Administrator password: NOT yet changed (checked 2026-11-26)

The one-time bootstrap value still signs `ARI` in and the response still says `must_change_password: true`. Until the
owner signs in once and chooses a real password, the bootstrap variable must stay (it is the only way in).

Owner's action: open the website, sign in as `ARI` with the one-time value from the local secrets file, set a real
password when prompted (16+ characters, not containing the initials). Then tell the assistant, or run the removal
yourself:
```
railway variable delete WEB_BOOTSTRAP_PASSWORD --service backend
```
(removing it triggers a backend redeploy; about two minutes). The check that proves the change: a sign-in attempt with
the old value must answer 401.

## 5. Database backups: configured; how to restore

Configured on 2026-11-26 for the PostgreSQL volume `postgres-volume` (volume instance `70f5e878-…`):
- Railway volume backups: **Daily** at 18:36 UTC and **Weekly** on Saturdays at 09:37 UTC (Railway's own retention:
  daily 6 days, weekly 1 month, monthly 1 year; a backup is a snapshot of the whole volume).
- One on-demand backup taken at 14:44 UTC on 2026-11-26 (`200b0cee-…`) right after the synthetic load.
- Point-in-time recovery: off. The mirror is re-fed by the office agent, so a daily snapshot plus a fresh sync is the
  recovery path; PITR can be enabled later for production (`railway postgres pitr enable`).

Restore procedure (dashboard): Postgres service -> **Backups** tab -> choose a backup -> **Restore**. Railway stops the
service, replaces the volume contents with the snapshot and redeploys; the backend reconnects by itself (health check
`/api/ready` goes 503 then 200). Expect one to three minutes of "database unavailable" on the website.

Restore procedure (CLI/API): `railway api 'mutation($v:String!,$b:String!){ volumeInstanceBackupRestore(volumeInstanceId:$v, volumeInstanceBackupId:$b){ workflowId } }' --raw-var v=<volume instance id> --raw-var b=<backup id>`.
Take an on-demand backup first (Backups -> Create backup) so the restore itself can be undone.

After any restore: run the sync agent once with `--full` so the mirror catches up with the office (deletions are
reconciled by the agent's state, never blindly), and check "Information as of" in the website banner.

Restore drill: once a quarter, restore the latest backup into a **separate** Postgres service in the same project
(Railway's "restore to new volume" option, or a new service + restore) and run the smoke checks against it; delete it
afterwards.

Belt and braces (later): the encrypted `pg_dump` to Cloudflare R2 in `deploy/railway/backup` gives an off-platform copy.

## 6. Cloudflare Zero Trust plan for up to 20 employees (not executed yet)

Target: `https://search.<company domain>` protected by Cloudflare Access; nobody reaches the website without a
Cloudflare identity; the application keeps its own roles (WEB_ADMINS / Users page) and the 20-seat limit.

| Step | Where | What | Cost |
|---|---|---|---|
| 1 | Cloudflare dashboard | Add the company domain (or a sub-domain delegated to Cloudflare) as a zone; nameservers at the registrar | free |
| 2 | Zero Trust -> Settings | Team name `mclabor` -> `mclabor.cloudflareaccess.com` (= `CLOUDFLARE_ACCESS_TEAM_DOMAIN`) | free up to 50 users |
| 3 | Zero Trust -> Authentication | Identity provider: Microsoft Entra ID or Google Workspace if the office has one; otherwise One-time PIN by e-mail restricted to the company e-mail domain | free |
| 4 | Zero Trust -> Access -> Applications | Self-hosted app `MC Labor search`, hostname `search.<domain>`; policy **Allow** for a group of at most 20 named e-mails (or an IdP group); session 8 h; copy the **AUD** tag (= `CLOUDFLARE_ACCESS_AUD`) | free |
| 5 | Zero Trust -> Access -> Service Auth | Service token `mclabor-sync-agent` for the office agent; add a second policy on the same app: **Service Auth**, path `/api/sync/*` | free |
| 6 | Railway frontend service -> Settings -> Networking | Custom domain `search.<domain>` -> Railway shows a CNAME target | free on Pro |
| 7 | Cloudflare DNS | CNAME `search` -> that target, **proxied (orange cloud)**; SSL/TLS mode Full (strict) | free |
| 8 | Railway backend variables | `ACCESS_MODE=gateway`, `GATEWAY_PLATFORM=cloudflare-access`, `GATEWAY_TRUSTED_PROXIES=any`, `CLOUDFLARE_ACCESS_TEAM_DOMAIN`, `CLOUDFLARE_ACCESS_AUD`, `CORS_ORIGINS=https://search.<domain>`; `WEB_ADMINS` = the administrators' e-mails | - |
| 9 | Railway frontend service | **remove the `*.up.railway.app` domain** (see 7 below) | - |
| 10 | Tests | sign in through Cloudflare as a listed user; a non-listed e-mail is refused by Cloudflare; the API without the Cloudflare token answers 401; the agent with the service token syncs; the 20-user load test; the Users page roster | - |

What the application already does for this (tested in `tests/test_cloud_ready.py`): verifies the Cloudflare Access
JWT signature, issuer and audience on every request (header or `CF_Authorization` cookie), takes the identity from the
token (never from a plain header), accepts service tokens only on `/api/sync/*` together with the sync key, and
refuses `GATEWAY_TRUSTED_PROXIES=any` unless the platform is Cloudflare Access.

Seat management stays in the website: Cloudflare decides *who can reach* the site (the policy's e-mail list), the
website decides *who may use* it (WEB_ADMINS/WEB_USERS and the Users page, 20 seats, warning at 16).

## 7. Preventing a bypass of Cloudflare through the Railway URL

Cloudflare Access only protects traffic that goes through Cloudflare. Three layers, applied together:

1. **No Railway-generated domain.** Delete `frontend-production-b331880c.up.railway.app` once the custom domain works
   (`railway domain delete <domain> --service frontend --yes`). Railway then serves the site only for the custom
   hostname.
2. **The application refuses anything that did not come through Cloudflare Access.** In gateway mode the backend
   requires a valid Cloudflare Access JWT on every API request; without it: 401, no data, no sign-in page that works.
   So even someone who reaches Railway's edge directly with the custom hostname (possible in principle, because the
   DNS target is Railway's) gets an empty shell and 401s. This is the layer that actually holds; it is already in the
   code and is turned on by `ACCESS_MODE=gateway`.
3. **Optional, strongest: Cloudflare Tunnel.** Run `cloudflared` as a fourth Railway service (no public domain on the
   frontend at all; the tunnel connects outbound to Cloudflare and publishes `search.<domain>`). Then there is no
   public path to Railway's edge for this site. `deploy/vm/cloudflared-config.yml.example` already describes the tunnel
   shape; on Railway it becomes a small service with the tunnel token as a sealed variable. Recommended before
   production; optional for staging.

Also: Cloudflare WAF rule "block requests to `/api/sync/*` unless they carry a service token" (Access policy already
does this), and the Cloudflare Access session length of 8 hours so a forgotten laptop expires.

## 8. Security checklist for the twice-daily office -> cloud synchronization (not activated yet)

Before the first real run (each item has an owner):
- [ ] Administrator creates the **read-only SQL login** on the live server from `tools/prod-check/proposed-grants-production.sql`
      (SELECT on the approved tables only; no write, no `db_owner`); its password is stored with
      `tools/sync/store-sync-secrets.ps1` (Windows DPAPI, the account that runs the task) and nowhere else.
- [ ] The server's TLS certificate is trusted by the office PC (`PRODUCTION_DB_ENCRYPT=true`,
      `PRODUCTION_DB_TRUST_SERVER_CERTIFICATE=false`); `PRODUCTION_DB_EXPECTED_SERVER_NAME` is set so the agent refuses any
      other server.
- [ ] `tools/sync/sync.env` on the office PC lists `OFFICE_HOSTS` (the agent refuses the office servers as a *target*)
      and `backend/office-hosts.txt` exists on that PC.
- [ ] The approved table/column list (`tools/prod-check/required_schema.json`) reviewed once more by the owner: no SSN,
      bank, date of birth, password or I-9 columns (the agent cannot send a column outside the list; the cloud side
      refuses it with 422).
- [ ] Cloud side: `SYNC_API_KEY` sealed and rotated once before production; the Cloudflare service token in DPAPI on
      the office PC; `/api/sync/*` reachable only with both.
- [ ] Deletion guards left at their defaults (agent: skip deletions when a table shrinks by more than 10 % and more than
      100 rows; cloud: refuse more than 10 % / 500 rows per run). `--allow-mass-delete` only by hand after checking
      the source.
- [ ] First real run is a **dry run** (`run-sync.ps1 -DryRun`), then a full run by hand watched by the owner, then the
      scheduled task (`register-sync-task.ps1 -Times "06:00,12:30"`, no overlap, retry after 15 min, S4U so no
      password is stored for the task).
- [ ] Logs: the agent's log file on the office PC and `GET /api/sync/runs` (administrators) in the cloud; exit code 2
      = deletions skipped, to be looked at the same day.
- [ ] The website banner "Information as of …" and the warning after 14 hours are what staff see; the owner is told
      what "outdated" means and whom to call.
- [ ] Never: a write path from cloud to office (none exists), the live server as a PostgreSQL/synthetic/schema target
      (refused by the guards), real records in staging, the Anthropic key with real data without
      `CLAUDE_REAL_DATA_APPROVAL`.

## 9. Items needing the owner's approval or action

1. History rewrite of commits `150dbd9` and `4d18cab` (section 3): authorize, or decline and leave it.
2. Sign in once as `ARI` and set a real password (section 4); then the bootstrap variable is deleted.
3. Cloudflare: which identity provider the staff will use, and the hostname (`search.<domain>`); then the plan in
   section 6 can be executed (free).
4. Whether to add the Cloudflare Tunnel service before or after production (section 7, item 3).
5. Later, separately: the read-only login on the live server (administrator), the first dry run, the scheduled task,
   and a production project (billing).
