#!/bin/bash
set -euo pipefail


if [ $# -lt 2 ] || [ $# -gt 3 ]; then
  echo "Usage: rungenomescope2 <r1.fastq[.gz]> [r2.fastq[.gz]] <outdir>"
  echo "  (last argument is output directory; reads must be visible in the tenant, usually under /data)"
  exit 1
fi

# -------------------------------
# Parse arguments
# -------------------------------
OUTDIR="${@: -1}"               # last arg
READS=("${@:1:$#-1}")           # all but last

# Resolve OUTDIR to absolute path
if command -v realpath >/dev/null 2>&1; then
  OUTDIR_ABS="$(realpath "$OUTDIR")"
else
  OUTDIR_ABS="$(cd "$(dirname "$OUTDIR")" && pwd)/$(basename "$OUTDIR")"
fi

# Clean + create run-specific output directory
rm -rf "$OUTDIR_ABS"
mkdir -p "$OUTDIR_ABS"

# -------------------------------
# Resolve tenant container id/name
# -------------------------------
SELF="${HOSTNAME:-}"

if ! docker inspect "$SELF" >/dev/null 2>&1; then
  cg="$(tail -n 1 /proc/1/cgroup || true)"
  cid="$(echo "$cg" | sed -n 's#.*[/:]\([0-9a-f]\{12,64\}\)$#\1#p')"
  if [ -n "${cid:-}" ] && docker inspect "$cid" >/dev/null 2>&1; then
    SELF="$cid"
  fi
fi

if [ -z "$SELF" ]; then
  echo "Error: could not resolve tenant container id/name."
  exit 1
fi

# -------------------------------
# Check reads & ensure .gz versions
# -------------------------------
READS_GZ=()

for READ in "${READS[@]}"; do
  # Absolute path
  if command -v realpath >/dev/null 2>&1; then
    READ_ABS="$(realpath "$READ")"
  else
    READ_ABS="$(cd "$(dirname "$READ")" && pwd)/$(basename "$READ")"
  fi

  if [ ! -f "$READ_ABS" ]; then
    echo "Error: reads file not found at $READ_ABS"
    exit 1
  fi

  # If already .gz, keep it; otherwise gzip to <file>.gz (once)
  if [[ "$READ_ABS" == *.gz ]]; then
    READ_GZ="$READ_ABS"
  else
    READ_GZ="${READ_ABS}.gz"
    if [ ! -f "$READ_GZ" ]; then
      echo "Gzipping $READ_ABS -> $READ_GZ ..."
      gzip -c "$READ_ABS" > "$READ_GZ"
    fi
  fi

  READS_GZ+=("$READ_GZ")
done

# Build zcat input list for inside the genomescope2 container
ZCAT_INPUTS=""
for GZ in "${READS_GZ[@]}"; do
  ZCAT_INPUTS+=" '$GZ'"
done

docker run --rm \
  --volumes-from "$SELF" \
  genomescope2 \
  bash -lc "
    set -euo pipefail

    # K-mer counting with Jellyfish from both mates (if provided)
    jellyfish count -C -m 21 -s 100M -t 4 \
      <(zcat${ZCAT_INPUTS}) \
      -o '$OUTDIR_ABS/reads.jf'

    jellyfish histo '$OUTDIR_ABS/reads.jf' > '$OUTDIR_ABS/reads.histo'

    # Run GenomeScope 2.0 using the command-line script
    Rscript /opt/genomescope2.0/genomescope.R \
      -i '$OUTDIR_ABS/reads.histo' \
      -o '$OUTDIR_ABS' \
      -k 21 \
      -p 1
  "

echo "GenomeScope2 finished. Results written to: $OUTDIR_ABS"

