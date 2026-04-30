"""
Shared tool registry for CASSIE.

This module is the single source of truth for tool metadata that is used by:
- the backend API
- the emulation layer
- pipeline conversion / analysis helpers
- documentation and onboarding
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional


PRODUCED_ARTIFACT_COMPATIBILITY: Dict[str, set[str]] = {
    # Assembly FASTA outputs can be used anywhere a downstream tool expects
    # a specific genome/assembly role.
    "assembly": {"assembly", "target_genome"},
    # Annotation outputs can satisfy tools that explicitly ask for a reference annotation.
    "annotation": {"annotation", "reference_annotation"},
    # Meryl-generated read k-mer databases can be consumed by Merqury.
    "read_kmer_db": {"read_kmer_db"},
}

COMPRESSED_FORMAT_ALIASES: Dict[str, List[str]] = {
    "fastq": ["fastq.gz", "fq", "fq.gz"],
    "fq": ["fq.gz", "fastq", "fastq.gz"],
    "fasta": ["fasta.gz", "fa", "fa.gz", "fna", "fna.gz"],
    "fa": ["fa.gz", "fasta", "fasta.gz", "fna", "fna.gz"],
    "fna": ["fna.gz", "fasta", "fasta.gz", "fa", "fa.gz"],
    "gff": ["gff.gz", "gff3", "gff3.gz"],
    "gff3": ["gff3.gz", "gff", "gff.gz"],
    "gtf": ["gtf.gz"],
    "hal": ["hal.gz"],
    "gfa": ["gfa.gz"],
    "txt": ["txt.gz"],
    "json": ["json.gz"],
    "cfg": ["cfg.gz"],
    "conf": ["conf.gz"],
    "ini": ["ini.gz"],
    "meryl": ["meryl.tar", "meryl.tar.gz", "meryl.tgz"],
    "tar": ["tar.gz", "tgz"],
    "tgz": ["tar.gz", "tar"],
}


TOOL_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "FASTQC",
        "name": "FastQC",
        "type": "qc",
        "description": "Quality control for raw sequence data",
        "produces": ["qc_report"],
        "node_labels": [
            "Read Quality (FastQC)",
            "FastQC",
        ],
        "input_requirements": [
            {
                "type": "reads",
                "label": "Reads (FASTQ)",
                "formats": ["fastq"],
            }
        ],
        "docker": {
            "image": "fastqc:0.12.1",
            "dockerfile": "dockerized_tools/fastqc/Dockerfile",
            "context_dir": "dockerized_tools/fastqc",
            "runner_script": "dockerized_tools/runfastqc.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": ["fastqc /data/<reads.fastq> -o /data/fastqc_out"],
            "expected_outputs": ["<sample>_fastqc.html", "<sample>_fastqc.zip"],
        },
        "process_template": r'''
process FASTQC {
    publishDir "${params.outdir}/FastQC", mode: 'copy'

    input:
    path read

    output:
    path "out/*"

    script:
    """
    set -euo pipefail
    mkdir -p out

    rm -rf "/data/fastqc_out/${workflow.runName}-${task.index}"
    mkdir -p "/data/fastqc_out/${workflow.runName}-${task.index}"

    runfastqc "$read" "/data/fastqc_out/${workflow.runName}-${task.index}"

    cp -a "/data/fastqc_out/${workflow.runName}-${task.index}"/. out/
    """
}
''',
    },
    {
        "id": "SPADES",
        "name": "SPAdes",
        "type": "transform",
        "description": "Genome assembler",
        "produces": ["assembly"],
        "node_labels": [
            "Assembly (Spades)",
            "SPAdes",
            "Spades",
        ],
        "input_requirements": [
            {
                "type": "forward_reads",
                "label": "Forward Reads (R1)",
                "formats": ["fastq"],
            },
            {
                "type": "reverse_reads",
                "label": "Reverse Reads (R2)",
                "formats": ["fastq"],
            },
        ],
        "docker": {
            "image": "spades:latest",
            "dockerfile": "dockerized_tools/spades/Dockerfile",
            "context_dir": "dockerized_tools/spades",
            "runner_script": "dockerized_tools/runspades.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "spades -1 /data/<reads_1.fastq> -2 /data/<reads_2.fastq> -o /data/spades_out"
            ],
            "expected_outputs": ["spades_out/contigs.fasta", "spades_out/spades.log"],
        },
        "process_template": r'''
process SPADES {
    publishDir "$params.outdir/SPAdes", mode: 'copy'

    input:
    tuple path(r1), path(r2)

    output:
    path "out/spades/${workflow.runName}-${task.index}/contigs.fasta", emit: assembly
    path "out/spades/${workflow.runName}-${task.index}/*",             emit: files



    script:
    """
    set -euo pipefail

    # Stage reads into /data (host-mountable)
    rm -rf "/data/spades_in/${workflow.runName}-${task.index}"
    mkdir -p "/data/spades_in/${workflow.runName}-${task.index}"

    cp "$r1" "/data/spades_in/${workflow.runName}-${task.index}/r1.fastq"
    cp "$r2" "/data/spades_in/${workflow.runName}-${task.index}/r2.fastq"

    rm -rf "/data/spades_out/${workflow.runName}-${task.index}"
    mkdir -p "/data/spades_out/${workflow.runName}-${task.index}"

    # Run SPAdes on /data paths
    runspades "/data/spades_in/${workflow.runName}-${task.index}/r1.fastq" \
            "/data/spades_in/${workflow.runName}-${task.index}/r2.fastq" \
            "/data/spades_out/${workflow.runName}-${task.index}"

    # Bring results into workdir (so Nextflow can publish/capture outputs)
    mkdir -p "out/spades/${workflow.runName}-${task.index}"
    cp -a "/data/spades_out/${workflow.runName}-${task.index}"/. "out/spades/${workflow.runName}-${task.index}/"
    """


}
''',
    },
    {
        "id": "QUAST",
        "name": "QUAST",
        "type": "qc",
        "description": "Assembly quality assessment",
        "produces": ["qc_report"],
        "node_labels": [
            "Quality Assessment for Assembly (QUAST)",
            "QUAST",
            "Quast",
        ],
        "input_requirements": [
            {
                "type": "assembly",
                "label": "Assembly File (FASTA)",
                "formats": ["fasta"],
            },
            {
                "type": "reference",
                "label": "Reference Genome (FASTA)",
                "formats": ["fasta"],
            },
        ],
        "docker": {
            "image": "quast:latest",
            "dockerfile": "dockerized_tools/quast/Dockerfile",
            "context_dir": "dockerized_tools/quast",
            "runner_script": "dockerized_tools/runquast.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "quast.py /data/<assembly.fasta> -r /data/<reference.fasta> -o /data/quast_out"
            ],
            "expected_outputs": ["quast_out/report.html", "quast_out/report.tsv"],
        },
        "process_template": r'''
process QUAST {
    publishDir "${params.outdir}/QUAST", mode: 'copy'

    input:
    tuple path(assembly), path(ref)

    output:
    path "out/*"

    script:
    """
    set -euo pipefail
    mkdir -p out

    # Stage inputs into /data so the QUAST container
    # sees them via --volumes-from (same pattern as SPAdes)
    rm -rf "/data/quast_in/${workflow.runName}-${task.index}"
    mkdir -p "/data/quast_in/${workflow.runName}-${task.index}"

    cp "$assembly" "/data/quast_in/${workflow.runName}-${task.index}/contigs.fasta"
    cp "$ref"      "/data/quast_in/${workflow.runName}-${task.index}/reference.fasta"

    rm -rf "/data/quast_out/${workflow.runName}-${task.index}"
    mkdir -p "/data/quast_out/${workflow.runName}-${task.index}"

    # Call runquast with absolute /data paths
    runquast "/data/quast_in/${workflow.runName}-${task.index}/contigs.fasta" \
             "/data/quast_in/${workflow.runName}-${task.index}/reference.fasta" \
             "/data/quast_out/${workflow.runName}-${task.index}"

    # Bring results back into the Nextflow workdir
    cp -a "/data/quast_out/${workflow.runName}-${task.index}"/. out/
    ls -la out
    """
}
''',
    },
    {
        "id": "GENOMESCOPE2",
        "name": "GenomeScope2",
        "type": "qc",
        "description": "Reference-free profiling",
        "produces": ["kmer_profile"],
        "node_labels": [
            "Genomic Property Estimation (GenomeScope2)",
            "GenomeScope2",
        ],
        "input_requirements": [
            {
                "type": "reads",
                "label": "Reads (FASTQ)",
                "formats": ["fastq"],
            }
        ],
        "docker": {
            "image": "genomescope2:latest",
            "dockerfile": "dockerized_tools/genomescope2/Dockerfile",
            "context_dir": "dockerized_tools/genomescope2",
            "runner_script": "dockerized_tools/rungenomescope2.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "rungenomescope2 /data/<reads.fastq>... /data/genomescope2_out"
            ],
            "expected_outputs": ["genomescope2_out/summary.txt", "genomescope2_out/model.txt"],
        },
        "process_template": r'''
process GENOMESCOPE2 {
    publishDir "${params.outdir}/GenomeScope2", mode: 'copy'

    input:
    path reads

    output:
    path "out/*"

    script:
    """
    set -euo pipefail
    mkdir -p out

    # Stage paired reads into /data so the GenomeScope2 container
    # sees them via --volumes-from (same pattern as SPAdes)
    rm -rf "/data/genomescope2_in/${workflow.runName}-${task.index}"
    mkdir -p "/data/genomescope2_in/${workflow.runName}-${task.index}"

    READ_ARGS=()
    for read in $reads; do
        staged="/data/genomescope2_in/${workflow.runName}-${task.index}/$(basename "$read")"
        cp "$read" "$staged"
        READ_ARGS+=("$staged")
    done

    rm -rf "/data/genomescope2_out/${workflow.runName}-${task.index}"
    mkdir -p "/data/genomescope2_out/${workflow.runName}-${task.index}"

    # Call rungenomescope2 with all staged FASTQ inputs
    rungenomescope2 "${READ_ARGS[@]}" "/data/genomescope2_out/${workflow.runName}-${task.index}"

    # Bring results back into the Nextflow workdir
    cp -a "/data/genomescope2_out/${workflow.runName}-${task.index}"/. out/
    ls -la out
    """
}
''',
    },
    {
        "id": "METASPADES",
        "name": "metaSPAdes",
        "type": "transform",
        "description": "Metagenome assembly from paired short reads",
        "produces": ["assembly"],
        "node_labels": [
            "Metagenome Assembly (metaSPAdes)",
            "metaSPAdes",
            "MetaSPAdes",
        ],
        "input_requirements": [
            {
                "type": "forward_reads",
                "label": "Forward Reads (R1)",
                "formats": ["fastq"],
            },
            {
                "type": "reverse_reads",
                "label": "Reverse Reads (R2)",
                "formats": ["fastq"],
            },
        ],
        "docker": {
            "image": "metaspades:latest",
            "dockerfile": "dockerized_tools/metaspades/Dockerfile",
            "context_dir": "dockerized_tools/metaspades",
            "runner_script": "dockerized_tools/runmetaspades.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "spades.py --meta -1 /data/<reads_1.fastq> -2 /data/<reads_2.fastq> -o /data/metaspades_out"
            ],
            "expected_outputs": ["metaspades_out/contigs.fasta", "metaspades_out/spades.log"],
        },
    },
    {
        "id": "HIFIASM",
        "name": "Hifiasm",
        "type": "transform",
        "description": "HiFi long-read genome assembly",
        "produces": ["assembly"],
        "node_labels": [
            "Assembly (Hifiasm)",
            "Hifiasm",
            "hifiasm",
        ],
        "input_requirements": [
            {
                "type": "hifi_reads",
                "label": "HiFi Reads (FASTQ/FASTA)",
                "formats": ["fastq", "fasta"],
            }
        ],
        "docker": {
            "image": "hifiasm:latest",
            "dockerfile": "dockerized_tools/hifiasm/Dockerfile",
            "context_dir": "dockerized_tools/hifiasm",
            "runner_script": "dockerized_tools/runhifiasm.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "hifiasm -o /data/hifiasm_out/assembly -t 4 /data/<reads.fastq>"
            ],
            "expected_outputs": [
                "hifiasm_out/assembly.bp.p_ctg.gfa",
                "hifiasm_out/assembly.primary.fasta",
                "hifiasm_out/assembly.log",
            ],
        },
    },
    {
        "id": "VERKKO",
        "name": "Verkko",
        "type": "transform",
        "description": "Telomere-to-telomere long-read assembly pipeline",
        "produces": ["assembly"],
        "node_labels": [
            "Assembly (Verkko)",
            "Verkko",
            "verkko",
        ],
        "input_requirements": [
            {
                "type": "hifi_reads",
                "label": "HiFi Reads (FASTQ/FASTA)",
                "formats": ["fastq", "fasta"],
            }
        ],
        "docker": {
            "image": "verkko:latest",
            "dockerfile": "dockerized_tools/verkko/Dockerfile",
            "context_dir": "dockerized_tools/verkko",
            "runner_script": "dockerized_tools/runverkko.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "verkko -d /data/verkko_out --hifi /data/<reads.fastq>"
            ],
            "expected_outputs": ["verkko_out/assembly.fasta", "verkko_out/assembly.gfa"],
        },
    },
    {
        "id": "LIFTOFF",
        "name": "Liftoff",
        "type": "annotation",
        "description": "Lift annotations from a reference genome to a target assembly",
        "produces": ["annotation"],
        "node_labels": [
            "Annotation Lift Over (Liftoff)",
            "Liftoff",
            "liftoff",
        ],
        "input_requirements": [
            {
                "type": "target_genome",
                "label": "Target Genome (FASTA)",
                "formats": ["fasta"],
            },
            {
                "type": "reference_genome",
                "label": "Reference Genome (FASTA)",
                "formats": ["fasta"],
            },
            {
                "type": "annotation",
                "label": "Reference Annotation (GFF/GTF)",
                "formats": ["gff", "gff3", "gtf"],
            },
        ],
        "docker": {
            "image": "liftoff:latest",
            "dockerfile": "dockerized_tools/liftoff/Dockerfile",
            "context_dir": "dockerized_tools/liftoff",
            "runner_script": "dockerized_tools/runliftoff.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "liftoff -g /data/<annotation.gff3> -o /data/liftoff_out/liftoff.gff3 /data/<target.fasta> /data/<reference.fasta>"
            ],
            "expected_outputs": ["liftoff_out/liftoff.gff3", "liftoff_out/liftoff_unmapped.txt"],
        },
    },
    {
        "id": "CAT",
        "name": "CAT",
        "type": "annotation",
        "description": "Comparative Annotation Toolkit on HAL alignments",
        "produces": ["annotation"],
        "node_labels": [
            "Comparative Annotation Toolkit (CAT)",
            "Comparative Annotation Toolkit",
            "CAT",
        ],
        "input_requirements": [
            {
                "type": "hal_alignment",
                "label": "HAL Alignment",
                "formats": ["hal"],
            },
            {
                "type": "reference_annotation",
                "label": "Reference Annotation (GFF/GTF)",
                "formats": ["gff", "gff3", "gtf"],
            },
            {
                "type": "reference_genome_name",
                "label": "Reference Genome Name (TXT)",
                "formats": ["txt"],
            },
        ],
        "docker": {
            "image": "cat-tool:latest",
            "dockerfile": "dockerized_tools/cat/Dockerfile",
            "context_dir": "dockerized_tools/cat",
            "runner_script": "dockerized_tools/runcat.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "luigi --module cat RunCat --hal=/data/<alignment.hal> --ref-genome=$(cat /data/<reference_name.txt>) --config=/data/generated.cat.ini --out-dir=/data/cat_out --work-dir=/data/cat_work"
            ],
            "expected_outputs": ["cat_out", "cat_work"],
        },
    },
    {
        "id": "BUSCO",
        "name": "BUSCO",
        "type": "qc",
        "description": "Assembly completeness assessment using conserved orthologs",
        "produces": ["qc_report"],
        "node_labels": [
            "Assembly Completeness (BUSCO)",
            "BUSCO",
            "Busco",
        ],
        "input_requirements": [
            {
                "type": "assembly",
                "label": "Assembly or Genome (FASTA)",
                "formats": ["fasta"],
            }
        ],
        "docker": {
            "image": "busco:latest",
            "dockerfile": "dockerized_tools/busco/Dockerfile",
            "context_dir": "dockerized_tools/busco",
            "runner_script": "dockerized_tools/runbusco.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "busco -i /data/<assembly.fasta> -m genome -l /opt/busco_downloads/lineages/eukaryota_odb12 --download_path /opt/busco_downloads --offline -o busco_out"
            ],
            "expected_outputs": ["busco_out/short_summary.txt", "busco_out/short_summary.json"],
        },
    },
    {
        "id": "MERYL",
        "name": "Meryl",
        "type": "transform",
        "description": "Build a read-derived meryl k-mer database archive for downstream Merqury evaluation",
        "produces": ["read_kmer_db"],
        "node_labels": [
            "Read k-mer Database Build (Meryl)",
            "Meryl",
            "meryl",
        ],
        "input_requirements": [
            {
                "type": "reads",
                "label": "Reads (FASTQ)",
                "formats": ["fastq"],
            }
        ],
        "docker": {
            "image": "meryl:latest",
            "dockerfile": "dockerized_tools/meryl/Dockerfile",
            "context_dir": "dockerized_tools/meryl",
            "runner_script": "dockerized_tools/runmeryl.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "runmeryl /data/meryl_out /data/<reads.fastq>..."
            ],
            "expected_outputs": ["meryl_out/reads.meryl.tar.gz"],
        },
        "process_template": r'''
process MERYL {
    publishDir "${params.outdir}/Meryl", mode: 'copy'

    input:
    path reads

    output:
    path "out/*"

    script:
    """
    set -euo pipefail
    mkdir -p out

    rm -rf "/data/meryl_in/${workflow.runName}-${task.index}"
    mkdir -p "/data/meryl_in/${workflow.runName}-${task.index}"

    READ_ARGS=()
    for read in $reads; do
        staged="/data/meryl_in/${workflow.runName}-${task.index}/$(basename "$read")"
        cp "$read" "$staged"
        READ_ARGS+=("$staged")
    done

    rm -rf "/data/meryl_out/${workflow.runName}-${task.index}"
    mkdir -p "/data/meryl_out/${workflow.runName}-${task.index}"

    runmeryl "/data/meryl_out/${workflow.runName}-${task.index}" "${READ_ARGS[@]}"

    cp -a "/data/meryl_out/${workflow.runName}-${task.index}"/. out/
    """
}
''',
    },
    {
        "id": "MERQURY",
        "name": "Merqury",
        "type": "qc",
        "description": "Reference-free k-mer-based assembly evaluation",
        "produces": ["qc_report"],
        "node_labels": [
            "Assembly k-mer Evaluation (Merqury)",
            "Merqury",
            "merqury",
        ],
        "input_requirements": [
            {
                "type": "assembly",
                "label": "Assembly (FASTA)",
                "formats": ["fasta"],
            },
            {
                "type": "read_kmer_db",
                "label": "Read k-mer DB Archive (.meryl.tar.gz or .meryl.tgz)",
                "formats": ["meryl"],
            },
        ],
        "docker": {
            "image": "merqury:latest",
            "dockerfile": "dockerized_tools/merqury/Dockerfile",
            "context_dir": "dockerized_tools/merqury",
            "runner_script": "dockerized_tools/runmerqury.sh",
        },
        "kubernetes": {
            "command": ["bash", "-lc"],
            "args_template": [
                "merqury.sh /data/<reads.meryl.tar.gz> /data/<assembly.fasta> /data/merqury_out"
            ],
            "expected_outputs": ["merqury_out", "merqury_out.qv"],
        },
    },
]


TOOL_EDITABLE_FLAGS: Dict[str, List[Dict[str, Any]]] = {
    "FASTQC": [
        {
            "key": "nogroup",
            "label": "Disable Base Grouping",
            "description": "Do not group bases >50 bp into bins in the plots.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "noextract",
            "label": "Keep ZIP Only",
            "description": "Do not unzip the FastQC archive after analysis.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "svg",
            "label": "Generate SVG Icons",
            "description": "Use SVG images in the HTML report where supported.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "casava",
            "label": "CASAVA Mode",
            "description": "Treat the input as CASAVA-grouped reads.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "nano",
            "label": "Nanopore Mode",
            "description": "Enable Nanopore-specific processing mode.",
            "type": "boolean",
            "default": False,
        },
    ],
    "SPADES": [
        {
            "key": "careful",
            "label": "Careful Mode",
            "description": "Reduce mismatches and short indels in the assembly.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "only_assembler",
            "label": "Skip Error Correction",
            "description": "Run the assembler stage only.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "cov_cutoff",
            "label": "Coverage Cutoff",
            "description": "Use a positive number, auto, or off.",
            "type": "string",
            "default": "off",
            "pattern": r"^(auto|off|\d+(?:\.\d+)?)$",
            "placeholder": "auto, off, or 10.5",
            "example": "auto",
            "error_message": "Enter auto, off, or a positive number such as 10.5.",
        },
        {
            "key": "phred_offset",
            "label": "PHRED Offset",
            "description": "Leave on auto unless the read encoding is known.",
            "type": "select",
            "default": "auto",
            "options": [
                {"label": "Auto Detect", "value": "auto"},
                {"label": "PHRED+33", "value": "33"},
                {"label": "PHRED+64", "value": "64"},
            ],
        },
    ],
    "QUAST": [
        {
            "key": "gene_finding",
            "label": "Run Gene Finding",
            "description": "Enable QUAST gene finding when appropriate.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "large",
            "label": "Large Genome Mode",
            "description": "Tune QUAST for larger and more complex genomes.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "fragmented",
            "label": "Fragmented Genome Mode",
            "description": "Use QUAST fragmented reference mode.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "memory_efficient",
            "label": "Memory Efficient Mode",
            "description": "Prefer lower-memory QUAST behavior.",
            "type": "boolean",
            "default": False,
        },
    ],
    "GENOMESCOPE2": [
        {
            "key": "ploidy",
            "label": "Expected Ploidy",
            "description": "Expected ploidy used by GenomeScope2.",
            "type": "integer",
            "default": 1,
            "min": 1,
            "max": 16,
            "placeholder": "e.g. 2",
            "example": "2",
        },
        {
            "key": "initial_coverage",
            "label": "Initial Coverage Guess",
            "description": "Optional initial estimate for the homozygous coverage peak.",
            "type": "integer",
            "default": 0,
            "min": 0,
            "placeholder": "e.g. 40",
            "example": "40",
        },
        {
            "key": "max_kmer_coverage",
            "label": "Maximum K-mer Coverage",
            "description": "Ignore k-mers above this coverage during fitting.",
            "type": "integer",
            "default": 0,
            "min": 0,
            "placeholder": "e.g. 10000",
            "example": "10000",
        },
        {
            "key": "jellyfish_hash_size",
            "label": "Jellyfish Hash Size",
            "description": "Jellyfish count table size such as 50M or 2G.",
            "type": "string",
            "default": "50M",
            "pattern": r"^\d+[KMG]$",
            "placeholder": "e.g. 1G",
            "example": "1G",
            "error_message": "Use a value like 50M, 500M, or 2G.",
        },
    ],
    "METASPADES": [
        {
            "key": "only_assembler",
            "label": "Skip Error Correction",
            "description": "Run the assembler stage only.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "phred_offset",
            "label": "PHRED Offset",
            "description": "Leave on auto unless the read encoding is known.",
            "type": "select",
            "default": "auto",
            "options": [
                {"label": "Auto Detect", "value": "auto"},
                {"label": "PHRED+33", "value": "33"},
                {"label": "PHRED+64", "value": "64"},
            ],
        },
    ],
    "HIFIASM": [
        {
            "key": "mode",
            "label": "Assembly Mode",
            "description": "Choose PacBio HiFi or ONT assembly mode.",
            "type": "select",
            "default": "hifi",
            "options": [
                {"label": "PacBio HiFi", "value": "hifi"},
                {"label": "Oxford Nanopore", "value": "ont"},
            ],
        },
        {
            "key": "disable_dup_purging",
            "label": "Disable Duplication Purging",
            "description": "Equivalent to hifiasm -l0 for inbred or homozygous genomes.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "small_genome_no_bloom",
            "label": "Disable Bloom Filter",
            "description": "Equivalent to hifiasm -f0 for smaller genomes.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "write_paf",
            "label": "Write PAF Alignments",
            "description": "Emit additional PAF overlap output.",
            "type": "boolean",
            "default": False,
        },
    ],
    "VERKKO": [
        {
            "key": "haploid",
            "label": "Haploid Mode",
            "description": "Run Verkko in haploid mode.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "uneven_depth",
            "label": "Uneven Depth Mode",
            "description": "Use settings intended for uneven sequencing depth.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "telomere_motif",
            "label": "Telomere Motif",
            "description": "Override the default vertebrate telomere repeat motif.",
            "type": "string",
            "default": "",
            "pattern": r"^$|^[ACGTacgt]+$",
            "placeholder": "e.g. CCCTAA",
            "example": "CCCTAA",
            "error_message": "Use only A, C, G, and T characters.",
        },
    ],
    "LIFTOFF": [
        {
            "key": "coverage_threshold",
            "label": "Coverage Threshold",
            "description": "Minimum alignment coverage required for a mapping.",
            "type": "number",
            "default": 0.5,
            "min": 0.0,
            "max": 1.0,
            "placeholder": "e.g. 0.75",
            "example": "0.75",
        },
        {
            "key": "identity_threshold",
            "label": "Sequence Identity Threshold",
            "description": "Minimum child feature sequence identity required for a mapping.",
            "type": "number",
            "default": 0.5,
            "min": 0.0,
            "max": 1.0,
            "placeholder": "e.g. 0.9",
            "example": "0.9",
        },
        {
            "key": "flank_fraction",
            "label": "Flanking Fraction",
            "description": "Fraction of flanking sequence to align with each gene.",
            "type": "number",
            "default": 0.0,
            "min": 0.0,
            "max": 1.0,
            "placeholder": "e.g. 0.2",
            "example": "0.2",
        },
        {
            "key": "exclude_partial",
            "label": "Exclude Partial Mappings",
            "description": "Write partial or low-identity mappings to the unmapped file instead of the main output.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "copies",
            "label": "Search for Extra Gene Copies",
            "description": "Look for additional gene copies in the target assembly.",
            "type": "boolean",
            "default": False,
        },
    ],
    "CAT": [
        {
            "key": "augustus",
            "label": "Run Augustus",
            "description": "Enable CAT Augustus annotation stages.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "augustus_species",
            "label": "Augustus Species",
            "description": "Species model used by Augustus when enabled.",
            "type": "string",
            "default": "",
            "placeholder": "e.g. human",
            "example": "human",
        },
        {
            "key": "augustus_utr_off",
            "label": "Disable Augustus UTR Prediction",
            "description": "Turn off Augustus UTR prediction when the species model lacks a UTR model.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "assembly_hub",
            "label": "Build Assembly Hub",
            "description": "Generate CAT assembly hub outputs.",
            "type": "boolean",
            "default": False,
        },
    ],
    "BUSCO": [
        {
            "key": "mode",
            "label": "BUSCO Mode",
            "description": "Choose the BUSCO analysis mode.",
            "type": "select",
            "default": "genome",
            "options": [
                {"label": "Genome", "value": "genome"},
                {"label": "Proteins", "value": "proteins"},
                {"label": "Transcriptome", "value": "transcriptome"},
            ],
        },
        {
            "key": "lineage_dataset",
            "label": "Lineage Dataset",
            "description": "Dataset name or local path used by BUSCO.",
            "type": "string",
            "default": "",
            "placeholder": "e.g. eukaryota_odb12",
            "example": "eukaryota_odb12",
        },
        {
            "key": "auto_lineage",
            "label": "Auto Lineage",
            "description": "Let BUSCO choose the most appropriate lineage automatically.",
            "type": "select",
            "default": "off",
            "options": [
                {"label": "Off", "value": "off"},
                {"label": "Auto", "value": "auto-lineage"},
                {"label": "Auto (Eukaryota)", "value": "auto-lineage-euk"},
                {"label": "Auto (Prokaryota)", "value": "auto-lineage-prok"},
            ],
        },
        {
            "key": "augustus",
            "label": "Use Augustus",
            "description": "Enable Augustus in supported BUSCO runs.",
            "type": "boolean",
            "default": False,
        },
        {
            "key": "augustus_species",
            "label": "Augustus Species",
            "description": "Species model used when Augustus is enabled.",
            "type": "string",
            "default": "",
            "placeholder": "e.g. fly",
            "example": "fly",
        },
    ],
    "MERYL": [
        {
            "key": "kmer_size",
            "label": "k-mer Size",
            "description": "k-mer size used when building the Meryl database.",
            "type": "integer",
            "default": 21,
            "min": 15,
            "max": 127,
        },
    ],
    "MERQURY": [],
}


def _build_default_flag_values(flag_definitions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        str(flag.get("key")): deepcopy(flag.get("default"))
        for flag in flag_definitions
        if str(flag.get("key") or "").strip()
    }


def _enrich_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    enriched = deepcopy(tool)
    for requirement in enriched.get("input_requirements", []) or []:
        formats = []
        seen_formats = set()
        for format_name in requirement.get("formats", []) or []:
            normalized = str(format_name or "").strip().lower().lstrip(".")
            for candidate in [normalized, *COMPRESSED_FORMAT_ALIASES.get(normalized, [])]:
                if candidate and candidate not in seen_formats:
                    formats.append(candidate)
                    seen_formats.add(candidate)
        requirement["formats"] = formats
    flag_definitions = deepcopy(TOOL_EDITABLE_FLAGS.get(str(tool.get("id") or ""), []))
    enriched["editable_flags"] = flag_definitions
    enriched["default_flag_values"] = _build_default_flag_values(flag_definitions)
    return enriched


def get_tool_editable_flags(tool_id: str) -> List[Dict[str, Any]]:
    """Return editable flag definitions for a tool."""
    return deepcopy(TOOL_EDITABLE_FLAGS.get(str(tool_id or "").strip().upper(), []))


def get_tool_default_flag_values(tool_id: str) -> Dict[str, Any]:
    """Return default editable flag values for a tool."""
    return _build_default_flag_values(get_tool_editable_flags(tool_id))


def validate_tool_flag_values(tool_id: str, values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate and normalize per-tool editable flag values."""
    provided = dict(values or {})
    normalized = get_tool_default_flag_values(tool_id)
    errors: Dict[str, str] = {}

    for flag in get_tool_editable_flags(tool_id):
        key = str(flag.get("key") or "").strip()
        if not key:
            continue

        flag_type = str(flag.get("type") or "string").strip().lower()
        raw_value = provided.get(key, normalized.get(key))
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
        if raw_value in {"", None} and flag_type != "boolean":
            raw_value = flag.get("default")

        try:
            if flag_type == "boolean":
                if isinstance(raw_value, bool):
                    value = raw_value
                elif isinstance(raw_value, (int, float)):
                    value = bool(raw_value)
                else:
                    value = str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}
            elif flag_type == "integer":
                value = int(raw_value)
                min_value = flag.get("min")
                max_value = flag.get("max")
                if min_value is not None and value < int(min_value):
                    raise ValueError(f"Value must be at least {min_value}.")
                if max_value is not None and value > int(max_value):
                    raise ValueError(f"Value must be at most {max_value}.")
            elif flag_type == "number":
                value = float(raw_value)
                min_value = flag.get("min")
                max_value = flag.get("max")
                if min_value is not None and value < float(min_value):
                    raise ValueError(f"Value must be at least {min_value}.")
                if max_value is not None and value > float(max_value):
                    raise ValueError(f"Value must be at most {max_value}.")
            elif flag_type == "select":
                valid_options = {
                    str(option.get("value"))
                    for option in (flag.get("options") or [])
                    if str(option.get("value") or "").strip()
                }
                value = str(raw_value or flag.get("default") or "").strip()
                if valid_options and value not in valid_options:
                    raise ValueError("Select one of the available options.")
            else:
                value = str(raw_value or "")
                pattern = str(flag.get("pattern") or "").strip()
                if pattern and value:
                    if re.fullmatch(pattern, value) is None:
                        raise ValueError(str(flag.get("error_message") or "Invalid value."))
        except (TypeError, ValueError) as exc:
            errors[key] = str(exc)
            continue

        normalized[key] = value

    return {
        "values": normalized,
        "errors": errors,
    }


