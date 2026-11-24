# Secret files for the container deployment

One file per secret, no newline at the end, readable by the Docker daemon only. **Never commit, copy or sync this
folder.** Create them on the host that runs Compose (or in the cloud platform's secret store, mounted at
`/run/secrets`):

| File | Content | How to make it |
|---|---|---|
| `jwt_secret` | 48+ random characters | `python -c "import secrets;print(secrets.token_urlsafe(48), end='')"` |
| `gateway_secret` | 48+ random characters (the proxy sends it, the backend checks it) | same |
| `production_db_password` | the password of `mclabor_web_read` on the cloud database | typed by the administrator who created the login |
| `staging_db_password` | the same for a cloud rehearsal copy (empty file if unused) | |
| `oauth2_client_secret` | the app registration's client secret (Entra ID or Google) | from the tenant's app registration |
| `oauth2_cookie_secret` | 32 random bytes, base64 | `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode(), end='')"` |

The backend reads its three through `MCLABOR_SECRETS_DIR=/run/secrets` (a file named like a setting supplies that
setting). Rotate by replacing the file and restarting the container.
