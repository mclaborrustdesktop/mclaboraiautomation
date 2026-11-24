#!/bin/sh
# Proves a backup can be restored: downloads the newest (or $1) backup, decrypts it, restores it into a scratch database
# on the same PostgreSQL server, counts the rows of the four main tables, drops the scratch database. Run it monthly
# (Railway: a one-off run of the backup service with START command ./restore-test.sh) and keep the output.
# Needs the same variables as backup.sh plus ADMIN_DATABASE_URL (a URL that may CREATE DATABASE; the database's own
# user on Railway can) - the live database is only READ (never written) by this script.
set -eu
: "${BACKUP_PASSPHRASE:?}" "${S3_BUCKET:?}" "${S3_ENDPOINT:?}" "${AWS_ACCESS_KEY_ID:?}" "${AWS_SECRET_ACCESS_KEY:?}"
ADMIN_URL="${ADMIN_DATABASE_URL:-${DATABASE_URL:?}}"
PREFIX="${BACKUP_PREFIX:-${RAILWAY_ENVIRONMENT_NAME:-mclabor}}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
KEY="${1:-$(aws s3 ls --endpoint-url "$S3_ENDPOINT" "s3://${S3_BUCKET}/${PREFIX}/" | awk '{print $4}' | grep -E '\.dump\.enc$' | sort | tail -n 1)}"
[ -n "$KEY" ] || { echo "restore-test: no backup found under ${PREFIX}/"; exit 1; }
echo "restore-test: using ${KEY}"
aws s3 cp --endpoint-url "$S3_ENDPOINT" --only-show-errors "s3://${S3_BUCKET}/${PREFIX}/${KEY}" "$TMP/b.enc"
aws s3 cp --endpoint-url "$S3_ENDPOINT" --only-show-errors "s3://${S3_BUCKET}/${PREFIX}/${KEY}.sha256" "$TMP/b.sha256"
[ "$(sha256sum "$TMP/b.enc" | cut -d' ' -f1)" = "$(cat "$TMP/b.sha256")" ] || { echo "restore-test: CHECKSUM MISMATCH"; exit 1; }
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$TMP/b.enc" -out "$TMP/b.dump" -pass env:BACKUP_PASSPHRASE
SCRATCH="restore_test_$(date -u +%Y%m%d%H%M%S)"
BASE="$(echo "$ADMIN_URL" | sed -E 's#/[^/?]+(\?.*)?$##')"
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE \"$SCRATCH\""
cleanup() { psql "$ADMIN_URL" -q -c "DROP DATABASE IF EXISTS \"$SCRATCH\"" || true; rm -rf "$TMP"; }
trap cleanup EXIT
pg_restore --no-owner --no-privileges --exit-on-error -d "${BASE}/${SCRATCH}" "$TMP/b.dump"
psql "${BASE}/${SCRATCH}" -v ON_ERROR_STOP=1 -At -c '
  SELECT '"'"'tblEmployee '"'"' || count(*) FROM "tblEmployee" UNION ALL
  SELECT '"'"'tblCustomer '"'"' || count(*) FROM "tblCustomer" UNION ALL
  SELECT '"'"'tblProject '"'"'  || count(*) FROM "tblProject"  UNION ALL
  SELECT '"'"'tblTracking '"'"' || count(*) FROM "tblTracking" UNION ALL
  SELECT '"'"'web_audit_log '"'"' || count(*) FROM web_audit_log'
echo "restore-test: PASSED (${KEY} restored into ${SCRATCH}, now dropped)"
