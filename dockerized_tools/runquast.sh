#!/bin/bash
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: runquast <assembly_fasta> <reference_fasta> <outdir>"
  echo "  (all arguments should be absolute paths visible in the tenant container,"
  echo "   typically under /data, e.g. /data/quast_in/<run>/contigs.fasta)"
  exit 1
fi

ASM="$1"
REF="$2"
OUTDIR="$3"

# Make sure output dir exists inside the tenant container filesystem
rm -rf "$OUTDIR"
mkdir -p "$OUTDIR"

# ---------------------------------------------------------
# Resolve the current tenant container id/name (SELF),
# same idea as for SPAdes: we want to reuse all mounts.
# Use TENANT_CONTAINER_NAME if set (from Nextflow env), otherwise fall back to HOSTNAME.
# This is necessary because when Nextflow runs the script, $HOSTNAME is the work container,
# not the tenant container that has the /data mount.
# ---------------------------------------------------------
if [ -n "${TENANT_CONTAINER_NAME:-}" ]; then
  SELF="${TENANT_CONTAINER_NAME}"
elif [ -n "${HOSTNAME:-}" ]; then
  SELF="${HOSTNAME}"
else
  # Fallback: try to get container ID from cgroup
  cg="$(tail -n 1 /proc/1/cgroup || true)"
  cid="$(echo "$cg" | sed -n 's#.*[/:]\([0-9a-f]\{12,64\}\)$#\1#p' || true)"
  if [ -n "$cid" ] && docker inspect "$cid" >/dev/null 2>&1; then
    SELF="$cid"
  fi
fi

if [ -z "$SELF" ]; then
  echo "Error: could not resolve tenant container id/name."
  echo "TENANT_CONTAINER_NAME: ${TENANT_CONTAINER_NAME:-not set}"
  echo "HOSTNAME: ${HOSTNAME:-not set}"
  exit 1
fi

# Basic sanity checks (inside the tenant container view)
if [ ! -f "$ASM" ]; then
  echo "Error: assembly not found at $ASM"
  exit 1
fi

if [ ! -f "$REF" ]; then
  echo "Error: reference not found at $REF"
  exit 1
fi

docker run --rm \
  --volumes-from "$SELF" \
  quast:latest \
  "$ASM" -r "$REF" --output-dir "$OUTDIR"

echo "QUAST finished. Results written to: $OUTDIR"

