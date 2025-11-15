#!/bin/bash
set -e

if [ $# -lt 1 ]; then
    echo "Usage: ./run_fastqc.sh <reads.fastq.gz>"
    exit 1
fi

READS=$1

docker run --rm \
    -v $(pwd):/data \
    fastqc:0.12.1 \
    /data/$READS \
    -o /data/fastqc_out

echo "FastQC finished. Output: fastqc_out/"