def get_tool_registry() -> List[Dict[str, Any]]:
    """Return a copy of the full registry."""
    return [_enrich_tool(tool) for tool in TOOL_REGISTRY]


def get_tool_by_index(index: int) -> Optional[Dict[str, Any]]:
    """Return a tool by its current registry index."""
    if 0 <= index < len(TOOL_REGISTRY):
        return _enrich_tool(TOOL_REGISTRY[index])
    return None


def get_tool_by_id(tool_id: str) -> Optional[Dict[str, Any]]:
    """Return a tool by its stable string identifier."""
    for tool in TOOL_REGISTRY:
        if tool["id"] == tool_id:
            return _enrich_tool(tool)
    return None


def get_tool_index_by_id(tool_id: str) -> Optional[int]:
    """Return the current registry index for a stable tool id."""
    for index, tool in enumerate(TOOL_REGISTRY):
        if tool["id"] == tool_id:
            return index
    return None


def get_tool_requirements(tool_id: str) -> List[Dict[str, Any]]:
    """Return input requirements for a tool."""
    tool = get_tool_by_id(tool_id)
    if not tool:
        return []
    return deepcopy(tool.get("input_requirements", []))


def get_tool_outputs(tool_id: str) -> List[str]:
    """Return logical artifact types produced by a tool."""
    tool = get_tool_by_id(tool_id)
    if not tool:
        return []
    return list(tool.get("produces", []))


