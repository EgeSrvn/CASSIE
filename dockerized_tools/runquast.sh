#!/bin/bash
set -euo pipefail

ASSEMBLY="$1"
OUTROOT="$2"

TOOL="quast"
WORKDIR="/data/${TOOL}_run"

mkdir -p "$WORKDIR"
mkdir -p out

docker run --rm \
  -v /data:/data \
  quast \
  quast.py "/data/$ASSEMBLY" \
    --min-contig 500 \
    -t 4 \
    -o "$WORKDIR"

rm -rf "$OUTROOT/$TOOL"
mv "$WORKDIR" "$OUTROOT/$TOOL"
cp -r "$OUTROOT/$TOOL" out/