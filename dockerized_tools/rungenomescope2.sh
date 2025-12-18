#!/bin/bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: rungenomescope2 <reads_fastq(.gz)> <outdir>"
  echo "  (paths must be visible in the tenant container, usually under /data)"
  exit 1
fi

READS="$1"
OUTDIR="$2"

# Clean + create run-specific output directory
rm -rf "$OUTDIR"
mkdir -p "$OUTDIR"

# ---------------------------------------------------------
# Resolve the current tenant container id/name (SELF),
# so we can reuse all its mounts via --volumes-from.
# ---------------------------------------------------------
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

# Sanity check: reads must exist in the tenant's filesystem
if [ ! -f "$READS" ]; then
  echo "Error: reads file not found at $READS"
  exit 1
fi

# ---------------------------------------------------------
# Run GenomeScope2 container sharing ALL volumes from the
# tenant, so /data/... is identical inside the tool.
# ---------------------------------------------------------
docker run --rm \
  --volumes-from "$SELF" \
  genomescope2 \
  bash -lc "
    jellyfish count -C -m 21 -s 100M -t 4 \
      <(zcat '$READS') \
      -o '$OUTDIR/reads.jf'

    jellyfish histo '$OUTDIR/reads.jf' > '$OUTDIR/reads.histo'

    Rscript -e '
      library(genomescope2)
      genomescope2(
        input=\"$OUTDIR/reads.histo\",
        k=21,
        ploidy=1,
        read_length=150,
        output_dir=\"$OUTDIR\"
      )
    '
  "

echo "GenomeScope2 finished. Results written to: $OUTDIR"
