#!/bin/bash -ue
mkdir -p out
# Loop safely over the input list
for r in ecoli_f.fastq ecoli_r.fastq; do
    runfastqc "$r" "$PWD"
done
