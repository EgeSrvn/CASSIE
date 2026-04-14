#!/bin/bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: runhifiasm <reads...> <out_prefix>"
  exit 1
fi

OUT_PREFIX="${@: -1}"
READS=("${@:1:$#-1}")

hifiasm -o "$OUT_PREFIX" "${READS[@]}"
