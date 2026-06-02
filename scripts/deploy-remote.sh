#!/usr/bin/env bash
set -euo pipefail

# Deploy WGS Cockpit to a remote Docker host over SSH.
# Usage: REMOTE_HOST=remote REMOTE_DIR=/opt/wgs-cockpit ./scripts/deploy-remote.sh [--build] [--logs]

HOST="${REMOTE_HOST:-remote}"
REMOTE_DIR="${REMOTE_DIR:-/opt/wgs-cockpit}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:3000}"
API_URL="${API_URL:-http://localhost:8000}"
BUILD=false
LOGS=false

for arg in "$@"; do
  case "$arg" in
    --build) BUILD=true ;;
    --logs) LOGS=true ;;
  esac
done

echo "==> Syncing repo to ${HOST}:${REMOTE_DIR}"
ssh "$HOST" "mkdir -p $REMOTE_DIR"
# Sync .env for remote
scp .env.remote "${HOST}:${REMOTE_DIR}/.env"

# Sync entrypoint script
scp apps/api/entrypoint.sh "${HOST}:${REMOTE_DIR}/apps/api/entrypoint.sh"

rsync -avz --delete \
  --exclude '.venv-test' \
  --exclude 'node_modules' \
  --exclude '.next' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'results/' \
  --exclude 'fastq/' \
  --exclude 'nf-cache/' \
  --exclude 'logs/' \
  --exclude '*.bam' \
  --exclude '*.cram' \
  --exclude '*.vcf.gz' \
  ./ "${HOST}:${REMOTE_DIR}/"

if [ "$BUILD" = true ]; then
  echo "==> Building and starting containers on remote host"
  ssh "$HOST" "cd $REMOTE_DIR && docker compose -f docker-compose.yml -f docker-compose.remote.yml up -d --build"
else
  echo "==> Starting containers on remote host (no rebuild)"
  ssh "$HOST" "cd $REMOTE_DIR && docker compose -f docker-compose.yml -f docker-compose.remote.yml up -d"
fi

echo "==> Checking health"
ssh "$HOST" "cd $REMOTE_DIR && docker compose ps"

if [ "$LOGS" = true ]; then
  echo "==> Streaming logs (Ctrl+C to stop)"
  ssh "$HOST" "cd $REMOTE_DIR && docker compose logs -f --tail=50"
fi

echo "==> Done. Frontend: ${FRONTEND_URL}  API: ${API_URL}/health"
