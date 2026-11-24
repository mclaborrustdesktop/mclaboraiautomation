# MC Labor backend (FastAPI) container image. Built by deploy/cloud/docker-compose.yml or a cloud build service.
# Includes Microsoft's ODBC Driver 18 for SQL Server, which the website needs for the McLabor database.
# Runs as a non-root user, listens on 8000 inside the container only; the reverse proxy in front adds HTTPS and sign-in.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    LOG_FORMAT=json ACCESS_LOG=true MCLABOR_SECRETS_DIR=/run/secrets

# ODBC Driver 18 for SQL Server (Microsoft's package repository) + unixODBC
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg2 ca-certificates apt-transport-https \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && apt-get purge -y curl gnupg2 && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
# The client's schema export (docs/schema, outside this build context) is read by the start-up schema check and the
# status page: docker-compose.yml mounts it at /app/docs/schema; a cloud build copies it into backend/docs/schema first.
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data /app/docs/schema && chown -R app:app /app
USER app
ENV SCHEMA_CSV_DIR=/app/docs/schema \
    WEB_AUTH_DATABASE_URL=sqlite:////app/data/web_auth.db

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Deliberately WITHOUT --proxy-headers: the backend must see the proxy's own address as the client, because the
# gateway check (GATEWAY_TRUSTED_PROXIES) is "did this request come from the proxy?". The proxy's log holds the
# visitor's address.
# PORT and WEB_WORKERS come from the hosting service when it sets them (Railway sets PORT); "::" listens on IPv6 and
# IPv4, which a private network that resolves service names to IPv6 (Railway) needs.
CMD ["sh", "-c", "python -m uvicorn app.main:app --host :: --port ${PORT:-8000} --workers ${WEB_WORKERS:-4} --no-access-log"]
