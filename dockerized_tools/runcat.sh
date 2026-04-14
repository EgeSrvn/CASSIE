#!/bin/bash
set -euo pipefail

if [ $# -ne 5 ]; then
  echo "Usage: runcat <alignment.hal> <reference.gff3> <reference_name.txt> <outdir> <workdir>"
  exit 1
fi

REF_NAME="$(tr -d '\r\n' < "$3")"
CONFIG_PATH="${4%/}/generated.cat.ini"
mkdir -p "$4" "$5"
printf "[ANNOTATION]\n%s = %s\n" "$REF_NAME" "$2" > "$CONFIG_PATH"

luigi --module cat RunCat \
  --hal "$1" \
  --ref-genome "$REF_NAME" \
  --config "$CONFIG_PATH" \
  --binary-mode local \
  --out-dir "$4" \
  --work-dir "$5"
