#!/bin/bash
set -e

echo "Building FastQC image..."
docker build -t fastqc:0.12.1 ./fastqc

echo "Building SPAdes image..."
docker build -t spades:3.15.5 ./spades

echo "Building GenomeScope2 image..."
docker build -t genomescope2 ./genomescope2

echo "All images built successfully."