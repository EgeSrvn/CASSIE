#!/bin/bash
set -euo pipefail

if [ $# -ne 4 ]; then
  echo "Usage: runliftoff <target.fasta> <reference.fasta> <annotation.gff3> <output.gff3>"
  exit 1
fi

liftoff -g "$3" -o "$4" "$1" "$2"
