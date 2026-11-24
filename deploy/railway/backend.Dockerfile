# MC Labor backend image for Railway, built from the REPOSITORY ROOT (service root directory "/") so that the client's
# schema export in docs/schema is part of the image without copying it into backend/. Same contents and the same
# security posture as backend/Dockerfile (non-root, no --proxy-headers); the SQL Server driver stays available so the
# image can also talk to the SQL Server environments if ever needed.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    LOG_FORMAT=json ACCESS_LOG=true

RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg2 ca-certificates apt-transport-https \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && apt-get purge -y curl gnupg2 && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY docs/schema ./docs/schema
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app
ENV SCHEMA_CSV_DIR=/app/docs/schema

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=4).status == 200 else 1)"

# PORT is set by Railway; "::" listens on IPv6 and IPv4 for the private network. No --proxy-headers (see backend/Dockerfile).
CMD ["sh", "-c", "python -m uvicorn app.main:app --host :: --port ${PORT:-8000} --workers ${WEB_WORKERS:-2} --no-access-log"]
