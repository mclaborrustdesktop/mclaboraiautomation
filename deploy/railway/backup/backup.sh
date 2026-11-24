#!/bin/sh
# Encrypted PostgreSQL backup -> S3-compatible bucket. Runs once and exits (Railway cron).
# Needs: DATABASE_URL (private URL of the database), BACKUP_PASSPHRASE (long random; keep a copy in the password safe,
# without it no backup can be read), S3_BUCKET, S3_ENDPOINT (R2: https://<account>.r2.cloudflarestorage.com),
# AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, optional BACKUP_PREFIX (default: the environment name) and KEEP_DAYS (default 35).
set -eu
: "${DATABASE_URL:?}" "${BACKUP_PASSPHRASE:?}" "${S3_BUCKET:?}" "${S3_ENDPOINT:?}" "${AWS_ACCESS_KEY_ID:?}" "${AWS_SECRET_ACCESS_KEY:?}"
PREFIX="${BACKUP_PREFIX:-${RAILWAY_ENVIRONMENT_NAME:-mclabor}}"
KEEP_DAYS="${KEEP_DAYS:-35}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="mclabor-${PREFIX}-${STAMP}.dump.enc"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "backup: dumping ${PREFIX} ..."
# custom format (compressed, restorable table by table); the passphrase never appears on a command line
pg_dump --format=custom --no-owner --no-privileges "$DATABASE_URL" > "$TMP/db.dump"
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$TMP/db.dump" -out "$TMP/$NAME" -pass env:BACKUP_PASSPHRASE
SIZE="$(stat -c %s "$TMP/$NAME")"
sha256sum "$TMP/$NAME" | cut -d' ' -f1 > "$TMP/$NAME.sha256"

echo "backup: uploading ${NAME} (${SIZE} bytes) ..."
aws s3 cp --endpoint-url "$S3_ENDPOINT" --only-show-errors "$TMP/$NAME" "s3://${S3_BUCKET}/${PREFIX}/${NAME}"
aws s3 cp --endpoint-url "$S3_ENDPOINT" --only-show-errors "$TMP/$NAME.sha256" "s3://${S3_BUCKET}/${PREFIX}/${NAME}.sha256"

# retention: delete objects older than KEEP_DAYS (a bucket lifecycle rule is the belt to these braces)
CUTOFF="$(date -u -d "-${KEEP_DAYS} days" +%Y%m%dT%H%M%SZ 2>/dev/null || date -u -v-${KEEP_DAYS}d +%Y%m%dT%H%M%SZ)"
aws s3 ls --endpoint-url "$S3_ENDPOINT" "s3://${S3_BUCKET}/${PREFIX}/" | awk '{print $4}' | while read -r key; do
  case "$key" in
    mclabor-${PREFIX}-*.dump.enc|mclabor-${PREFIX}-*.dump.enc.sha256)
      ts="$(echo "$key" | sed -E 's/.*-([0-9]{8}T[0-9]{6}Z)\..*/\1/')"
      if [ "$ts" \< "$CUTOFF" ]; then
        aws s3 rm --endpoint-url "$S3_ENDPOINT" --only-show-errors "s3://${S3_BUCKET}/${PREFIX}/${key}"
        echo "backup: removed old ${key}"
      fi;;
  esac
done
echo "backup: done ${NAME}"
