#!/bin/bash
set -euo pipefail

# Interface compatible with FastQC
R1="$1"
R2="$2"
OUTROOT="$3"

TOOL="spades"
WORKDIR="/data/${TOOL}_run"

mkdir -p "$WORKDIR"
mkdir -p out

docker run --rm \
  -v /data:/data \
  spades \
  spades.py \
    --careful \
    -1 "/data/$R1" \
    -2 "/data/$R2" \
    -t 4 \
    -m 8 \
    -o "$WORKDIR"

rm -rf "$OUTROOT/$TOOL"
mv "$WORKDIR" "$OUTROOT/$TOOL"
cp -r "$OUTROOT/$TOOL" out/
