#!/bin/bash
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: runquast <assembly> <reference_fasta> <outroot>"
  echo "  (assembly and reference should be paths under /data, e.g. quast_in/XYZ/contigs.fasta)"
  exit 1
fi

ASSEMBLY="$1"
REF="$2"
OUTROOT="$3"

# Absolute host path to outroot (e.g. /data/quast_out/<taskid>)
OUTROOT_ABS="$(realpath "$OUTROOT")"

# Keep your design: inputs must live under /data/...
ASM_ABS="/data/${ASSEMBLY#/data/}"
REF_ABS="/data/${REF#/data/}"

if [ ! -f "$ASM_ABS" ]; then
  echo "Error: assembly not found at $ASM_ABS"
  exit 1
fi
if [ ! -f "$REF_ABS" ]; then
  echo "Error: reference not found at $REF_ABS"
  exit 1
fi

# IMPORTANT FIX:
# Write QUAST output directly into the per-task outroot so:
# - no global /data/quast_out clobbering
# - parallel tasks are safe
QUAST_OUT="$OUTROOT_ABS"

rm -rf "$QUAST_OUT"
mkdir -p "$QUAST_OUT"

docker run --rm \
  --volumes-from "$HOSTNAME" \
  -v "$OUTROOT_ABS:$OUTROOT_ABS" \
  quast:latest \
  sh -lc "quast.py '$ASM_ABS' -r '$REF_ABS' --output-dir '$QUAST_OUT'"

echo "QUAST finished. Results written to: $QUAST_OUT"
