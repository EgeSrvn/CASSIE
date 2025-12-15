
nextflow.enable.dsl=2

params.input = "/data/ege_1765750669_SRR24940081_fastqc"
params.outdir = "$baseDir/results"


process FASTQC {
    publishDir "$params.outdir/FastQC", [mode: 'copy']

    input:
    path reads

    output:
    path "out/*"

    script:
    """
    mkdir -p out
    runfastqc "$reads" "/data"
    """
}

workflow {
    data_ch = Channel.fromPath(params.input)

    FASTQC(data_ch)
}

