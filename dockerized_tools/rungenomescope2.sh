#!/bin/bash
set -e

if [ $# -lt 1 ]; then
    echo "Usage: ./run_genomescope2.sh <reads.fastq.gz>"
    exit 1
fi

READS=$1

docker run --rm \
    -v $(pwd):/data \
    genomescope2 \
    bash -c "jellyfish count -C -m 21 -s 200M -t 8 <(zcat /data/$READS) -o counts.jf && \
             jellyfish histo counts.jf > histogram.histo && \
             Rscript -e \"genomescope2::genomescope('histogram.histo', 21, 'genomescope_output', max_kmercov=10000)\""

echo "GenomeScope2 done. Output: genomescope_output/"