def tool_produces_requirement(tool_or_id: Dict[str, Any] | str, requirement_type: str) -> bool:
    """Return True when a tool can satisfy a logical input requirement."""
    if isinstance(tool_or_id, dict):
        produced = tool_or_id.get("produces", [])
    else:
        produced = get_tool_outputs(str(tool_or_id))

    normalized_requirement = str(requirement_type or "").strip().lower()
    compatible_outputs = set()
    for item in produced:
        normalized_item = str(item).strip().lower()
        if not normalized_item:
            continue
        compatible_outputs.update(
            PRODUCED_ARTIFACT_COMPATIBILITY.get(normalized_item, {normalized_item})
        )

    return normalized_requirement in compatible_outputs


def get_tool_id_from_label(label: str) -> Optional[str]:
    """Resolve a pipeline node label or alias to a tool id."""
    normalized_label = (label or "").strip().lower()
    if not normalized_label:
        return None

    for tool in TOOL_REGISTRY:
        for alias in tool.get("node_labels", []):
            alias_normalized = alias.strip().lower()
            if alias_normalized == normalized_label or alias_normalized in normalized_label:
                return tool["id"]

    return None


def get_tool_names_by_indices(indices: List[int]) -> List[str]:
    """Return display names for a list of registry indices."""
    names: List[str] = []
    for index in indices:
        tool = get_tool_by_index(index)
        if tool:
            names.append(tool["name"])
    return names
