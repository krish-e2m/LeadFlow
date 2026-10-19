#!/bin/sh
# Run this ON the VM, from the repo root, after: (1) the VM exists, (2) you've SSH'd in,
# (3) the repo is on the VM (git clone or scp), (4) you've created a real .env at the repo root
# (copy .env.example, fill in every value, set DOMAIN, POSTGRES_PASSWORD, POSTGRES_APP_PASSWORD
# to REAL values — not the dev defaults).
#
# What this does NOT do, on purpose: create the VM, configure DNS, or touch your local machine.
# Those are the parts only you can do (see docs/DEPLOYMENT.md §4-Alt.0 for VM
# creation, §4-Alt.1 step 2 for DNS).
#
# Usage: ./infra/scripts/bootstrap-vm.sh
set -eu

if [ ! -f .env ]; then
  echo "No .env at the repo root. Copy .env.example to .env and fill in real production values first." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo "Docker installed. Log out and back in (or run 'newgrp docker') for group membership to take effect, then re-run this script."
  exit 0
fi

echo "==> Building and starting the production stack..."
docker compose -f infra/docker/docker-compose.prod.yml --env-file .env up -d --build

echo "==> Waiting for Postgres to report healthy..."
for i in $(seq 1 30); do
  status=$(docker inspect -f '{{.State.Health.Status}}' leadflow_postgres 2>/dev/null || echo "starting")
  if [ "$status" = "healthy" ]; then
    break
  fi
  sleep 2
done

echo "==> Running database migrations..."
docker exec leadflow_api sh -c "cd /app && PYTHONPATH=/app alembic upgrade head"

echo "==> Done. Containers:"
docker compose -f infra/docker/docker-compose.prod.yml ps

echo ""
echo "Next: confirm DNS (A records for \$DOMAIN and api.\$DOMAIN) points at this VM's public IP,"
echo "then run the smoke test in docs/DEPLOYMENT.md §5.2 — the HTTPS cert won't issue until DNS resolves."
