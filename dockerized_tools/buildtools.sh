#!/bin/bash
set -euo pipefail

echo "[TOOLS] Rebuilding FastQC image (no cache)..."
docker build --no-cache -t fastqc:0.12.1 ./fastqc

# echo "[TOOLS] Rebuilding SPAdes image (no cache)..."
# docker build --no-cache -t spades:3.15.5 ./spades

echo "[TOOLS] Verifying FastQC image..."
docker run --rm fastqc:0.12.1 --version

echo "[TOOLS] All images built and verified successfully."
