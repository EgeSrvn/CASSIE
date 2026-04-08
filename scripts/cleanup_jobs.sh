#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${KUBERNETES_NAMESPACE:-default}"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl is required but was not found in PATH."
  exit 1
fi

kubectl delete jobs -n "$NAMESPACE" -l app.kubernetes.io/name=cassie-pipeline --ignore-not-found=true
