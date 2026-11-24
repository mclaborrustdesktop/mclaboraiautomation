# Nightly encrypted PostgreSQL backup to object storage, run by Railway's cron (deploy/railway/backup/railway.json).
# pg_dump from the official PostgreSQL 16 image, AES-256 with a passphrase that only the owner holds, upload with
# the AWS command line to any S3-compatible bucket (Cloudflare R2 has a free tier; AWS S3, Backblaze B2 work too).
FROM postgres:16-alpine
RUN apk add --no-cache aws-cli openssl coreutils
WORKDIR /backup
COPY backup.sh restore-test.sh ./
RUN chmod +x backup.sh restore-test.sh && adduser -D -u 10001 backup && chown -R backup:backup /backup
USER backup
CMD ["./backup.sh"]
