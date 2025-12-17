#!/bin/bash
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: runspades <r1> <r2> <outdir>"
  exit 1
fi

R1_ABS="$1"
R2_ABS="$2"
OUT_ABS="$3"


# Resolve tenant container for docker inspect
SELF=""
if docker inspect "$HOSTNAME" >/dev/null 2>&1; then
  SELF="$HOSTNAME"
else
  cg="$(cat /proc/1/cgroup | tail -n 1)"
  cid="$(echo "$cg" | sed -n 's#.*[/:]\([0-9a-f]\{12,64\}\)$#\1#p')"
  if [ -n "$cid" ] && docker inspect "$cid" >/dev/null 2>&1; then
    SELF="$cid"
  fi
fi
if [ -z "$SELF" ]; then
  echo "Error: could not resolve tenant container id/name."
  exit 1
fi

DATA_SRC="$(docker inspect "$SELF" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')"
if [ -z "$DATA_SRC" ]; then
  echo "Error: /data is not a Docker mount in the tenant container."
  exit 1
fi

mkdir -p "$OUT_ABS"

docker run --rm \
  -v "$DATA_SRC:/data" \
  spades \
  sh -lc "spades.py --careful -1 '$R1_ABS' -2 '$R2_ABS' -t 4 -m 8 -o '$OUT_ABS'"

echo "SPAdes finished. Output dir: $OUT_ABS"
