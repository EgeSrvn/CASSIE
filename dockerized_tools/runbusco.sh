#!/bin/bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: runbusco <assembly.fasta> <outdir>"
  exit 1
fi

mkdir -p "$2"
cd "$2"
busco -i "$1" -m genome --auto-lineage -o busco_run
