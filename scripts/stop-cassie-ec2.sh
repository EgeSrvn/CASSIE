#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE_FILE="${ROOT_DIR}/docker-compose.ec2-s3.yml"

if docker compose version >/dev/null 2>&1; then
  docker compose -f "${COMPOSE_FILE}" down
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "${COMPOSE_FILE}" down
else
  echo "Docker Compose is required but was not found."
  exit 1
fi

if command -v minikube >/dev/null 2>&1; then
  echo "Stopping Minikube ..."
  minikube stop
fi

echo "CASSIE EC2 stack stopped."
