#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage:"
  echo "  Single-end: runspades <reads.fastq.gz | reads.fastq>"
  echo "  Paired-end: runspades <R1.fastq.gz | R1.fastq> <R2.fastq.gz | R2.fastq>"
  exit 1
fi

# Resolve absolute paths if possible
to_abs() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p"
  else
    echo "$p"
  fi
}

OUT_DIR="${HOME}/spades_out"
mkdir -p "$OUT_DIR"

THREADS="${THREADS:-8}"
MEM_GB="${MEM_GB:-16}"

if [ $# -eq 1 ]; then
  READS_ABS="$(to_abs "$1")"
  if [ ! -f "$READS_ABS" ]; then
    echo "Error: reads file not found: $READS_ABS"
    exit 1
  fi

  READS_DIR="$(dirname "$READS_ABS")"
  READS_FILE="$(basename "$READS_ABS")"

  docker run --rm \
    -v "${READS_DIR}:/in:ro" \
    -v "${OUT_DIR}:/out:rw" \
    spades:3.15.5 \
    spades.py -s "/in/${READS_FILE}" -o /out -t "${THREADS}" -m "${MEM_GB}"
else
  R1_ABS="$(to_abs "$1")"
  R2_ABS="$(to_abs "$2")"

  if [ ! -f "$R1_ABS" ]; then
    echo "Error: R1 file not found: $R1_ABS"
    exit 1
  fi
  if [ ! -f "$R2_ABS" ]; then
    echo "Error: R2 file not found: $R2_ABS"
    exit 1
  fi

  # If R1/R2 are in different directories, mount both
  R1_DIR="$(dirname "$R1_ABS")"
  R2_DIR="$(dirname "$R2_ABS")"
  R1_FILE="$(basename "$R1_ABS")"
  R2_FILE="$(basename "$R2_ABS")"

  if [ "$R1_DIR" = "$R2_DIR" ]; then
    docker run --rm \
      -v "${R1_DIR}:/in:ro" \
      -v "${OUT_DIR}:/out:rw" \
      spades:3.15.5 \
      spades.py -1 "/in/${R1_FILE}" -2 "/in/${R2_FILE}" -o /out -t "${THREADS}" -m "${MEM_GB}"
  else
    docker run --rm \
      -v "${R1_DIR}:/in1:ro" \
      -v "${R2_DIR}:/in2:ro" \
      -v "${OUT_DIR}:/out:rw" \
      spades:3.15.5 \
      spades.py -1 "/in1/${R1_FILE}" -2 "/in2/${R2_FILE}" -o /out -t "${THREADS}" -m "${MEM_GB}"
  fi
fi

echo "SPAdes finished. Output: ${OUT_DIR}/"
