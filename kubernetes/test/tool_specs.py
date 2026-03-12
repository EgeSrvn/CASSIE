"""
Variable-driven pipeline/tool specification.

This file exposes small building blocks (`INPUTS`, `TOOLS`, `CONNECTIONS`,
`FINAL_OUTPUTS`) and a helper `make_pipeline_spec()` so you can add/remove
tools, inputs or connections by editing simple variables rather than the
monolithic dict.
"""

# Basic pipeline metadata defaults
WORKDIR_MOUNT = "/data"
PUBLISH_SUBDIR = "results"

# Inputs that user provides at launch time (edit here to add/remove inputs)
INPUTS = {
    "reads_1": {"type": "path"},
    "reads_2": {"type": "path"},
    "reference_fasta": {"type": "path"},
}

# Tools / processes (edit to add/remove tools). Each tool is keyed by name.
# Keep `in` and `out` as logical names that can be connected by `CONNECTIONS`.
TOOLS = {
    "fastqc": {
        "image": "fastqc:0.12.1",
        "remote_repo": "fastqc",
        "tag": "0.12.1",
        "in": ["reads_1", "reads_2"],
        "out": ["fastqc_reports"],
        "script": r"""
mkdir -p fastqc_out
fastqc ${reads_1} ${reads_2} -o fastqc_out
""",
        "emit": {"fastqc_reports": "fastqc_out/*"},
    },

    "spades": {
        "image": "spades:latest",
        "remote_repo": "spades",
        "tag": "latest",
        "in": ["reads_1", "reads_2"],
        "out": ["contigs_fasta", "spades_dir"],
        "script": r"""
mkdir -p spades_out
spades -1 ${reads_1} -2 ${reads_2} -o spades_out
""",
        "emit": {"contigs_fasta": "spades_out/contigs.fasta", "spades_dir": "spades_out"},
    },

    "quast": {
        "image": "quast:latest",
        "remote_repo": "quast",
        "tag": "latest",
        "in": ["reference_fasta", "contigs_fasta"],
        "out": ["quast_dir"],
        "script": r"""
mkdir -p quast_out
quast.py ${contigs_fasta} -r ${reference_fasta} -o quast_out
""",
        "emit": {"quast_dir": "quast_out"},
    },
}

# Connections between tools (DAG edges). Use "from_tool.output" -> "to_tool.input" names.
CONNECTIONS = [
    {"from": "spades.contigs_fasta", "to": "quast.contigs_fasta"},
]

# Which outputs to publish as final results (tool_name.output_name strings)
FINAL_OUTPUTS = [
    "fastqc.fastqc_reports",
    "spades.spades_dir",
    "quast.quast_dir",
]


def make_pipeline_spec(name: str,
                       workdir_mount: str = WORKDIR_MOUNT,
                       publish_subdir: str = PUBLISH_SUBDIR,
                       inputs: dict = None,
                       tools: dict = None,
                       connections: list = None,
                       final_outputs: list = None) -> dict:
    """Build the PIPELINE_SPEC dict from the variable pieces.

    This makes it easy to programmatically alter `INPUTS`, `TOOLS`, or
    `CONNECTIONS` before calling this function.
    """
    return {
        "name": name,
        "workdir_mount": workdir_mount,
        "publish_subdir": publish_subdir,
        "inputs": inputs if inputs is not None else INPUTS,
        "tools": tools if tools is not None else TOOLS,
        "connections": connections if connections is not None else CONNECTIONS,
        "final_outputs": final_outputs if final_outputs is not None else FINAL_OUTPUTS,
    }


# Default pipeline spec instance (edit variables above to change composition)
PIPELINE_SPEC = make_pipeline_spec("fastqc_spades_quast")