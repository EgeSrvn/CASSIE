#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: runfastqc <reads.fastq(.gz)> [out_dir]"
  exit 1
fi

READS_PATH="$1"
OUT_DIR_ARG="${2:-}"

# Absolute path to reads
if command -v realpath >/dev/null 2>&1; then
  READS_ABS="$(realpath "$READS_PATH")"
else
  READS_ABS="$(cd "$(dirname "$READS_PATH")" && pwd)/$(basename "$READS_PATH")"
fi

if [ ! -f "$READS_ABS" ]; then
  echo "Error: reads file not found: $READS_ABS"
  exit 1
fi

READS_DIR="$(dirname "$READS_ABS")"
READS_FILE="$(basename "$READS_ABS")"

# Output directory (default: ~/fastqc_out)
if [ -n "$OUT_DIR_ARG" ]; then
  if command -v realpath >/dev/null 2>&1; then
    OUT_DIR="$(realpath "$OUT_DIR_ARG")"
  else
    OUT_DIR="$(cd "$(dirname "$OUT_DIR_ARG")" && pwd)/$(basename "$OUT_DIR_ARG")"
  fi
else
  OUT_DIR="/data/fastqc_out"
fi

# In a container, $HOSTNAME is typically the container id; Docker accepts it for --volumes-from.
SELF_CONTAINER="${HOSTNAME}"

docker run --rm \
  --volumes-from "$SELF_CONTAINER" \
  -w "$READS_DIR" \
  --entrypoint /bin/sh \
  fastqc:0.12.1 \
  -lc "mkdir -p \"$OUT_DIR\" && exec fastqc -o \"$OUT_DIR\" \"$READS_FILE\""

echo "FastQC finished. Output: ${OUT_DIR}/"
