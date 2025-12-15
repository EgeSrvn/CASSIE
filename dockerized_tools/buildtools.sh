#!/bin/bash
set -euo pipefail

echo "[TOOLS] Rebuilding tool images (no cache, deterministic)..."

docker build --no-cache \
  -f fastqc/Dockerfile \
  -t fastqc:0.12.1 \
  fastqc

docker build --no-cache \
  -f genomescope2/Dockerfile \
  -t genomescope2 \
  genomescope2

docker build --no-cache \
  -f spades/Dockerfile \
  -t spades \
  spades

docker build --no-cache \
  -f quast/Dockerfile \
  -t quast \
  quast

echo "[TOOLS] Verifying FastQC image..."
docker run --rm fastqc:0.12.1 --version

echo "[TOOLS] All images built and verified successfully."
