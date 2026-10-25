#!/bin/sh
set -eu

ENV_FILE="${1:-.env.production}"
case "$ENV_FILE" in
  /*) ENV_PATH="$ENV_FILE" ;;
  *) ENV_PATH="$(pwd)/$ENV_FILE" ;;
esac

if [ ! -f "$ENV_PATH" ]; then
  echo "File non trovato: $ENV_PATH" >&2
  exit 1
fi

docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  build app

docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  run --rm --no-deps \
  -v "$ENV_PATH:/tmp/signaldesk.env:ro" \
  app python scripts/check_deploy_config.py /tmp/signaldesk.env

docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  config --quiet

docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up --detach --remove-orphans

docker compose --env-file "$ENV_FILE" \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  ps
