#!/bin/bash
set -e

if [ $# -lt 1 ]; then
    echo "Usage:"
    echo "  Single-end: ./run_spades.sh <reads.fastq.gz>"
    echo "  Paired-end: ./run_spades.sh <R1.fastq.gz> <R2.fastq.gz>"
    exit 1
fi

if [ $# -eq 1 ]; then
    # Single-end mode
    READS=$1
    docker run --rm \
        -v $(pwd):/data \
        spades:3.15.5 \
        -s /data/$READS \
        -o /data/spades_out
else
    # Paired-end mode
    R1=$1
    R2=$2
    docker run --rm \
        -v $(pwd):/data \
        spades:3.15.5 \
        -1 /data/$R1 \
        -2 /data/$R2 \
        -o /data/spades_out
fi

echo "SPAdes assembly done. Output: spades_out/"
