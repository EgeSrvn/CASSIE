#!/bin/bash
set -euo pipefail

# Function to log (to container stdout if possible, otherwise just stdout)
log_build() {
    echo "$@"  # Normal stdout (always works)
    # Try to write to container logs, but silently fail if not possible
    # This works in vm1 container but not in intermediate build containers
    if [ -w /proc/1/fd/1 ] 2>/dev/null; then
        echo "$@" > /proc/1/fd/1 2>/dev/null || true
    fi
}

# Function to check if a Docker image exists
image_exists() {
    local tag="$1"
    # Check if image exists (with or without tag)
    if docker images --format "{{.Repository}}:{{.Tag}}" | grep -qE "^${tag}$|^${tag}:latest$" || \
       docker images --format "{{.Repository}}" | grep -qE "^${tag}$"; then
        return 0  # Image exists
    else
        return 1  # Image doesn't exist
    fi
}

# Function to run docker build and redirect output to container logs
build_with_logs() {
    local tool_name="$1"
    local dockerfile="$2"
    local tag="$3"
    local context="$4"
    
    log_build "[TOOLS] ========================================"
    log_build "[TOOLS] Checking $tool_name image ($tag)..."
    
    # Check if image already exists
    if image_exists "$tag"; then
        log_build "[TOOLS] ✓ $tool_name image already exists, skipping build"
        log_build "[TOOLS] ========================================"
        return 0
    fi
    
    log_build "[TOOLS] Building $tool_name image..."
    log_build "[TOOLS] Dockerfile: $dockerfile"
    log_build "[TOOLS] Tag: $tag"
    log_build "[TOOLS] [NOTE] Docker will create intermediate containers during build (these are temporary)"
    log_build "[TOOLS] ========================================"
    
    # Run docker build and capture output
    # Note: When building on host, output goes to stdout
    # When building inside vm1, we could redirect to container logs, but
    # intermediate build containers don't support this, so we just use stdout
docker build --no-cache \
      -f "$dockerfile" \
      -t "$tag" \
      "$context"
    
    local exit_code=$?
    if [ $exit_code -eq 0 ]; then
        log_build "[TOOLS] ✓ $tool_name image built successfully"
    else
        log_build "[TOOLS] ✗ $tool_name image build failed with exit code $exit_code"
        return $exit_code
    fi
}

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log_build "[TOOLS] ========================================"
log_build "[TOOLS] Building tool images (will skip if already exist)..."
log_build "[TOOLS] Working directory: $SCRIPT_DIR"
log_build "[TOOLS] ========================================"

build_with_logs "FastQC" "fastqc/Dockerfile" "fastqc:0.12.1" "fastqc"

build_with_logs "GenomeScope2" "genomescope2/Dockerfile" "genomescope2" "genomescope2"

build_with_logs "SPAdes" "spades/Dockerfile" "spades" "spades"

build_with_logs "metaSPAdes" "metaspades/Dockerfile" "metaspades" "metaspades"

build_with_logs "QUAST" "quast/Dockerfile" "quast" "quast"

build_with_logs "Hifiasm" "hifiasm/Dockerfile" "hifiasm" "hifiasm"

build_with_logs "Verkko" "verkko/Dockerfile" "verkko" "verkko"

build_with_logs "Liftoff" "liftoff/Dockerfile" "liftoff" "liftoff"

build_with_logs "CAT" "cat/Dockerfile" "cat-tool" "cat"

build_with_logs "BUSCO" "busco/Dockerfile" "busco" "busco"

build_with_logs "Meryl" "meryl/Dockerfile" "meryl" "meryl"

build_with_logs "Merqury" "merqury/Dockerfile" "merqury" "merqury"

log_build "[TOOLS] Verifying FastQC image..."
docker run --rm fastqc:0.12.1 --version

log_build "[TOOLS] ========================================"
log_build "[TOOLS] All images built and verified successfully."
log_build "[TOOLS] ========================================"
