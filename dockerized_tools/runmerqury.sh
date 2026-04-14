#!/bin/bash
set -euo pipefail

if [ $# -ne 3 ]; then
  echo "Usage: runmerqury <reads.meryl> <assembly.fasta> <out_prefix>"
  exit 1
fi

merqury.sh "$1" "$2" "$3"
