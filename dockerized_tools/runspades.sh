#!/bin/bash
# Don't use set -euo pipefail yet - we want to catch errors manually
set -u  # Only fail on undefined variables for now

# Function to log to both stdout and stderr (so Nextflow definitely sees it)
log() {
    echo "[runspades] $@" | tee /dev/stderr
}

# Trap errors to log them before exiting
trap 'EXIT_CODE=$?; log "ERROR: Script failed at line $LINENO with exit code $EXIT_CODE"; exit $EXIT_CODE' ERR

log "Starting at $(date)"
log "Arguments: $@"
log "Working directory: $(pwd)"
log "HOSTNAME: ${HOSTNAME:-not set}"

if [ $# -lt 3 ]; then
  log "ERROR: Usage: runspades <r1> <r2> <outdir>"
  exit 1
fi

R1_ARG="$1"
R2_ARG="$2"
OUT_ARG="$3"

# Convert relative paths to absolute paths (like runfastqc.sh does)
if command -v realpath >/dev/null 2>&1; then
  R1_ABS="$(realpath "$R1_ARG")"
  R2_ABS="$(realpath "$R2_ARG")"
  OUT_ABS="$(realpath -m "$OUT_ARG")"  # -m allows non-existent paths
else
  R1_ABS="$(cd "$(dirname "$R1_ARG")" && pwd)/$(basename "$R1_ARG")"
  R2_ABS="$(cd "$(dirname "$R2_ARG")" && pwd)/$(basename "$R2_ARG")"
  OUT_ABS="$(cd "$(dirname "$OUT_ARG")" 2>/dev/null && pwd)/$(basename "$OUT_ARG")" || OUT_ABS="$OUT_ARG"
fi

log "R1_ABS: $R1_ABS"
log "R2_ABS: $R2_ABS"
log "OUT_ABS: $OUT_ABS"

# Check if input files exist
if [ ! -f "$R1_ABS" ]; then
  log "ERROR: R1 file not found: $R1_ABS"
  log "Current directory contents:"
  ls -la "$(dirname "$R1_ABS")" 2>&1 | head -20 || true
  exit 1
fi
if [ ! -f "$R2_ABS" ]; then
  log "ERROR: R2 file not found: $R2_ABS"
  log "Current directory contents:"
  ls -la "$(dirname "$R2_ABS")" 2>&1 | head -20 || true
  exit 1
fi
log "Input files verified"

# Check Docker availability
if ! command -v docker &> /dev/null; then
  log "ERROR: docker command not found in PATH"
  log "PATH: $PATH"
  exit 1
fi
log "Docker command found: $(which docker)"

# Test Docker access
if ! docker info &> /dev/null; then
  log "ERROR: Cannot access Docker daemon"
  log "Docker info output:"
  docker info 2>&1 | head -20 || true
  exit 1
fi
log "Docker daemon accessible"

# Use TENANT_CONTAINER_NAME if set (from Nextflow env), otherwise fall back to HOSTNAME
# This is necessary because when Nextflow runs the script, $HOSTNAME is the work container,
# not the tenant container that has the /data mount.
if [ -n "${TENANT_CONTAINER_NAME:-}" ]; then
  SELF_CONTAINER="${TENANT_CONTAINER_NAME}"
  log "Using TENANT_CONTAINER_NAME from environment: $SELF_CONTAINER"
elif [ -n "${HOSTNAME:-}" ]; then
  SELF_CONTAINER="${HOSTNAME}"
  log "Using HOSTNAME as container ID: $SELF_CONTAINER"
else
  # Fallback: try to get container ID from cgroup
  cg="$(cat /proc/1/cgroup 2>/dev/null | tail -n 1 || true)"
  cid="$(echo "$cg" | sed -n 's#.*[/:]\([0-9a-f]\{12,64\}\)$#\1#p' || true)"
  if [ -n "$cid" ] && docker inspect "$cid" >/dev/null 2>&1; then
    SELF_CONTAINER="$cid"
    log "Using container ID from cgroup: $SELF_CONTAINER"
  else
    log "ERROR: could not resolve tenant container id/name."
    log "TENANT_CONTAINER_NAME: ${TENANT_CONTAINER_NAME:-not set}"
    log "HOSTNAME: ${HOSTNAME:-not set}"
    log "cgroup: $cg"
    log "extracted cid: $cid"
    exit 1
  fi
fi

# Verify container exists
if ! docker inspect "$SELF_CONTAINER" >/dev/null 2>&1; then
  log "ERROR: Container $SELF_CONTAINER does not exist or is not accessible"
  log "Available containers:"
  docker ps -a --format "{{.Names}}" 2>&1 | head -10 || true
  exit 1
fi
log "Container $SELF_CONTAINER verified"

# Check if spades image exists
if ! docker images spades --format "{{.Repository}}" 2>/dev/null | grep -q "^spades$"; then
  log "ERROR: spades Docker image not found"
  log "Available images:"
  docker images --format "{{.Repository}}:{{.Tag}}" 2>&1 | head -10 || true
  exit 1
fi
log "SPAdes Docker image found"

# Create output directory
mkdir -p "$OUT_ABS" || {
  log "ERROR: Failed to create output directory: $OUT_ABS"
  exit 1
}
log "Created output directory: $OUT_ABS"

log "Running SPAdes Docker container..."

# SPAdes configuration: Default to fast mode for testing (no --careful)
# Options:
#   --careful: Slower but more accurate (set SPADES_MODE="careful" to enable)
#   (no --careful): Faster but less accurate (default for testing)
#   --only-assembler: Fastest, skips error correction (set SPADES_MODE="only-assembler")
# Threads: Use 2 threads (VM has 2 CPUs, so 2 is safe)
# Memory: Use 4GB (VM has 4GB total, so 4GB is max)
SPADES_MODE="${SPADES_MODE:-fast}"  # Default to "fast" for testing (can be "careful" or "only-assembler")
SPADES_THREADS="${SPADES_THREADS:-2}"  # Default to 2 threads (safe for 2-CPU VM)
SPADES_MEMORY="${SPADES_MEMORY:-4}"  # Default to 4GB (safe for 4GB VM)

# Build SPAdes command based on mode
if [ "$SPADES_MODE" = "only-assembler" ]; then
  SPADES_FLAGS="--only-assembler"
  log "Using fast mode: --only-assembler (fastest, lowest quality)"
elif [ "$SPADES_MODE" = "careful" ]; then
  SPADES_FLAGS="--careful"  # Careful mode
  log "Using careful mode: --careful (slower, more accurate)"
else
  SPADES_FLAGS=""  # Default: fast mode (no --careful)
  log "Using fast mode: no --careful (faster, less accurate) - DEFAULT FOR TESTING"
fi

SPADES_CMD="spades.py $SPADES_FLAGS -1 '$R1_ABS' -2 '$R2_ABS' -t $SPADES_THREADS -m $SPADES_MEMORY -o '$OUT_ABS'"
log "Command: docker run --rm --volumes-from \"$SELF_CONTAINER\" spades sh -lc \"$SPADES_CMD\""

# Use --volumes-from instead of manual mount resolution (same pattern as runfastqc.sh)
# Capture both stdout and stderr from docker run
set +e  # Temporarily disable exit on error to capture docker output
DOCKER_OUTPUT=$(docker run --rm \
  --volumes-from "$SELF_CONTAINER" \
  spades \
  sh -lc "$SPADES_CMD" 2>&1)
DOCKER_EXIT=$?
set -e  # Re-enable exit on error

if [ $DOCKER_EXIT -eq 0 ]; then
  log "SPAdes finished successfully. Output dir: $OUT_ABS"
  log "Checking output files..."
  ls -lh "$OUT_ABS" 2>&1 | head -20 || log "WARNING: Output directory is empty or not accessible"
  echo "SPAdes finished. Output dir: $OUT_ABS"
else
  log "ERROR: SPAdes failed with exit code: $DOCKER_EXIT"
  log "Docker output:"
  echo "$DOCKER_OUTPUT" | head -50
  exit $DOCKER_EXIT
fi

log "Completed at $(date)"
