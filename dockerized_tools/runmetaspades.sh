#!/bin/bash
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: runmetaspades <r1.fastq> <r2.fastq> <outdir>"
  exit 1
fi

spades.py --meta -1 "$1" -2 "$2" -o "$3"
