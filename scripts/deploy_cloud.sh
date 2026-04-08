#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/deploy_cloud.sh <manifest.yaml> [kubectl args...]"
  exit 1
fi

MANIFEST_PATH="$1"
shift || true

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required but was not found in PATH."
  exit 1
fi

cd "$ROOT_DIR"
kubectl apply -f "$MANIFEST_PATH" "$@"
