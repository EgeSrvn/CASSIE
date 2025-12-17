#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: rungenomescope2 <reads.fastq.gz | reads.fastq>"
  exit 1
fi

READS_PATH="$1"

# Resolve to an absolute path if possible
if command -v realpath >/dev/null 2>&1; then
  READS_ABS="$(realpath "$READS_PATH")"
else
  READS_ABS="$READS_PATH"
fi

if [ ! -f "$READS_ABS" ]; then
  echo "Error: reads file not found: $READS_ABS"
  exit 1
fi

READS_DIR="$(dirname "$READS_ABS")"
READS_FILE="$(basename "$READS_ABS")"

# Always output to ~/genomescope2_out (independent of cwd)
OUT_DIR="${HOME}/genomescope2_out"
mkdir -p "$OUT_DIR"

# Optional tuning via env vars
KMER_SIZE="${KMER_SIZE:-21}"
HASH_SIZE="${HASH_SIZE:-200M}"
THREADS="${THREADS:-8}"
MAX_KMERCOV="${MAX_KMERCOV:-10000}"

# Run: mount input dir read-only, mount output dir read-write
docker run --rm \
  -v "${READS_DIR}:/in:ro" \
  -v "${OUT_DIR}:/out:rw" \
  genomescope2 \
  bash -lc "
    set -euo pipefail
    jellyfish count -C -m ${KMER_SIZE} -s ${HASH_SIZE} -t ${THREADS} <(zcat /in/${READS_FILE}) -o /out/counts.jf
    jellyfish histo /out/counts.jf > /out/histogram.histo
    Rscript -e \"genomescope2::genomescope('/out/histogram.histo', ${KMER_SIZE}, '/out/genomescope_output', max_kmercov=${MAX_KMERCOV})\"
  "

echo "GenomeScope2 finished. Output: ${OUT_DIR}/genomescope_output/"
