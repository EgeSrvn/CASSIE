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
from typing import Any, Dict, List, Optional


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
                "busco -i /data/<assembly.fasta> -m genome --auto-lineage -o busco_out"
            ],
            "expected_outputs": ["busco_out/short_summary.txt", "busco_out/short_summary.json"],
        },
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


def get_tool_registry() -> List[Dict[str, Any]]:
    """Return a copy of the full registry."""
    return deepcopy(TOOL_REGISTRY)


def get_tool_by_index(index: int) -> Optional[Dict[str, Any]]:
    """Return a tool by its current registry index."""
    if 0 <= index < len(TOOL_REGISTRY):
        return deepcopy(TOOL_REGISTRY[index])
    return None


def get_tool_by_id(tool_id: str) -> Optional[Dict[str, Any]]:
    """Return a tool by its stable string identifier."""
    for tool in TOOL_REGISTRY:
        if tool["id"] == tool_id:
            return deepcopy(tool)
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
    return normalized_requirement in {
        str(item).strip().lower()
        for item in produced
        if str(item).strip()
    }


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
