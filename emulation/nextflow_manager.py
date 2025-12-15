import docker
import time
import shlex

# -------------------------------------------------------------------
# Tool Definitions
# -------------------------------------------------------------------
AVAILABLE_TOOLS = [
    {
        "name": "FastQC",
        "id": "FASTQC",
        "type": "qc",
        "description": "Quality control for raw sequence data",
        "process_template": '''
process FASTQC {
    publishDir "$params.outdir/FastQC", mode: 'copy'

    input:
    path reads

    output:
    path "out/*"

    script:
    """
    mkdir -p out
    # IMPORTANT: do NOT quote $reads; paired inputs become "file1 file2" and quoting breaks it.
    runfastqc $reads "$PWD/out"
    """
}
'''
    },
    {
        "name": "SPAdes",
        "id": "SPADES",
        "type": "transform",
        "description": "Genome assembler",
        "process_template": '''
process SPADES {
    publishDir "$params.outdir/SPAdes", mode: 'copy'

    input:
    tuple path(r1), path(r2)

    output:
    path "out/contigs.fasta", emit: assembly
    path "out/*",            emit: files

    script:
    """
    mkdir -p out
    runspades "$r1" "$r2" "$PWD/out"
    """
}
'''
    },
    {
        "name": "QUAST",
        "id": "QUAST",
        "type": "qc",
        "description": "Assembly quality assessment",
        "process_template": '''
process QUAST {
    publishDir "$params.outdir/QUAST", mode: 'copy'

    input:
    path assembly

    output:
    path "out/*"

    script:
    """
    mkdir -p out
    runquast "$assembly" "$PWD/out"
    """
}
'''
    },
    {
        "name": "GenomeScope2",
        "id": "GENOMESCOPE2",
        "type": "qc",
        "description": "Reference-free profiling",
        "process_template": '''
process GENOMESCOPE2 {
    publishDir "$params.outdir/GenomeScope2", mode: 'copy'

    input:
    path reads

    output:
    path "out/*"

    script:
    """
    mkdir -p out
    # Same rule as FASTQC: avoid quoting $reads if multiple files may be passed.
    rungenomescope2 $reads "$PWD/out"
    """
}
'''
    }
]


def get_tool_list():
    return [t["name"] for t in AVAILABLE_TOOLS]


def parse_input_args(arg_str: str):
    """
    Parses:
      "-fasta ref.fa -fastq fwd.fq -fastq rev.fq"
    into:
      {'fasta': 'ref.fa', 'fastq': ['fwd.fq', 'rev.fq']}
    """
    try:
        parts = shlex.split(arg_str)
    except ValueError:
        parts = arg_str.split()

    params = {}
    i = 0
    while i < len(parts):
        curr = parts[i]
        if curr.startswith("-"):
            key = curr.lstrip("-")
            if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                val = parts[i + 1]
                i += 2
            else:
                val = "true"
                i += 1

            if key in params:
                if not isinstance(params[key], list):
                    params[key] = [params[key]]
                params[key].append(val)
            else:
                params[key] = val
        else:
            i += 1

    return params


