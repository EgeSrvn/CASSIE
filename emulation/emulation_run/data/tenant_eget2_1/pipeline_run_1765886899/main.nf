
nextflow.enable.dsl=2

params.outdir = System.getenv('HOME')
params.fasta = '/home/tenant_eget2_1/ecoli.fasta'
params.fastq = ['/home/tenant_eget2_1/ecoli_f.fastq', '/home/tenant_eget2_1/ecoli_r.fastq']


process FASTQC {
    publishDir "$params.outdir/FastQC", mode: 'copy'
    stageInMode 'copy'  // [FIX] Force physical copy so container can see files

    input:
    path reads

    output:
    path "out/*"

    script:
    """
    mkdir -p out
    # Loop safely over the input list
    for r in $reads; do
        runfastqc "\$r" "\$PWD"
    done
    """
}


process SPADES {
    publishDir "$params.outdir/SPAdes", mode: 'copy'
    stageInMode 'copy'  // [FIX] Force physical copy

    input:
    tuple path(r1), path(r2)

    output:
    path "out/contigs.fasta", emit: assembly
    path "out/*"

    script:
    """
    mkdir -p out
    runspades "$r1" "$r2" "\$PWD"
    """
}


process QUAST {
    publishDir "$params.outdir/QUAST", mode: 'copy'
    stageInMode 'copy'  // [FIX] Force physical copy

    input:
    path assembly

    output:
    path "out/*"

    script:
    """
    mkdir -p out
    runquast "$assembly" "\$PWD"
    """
}

workflow {
    // Detected paired list in 'fastq'
    data_ch = Channel.of( tuple(file(params.fastq[0]), file(params.fastq[1])) ).first()

    FASTQC(data_ch)
    SPADES_out = SPADES(data_ch)
    data_ch = SPADES_out.assembly
    QUAST(data_ch)
}

