#!/bin/bash -ue
mkdir -p out
runspades "ecoli_f.fastq" "ecoli_r.fastq" "$PWD"