def generate_nextflow_script(selected_indices, input_arg_str):
    """
    Generate main.nf with:
      - smart channel creation
      - correct SPADES -> QUAST wiring (QUAST gets only assembly)
      - QC tools run on reads channel
      - fixes FASTQC quoting issue for paired reads
    """
    script = '''
nextflow.enable.dsl=2

params.outdir = "$baseDir/results"
'''

    user_params = parse_input_args(input_arg_str)
    if not user_params:
        user_params = {"input": "data/*_{1,2}.fastq"}

    # write params into the .nf
    for k, v in user_params.items():
        if isinstance(v, list):
            val_str = "[" + ", ".join([f"'{x}'" for x in v]) + "]"
            script += f"params.{k} = {val_str}\n"
        else:
            script += f"params.{k} = '{v}'\n"

    script += "\n"

    # add process defs
    active_tools = []
    try:
        for idx in selected_indices:
            tool = AVAILABLE_TOOLS[int(idx)]
            script += tool["process_template"] + "\n"
            active_tools.append(tool)
    except (IndexError, ValueError):
        return None, "Invalid tool index selected."

    # workflow
    script += "workflow {\n"

    # channel creation
    if "fastq" in user_params and isinstance(user_params["fastq"], list) and len(user_params["fastq"]) == 2:
        script += "    // Detected paired list in 'fastq'\n"
        script += "    reads_pair_ch = Channel.of( tuple(file(params.fastq[0]), file(params.fastq[1])) )\n"
        script += "    reads_ch = reads_pair_ch\n"
        script += "    data_ch  = reads_pair_ch\n"

    elif "r1" in user_params and "r2" in user_params:
        script += "    // Detected r1/r2 keys\n"
        script += "    reads_pair_ch = Channel.of( tuple(file(params.r1), file(params.r2)) )\n"
        script += "    reads_ch = reads_pair_ch\n"
        script += "    data_ch  = reads_pair_ch\n"

    elif "input" in user_params:
        script += "    // Detected 'input' glob pattern\n"
        script += "    reads_ch = Channel.fromFilePairs(params.input, flat: true)\n"
        script += "    data_ch  = reads_ch\n"

    elif "fasta" in user_params:
        script += "    // Detected single 'fasta'\n"
        script += "    reads_ch = Channel.fromPath(params.fasta)\n"
        script += "    data_ch  = reads_ch\n"

    else:
        first_key = list(user_params.keys())[0]
        script += f"    // Fallback: using params.{first_key}\n"
        script += f"    reads_ch = Channel.fromPath(params.{first_key})\n"
        script += f"    data_ch  = reads_ch\n"

    script += "\n"
    script += "    // --- Pipeline wiring ---\n"
    script += "    def assembly_ch_defined = false\n\n"

    for tool in active_tools:
        pid = tool["id"]

        if pid == "SPADES":
            script += "    spades_res = SPADES(data_ch)\n"
            script += "    assembly_ch = spades_res.assembly\n"
            script += "    assembly_ch_defined = true\n\n"

        elif pid == "QUAST":
            script += "    if( !assembly_ch_defined ) error 'QUAST requires an assembly. Select SPADES before QUAST.'\n"
            script += "    QUAST(assembly_ch)\n\n"

        else:
            if tool["type"] == "qc":
                script += f"    {pid}(reads_ch)\n\n"
            elif tool["type"] == "transform":
                script += f"    data_ch = {pid}(data_ch)\n\n"

    script += "}\n"
    return script, None


def setup_nextflow(container):
    """Ensure Nextflow is installed in the tenant container."""
    check = container.exec_run("which nextflow")
    if check.exit_code != 0:
        print(f"[*] Installing Nextflow in {container.name}...")
        cmd = "curl -s https://get.nextflow.io | bash && mv nextflow /usr/local/bin/ && chmod +x /usr/local/bin/nextflow"
        container.exec_run(f"/bin/bash -c '{cmd}'", user="root")


def run_pipeline(tenant_container, input_args: str, tool_indices):
    """
    Orchestrate pipeline execution in the tenant container.
    """
    setup_nextflow(tenant_container)

    nf_script, error = generate_nextflow_script(tool_indices, input_args)
    if error:
        return error

    work_dir = f"/home/{tenant_container.name}/pipeline_run_{int(time.time())}"
    script_path = f"{work_dir}/main.nf"

    # create work dir
    res = tenant_container.exec_run(
        ["/bin/bash", "-lc", f"mkdir -p {work_dir}"],
        user="root"
    )
    if res.exit_code != 0:
        return (
            "Pipeline failed: could not create work_dir\n"
            + getattr(res, "output", b"").decode(errors="replace")
        )

    # write main.nf
    write_cmd = f"cat <<'__NF_EOF__' > {script_path}\n{nf_script}\n__NF_EOF__"
    res = tenant_container.exec_run(
        ["/bin/bash", "-lc", write_cmd],
        user="root"
    )
    if res.exit_code != 0:
        out = getattr(res, "output", b"").decode(errors="replace")
        return f"Pipeline failed: main.nf was not created\n{out}"

    # run nextflow
    print(f"[*] Starting Nextflow pipeline in {tenant_container.name}...")
    cmd = f"cd {work_dir} && nextflow run main.nf"
    res = tenant_container.exec_run(
        ["/bin/bash", "-lc", cmd],
        user="root"
    )

    output_log = getattr(res, "output", b"").decode(errors="replace")

    if res.exit_code == 0:
        return (
            "Pipeline completed successfully.\n"
            f"Results saved to: {work_dir}/results\n\n"
            f"Logs:\n{output_log}"
        )

    return f"Pipeline failed.\n\nLogs:\n{output_log}"

# -fasta uploads/ege_1765832522_ecoli.fasta -fastq uploads/ege_1765832546_ecoli_f.fastq -fastq uploads/ege_1765832574_ecoli_r.fastq

# -------------------------------------------------------------
# Optional: tiny helper for local testing (won't run unless you call it)
# -------------------------------------------------------------
if __name__ == "__main__":
    # Example usage (edit to match your environment):
    # client = docker.from_env()
    # tenant = client.containers.get("tenant_tt1_1")
    # print(run_pipeline(tenant, "-fastq reads_1.fq -fastq reads_2.fq", ["1", "2"]))  # SPADES + QUAST
    pass
