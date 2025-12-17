
nextflow.enable.dsl=2

params.outdir = System.getenv('HOME')
params.fasta = 'true'


process FASTQC {
    publishDir "$params.outdir/FastQC", mode: 'copy'
    stageInMode 'copy' 

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
    stageInMode 'copy'

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
    stageInMode 'copy'

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
    // Detected single 'fasta'
    data_ch = Channel.fromPath(params.fasta).first()

    FASTQC(data_ch)
    SPADES_out = SPADES(data_ch)
    data_ch = SPADES_out.assembly
    QUAST(data_ch)
}

