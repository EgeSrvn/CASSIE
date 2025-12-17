#!/bin/bash
set -euo pipefail

# Interface MUST match runfastqc.sh
READS="$1"
OUTROOT="$2"

TOOL="genomescope2"
WORKDIR="/data/${TOOL}_run"

# Ensure out directory exists in current work directory (Nextflow work dir)
mkdir -p "$WORKDIR"
mkdir -p out

docker run --rm \
  -v /data:/data \
  genomescope2 \
  bash -lc "
    jellyfish count -C -m 21 -s 100M -t 4 \
      <(zcat /data/$READS) \
      -o $WORKDIR/reads.jf

    jellyfish histo $WORKDIR/reads.jf > $WORKDIR/reads.histo

    Rscript -e '
      library(genomescope2)
      genomescope2(
        input=\"$WORKDIR/reads.histo\",
        k=21,
        ploidy=1,
        read_length=150,
        output_dir=\"$WORKDIR\"
      )
    '
  "

# Copy results directly to out/ in the work directory
cp -r "$WORKDIR" out/