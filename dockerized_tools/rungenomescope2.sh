#!/bin/bash
# Don't use set -euo pipefail yet - we want to catch errors manually
set -u  # Only fail on undefined variables for now

# Function to log to both stdout and stderr (so Docker Desktop sees it)
log() {
  echo "[rungenomescope2] $@" | tee /dev/stderr
}

# Trap errors to log them before exiting
trap 'EXIT_CODE=$?; log "ERROR: Script failed at line $LINENO with exit code $EXIT_CODE"; exit $EXIT_CODE' ERR

log "Starting at $(date)"
log "Arguments: $@"

if [ $# -lt 2 ] || [ $# -gt 3 ]; then
  log "ERROR: Usage: rungenomescope2 <r1.fastq[.gz]> [r2.fastq[.gz]] <outdir>"
  log "  (last argument is output directory; reads must be visible in the tenant, usually under /data)"
  exit 1
fi

# -------------------------------
# Parse arguments
# -------------------------------
OUTDIR="${@: -1}"               # last arg
READS=("${@:1:$#-1}")           # all but last

# Resolve OUTDIR to absolute path
if command -v realpath >/dev/null 2>&1; then
  OUTDIR_ABS="$(realpath "$OUTDIR")"
else
  OUTDIR_ABS="$(cd "$(dirname "$OUTDIR")" && pwd)/$(basename "$OUTDIR")"
fi

# Clean + create run-specific output directory
rm -rf "$OUTDIR_ABS"
mkdir -p "$OUTDIR_ABS"

# -------------------------------
# Resolve tenant container id/name
# Use TENANT_CONTAINER_NAME if set (from Nextflow env), otherwise fall back to HOSTNAME
# -------------------------------
if [ -n "${TENANT_CONTAINER_NAME:-}" ]; then
  SELF="${TENANT_CONTAINER_NAME}"
  log "Using TENANT_CONTAINER_NAME from environment: $SELF"
elif [ -n "${HOSTNAME:-}" ]; then
  SELF="${HOSTNAME}"
  log "Using HOSTNAME as container ID: $SELF"
else
  # Fallback: try to get container ID from cgroup
  cg="$(tail -n 1 /proc/1/cgroup || true)"
  cid="$(echo "$cg" | sed -n 's#.*[/:]\([0-9a-f]\{12,64\}\)$#\1#p' || true)"
  if [ -n "$cid" ] && docker inspect "$cid" >/dev/null 2>&1; then
    SELF="$cid"
    log "Using container ID from cgroup: $SELF"
  fi
fi

if [ -z "$SELF" ]; then
  log "ERROR: could not resolve tenant container id/name."
  log "TENANT_CONTAINER_NAME: ${TENANT_CONTAINER_NAME:-not set}"
  log "HOSTNAME: ${HOSTNAME:-not set}"
  exit 1
fi

log "Using tenant container: $SELF"

# -------------------------------
# Check reads & ensure .gz versions
# -------------------------------
READS_GZ=()

for READ in "${READS[@]}"; do
  # Absolute path
  if command -v realpath >/dev/null 2>&1; then
    READ_ABS="$(realpath "$READ")"
  else
    READ_ABS="$(cd "$(dirname "$READ")" && pwd)/$(basename "$READ")"
  fi

  if [ ! -f "$READ_ABS" ]; then
    log "ERROR: reads file not found at $READ_ABS"
    log "Current directory: $(pwd)"
    log "Directory contents:"
    ls -la "$(dirname "$READ_ABS")" 2>&1 | head -20 || true
    exit 1
  fi

  # If already .gz, keep it; otherwise gzip to <file>.gz (once)
  case "$READ_ABS" in
    *.gz|*.GZ)
      READ_GZ="$READ_ABS"
      log "File already compressed: $READ_GZ"
      ;;
    *)
      READ_GZ="${READ_ABS}.gz"
      if [ ! -f "$READ_GZ" ]; then
        log "Gzipping $READ_ABS -> $READ_GZ ..."
        gzip -c "$READ_ABS" > "$READ_GZ"
      else
        log "Compressed file already exists: $READ_GZ"
      fi
      ;;
  esac

  READS_GZ+=("$READ_GZ")
done

