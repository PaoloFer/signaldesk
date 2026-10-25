#!/bin/sh
set -eu

ENV_FILE="${1:-.env.production}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"
set -a
. "$ENV_FILE"
set +a

docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  exec -T postgres pg_dump \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom \
    > "$BACKUP_DIR/signaldesk-$STAMP.dump"

find "$BACKUP_DIR" -type f -name 'signaldesk-*.dump' -mtime "+$RETENTION_DAYS" -delete
echo "Backup creato: $BACKUP_DIR/signaldesk-$STAMP.dump"
