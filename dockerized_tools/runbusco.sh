#!/bin/bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: runbusco <assembly.fasta> <outdir>"
  exit 1
fi

mkdir -p "$2"
cd "$2"
BUSCO_DEFAULT_LINEAGE="${BUSCO_DEFAULT_LINEAGE:-eukaryota_odb12}"
BUSCO_DOWNLOAD_PATH="${BUSCO_DOWNLOAD_PATH:-/opt/busco_downloads}"
BUSCO_LINEAGE="${BUSCO_DOWNLOAD_PATH%/}/lineages/${BUSCO_DEFAULT_LINEAGE}"

if [ ! -d "$BUSCO_LINEAGE" ]; then
  echo "BUSCO lineage $BUSCO_LINEAGE is not cached; downloading it now..." >&2
  busco --download_path "$BUSCO_DOWNLOAD_PATH" --download "$BUSCO_DEFAULT_LINEAGE"
fi

busco -i "$1" -m genome -l "$BUSCO_LINEAGE" --download_path "$BUSCO_DOWNLOAD_PATH" --offline -o busco_run