# Check if genomescope2 image exists
if ! docker images genomescope2 --format "{{.Repository}}" 2>/dev/null | grep -q "^genomescope2$"; then
  log "ERROR: genomescope2 Docker image not found"
  log "Available images:"
  docker images --format "{{.Repository}}:{{.Tag}}" 2>&1 | head -10 || true
  exit 1
fi
log "GenomeScope2 Docker image found"

# Build zcat input list for inside the genomescope2 container
ZCAT_INPUTS=""
for GZ in "${READS_GZ[@]}"; do
  ZCAT_INPUTS+=" '$GZ'"
done

log "Running GenomeScope2 Docker container..."
log "Input files: ${READS_GZ[*]}"
log "Output directory: $OUTDIR_ABS"

# Run docker and stream output directly to stderr so it's visible immediately
set +e  # Temporarily disable exit on error to capture docker output
docker run --rm \
  --volumes-from "$SELF" \
  genomescope2 \
  bash -c "
    # Don't use set -e - we want to see all errors
    set -u  # Only fail on undefined variables
    
    echo '[GenomeScope2] Starting jellyfish count...' >&2
    JELLYFISH_EXIT=0
    jellyfish count -C -m 21 -s 100M -t 4 \
      <(zcat${ZCAT_INPUTS}) \
      -o '$OUTDIR_ABS/reads.jf' 2>&1 || JELLYFISH_EXIT=\$?
    
    if [ \$JELLYFISH_EXIT -ne 0 ]; then
      echo '[GenomeScope2] ERROR: jellyfish count failed with exit code '\$JELLYFISH_EXIT >&2
      exit \$JELLYFISH_EXIT
    fi
    echo '[GenomeScope2] jellyfish count completed successfully' >&2
    
    echo '[GenomeScope2] Starting jellyfish histo...' >&2
    JELLYFISH_HISTO_EXIT=0
    jellyfish histo '$OUTDIR_ABS/reads.jf' > '$OUTDIR_ABS/reads.histo' 2>&1 || JELLYFISH_HISTO_EXIT=\$?
    
    if [ \$JELLYFISH_HISTO_EXIT -ne 0 ]; then
      echo '[GenomeScope2] ERROR: jellyfish histo failed with exit code '\$JELLYFISH_HISTO_EXIT >&2
      exit \$JELLYFISH_HISTO_EXIT
    fi
    echo '[GenomeScope2] jellyfish histo completed successfully' >&2
    
    echo '[GenomeScope2] Starting R script (genomescope.R)...' >&2
    echo '[GenomeScope2] Checking if genomescope.R exists...' >&2
    if [ ! -f /opt/genomescope2.0/genomescope.R ]; then
      echo '[GenomeScope2] ERROR: genomescope.R not found at /opt/genomescope2.0/genomescope.R' >&2
      echo '[GenomeScope2] Listing /opt/genomescope2.0 contents:' >&2
      ls -la /opt/genomescope2.0/ >&2 || true
      exit 1
    fi
    echo '[GenomeScope2] genomescope.R found, running...' >&2
    RSCRIPT_EXIT=0
    # Try with standard arguments first
    Rscript /opt/genomescope2.0/genomescope.R \
      -i '$OUTDIR_ABS/reads.histo' \
      -o '$OUTDIR_ABS' \
      -k 21 \
      -p 1 2>&1 || RSCRIPT_EXIT=\$?
    
    if [ \$RSCRIPT_EXIT -ne 0 ]; then
      echo '[GenomeScope2] ERROR: R script failed with exit code '\$RSCRIPT_EXIT >&2
      exit \$RSCRIPT_EXIT
    fi
    echo '[GenomeScope2] R script completed successfully' >&2
    
    echo '[GenomeScope2] Finished successfully' >&2
  " 2>&1 | tee /dev/stderr | while IFS= read -r line || [ -n "$line" ]; do
    log "$line"
  done
DOCKER_EXIT=${PIPESTATUS[0]}
set -e  # Re-enable exit on error

if [ $DOCKER_EXIT -eq 0 ]; then
  log "GenomeScope2 finished successfully. Results written to: $OUTDIR_ABS"
  log "Checking output files..."
  ls -lh "$OUTDIR_ABS" 2>&1 | head -20 || log "WARNING: Output directory is empty or not accessible"
else
  log "ERROR: GenomeScope2 failed with exit code: $DOCKER_EXIT"
  exit $DOCKER_EXIT
fi

log "Completed at $(date)"