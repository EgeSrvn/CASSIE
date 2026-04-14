#!/bin/bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: runverkko <hifi reads...> <outdir>"
  exit 1
fi

OUTDIR="${@: -1}"
READS=("${@:1:$#-1}")

verkko -d "$OUTDIR" --hifi "${READS[@]}"
