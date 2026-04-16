#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if docker compose version >/dev/null 2>&1; then
  docker compose down
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose down
else
  echo "Docker Compose is required but was not found."
  exit 1
fi

if command -v minikube >/dev/null 2>&1; then
  echo "Deleting Minikube clusters ..."
  minikube delete --all --purge
fi

if [[ -d "${ROOT_DIR}/.cassie/kube" ]]; then
  rm -rf "${ROOT_DIR}/.cassie/kube"
fi
