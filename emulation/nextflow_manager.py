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
'''
    },
    {
        "name": "SPAdes",
        "id": "SPADES",
        "type": "transform",
        "description": "Genome assembler",
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
'''
    },
    {
        "name": "QUAST",
        "id": "QUAST",
        "type": "qc",
        "description": "Assembly quality assessment",
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

    rm -rf "/data/quast_in/${workflow.runName}-${task.index}"
    mkdir -p "/data/quast_in/${workflow.runName}-${task.index}"

    cp "$assembly" "/data/quast_in/${workflow.runName}-${task.index}/contigs.fasta"
    cp "$ref"      "/data/quast_in/${workflow.runName}-${task.index}/reference.fasta"

    rm -rf "/data/quast_out/${workflow.runName}-${task.index}"
    mkdir -p "/data/quast_out/${workflow.runName}-${task.index}"

    # Requires runquast.sh to use --volumes-from "$HOSTNAME"
    runquast "quast_in/${workflow.runName}-${task.index}/contigs.fasta" \
             "quast_in/${workflow.runName}-${task.index}/reference.fasta" \
             "/data/quast_out/${workflow.runName}-${task.index}"

    cp -a "/data/quast_out/${workflow.runName}-${task.index}"/. out/
    ls -la out
    """
}
'''
    },
    {
        "name": "GenomeScope2",
        "id": "GENOMESCOPE2",
        "type": "qc",
        "description": "Reference-free profiling",
        "process_template": r'''
process GENOMESCOPE2 {
    publishDir "${params.outdir}/GenomeScope2", mode: 'copy'

    input:
    path read

    output:
    path "out/*"

    script:
    """
    set -euo pipefail
    mkdir -p out

    rm -rf "/data/genomescope2_out/${workflow.runName}-${task.index}"
    mkdir -p "/data/genomescope2_out/${workflow.runName}-${task.index}"

    rungenomescope2 "$read" "/data/genomescope2_out/${workflow.runName}-${task.index}"

    cp -a "/data/genomescope2_out/${workflow.runName}-${task.index}"/. out/
    """
}
'''
    }
]


def get_tool_list():
    return [t["name"] for t in AVAILABLE_TOOLS]


def _nf_quote(v: str) -> str:
    return f"'{v}'"


def _to_datadir_path(p: str) -> str:
    p = str(p)
    if p.startswith("/"):
        return p
    if p.startswith("data/"):
        p = p[len("data/"):]
    return "/data/" + p


def parse_input_args(arg_str: str):
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
    script = r'''
nextflow.enable.dsl=2

params.datadir = "/data"
params.outdir = "${baseDir}/results"
'''

    user_params = parse_input_args(input_arg_str)
    if not user_params:
        user_params = {"input": "/data/*_{1,2}.fastq"}

    file_keys = ("fastq", "r1", "r2", "input", "fasta")

    for k, v in user_params.items():
        if isinstance(v, list):
            mapped = []
            for x in v:
                if k in file_keys:
                    x = _to_datadir_path(x)
                mapped.append(_nf_quote(x))
            script += f"params.{k} = [{', '.join(mapped)}]\n"
        else:
            val = v
            if k in file_keys:
                val = _to_datadir_path(val)
            script += f"params.{k} = {_nf_quote(val)}\n"

    script += "\n"

    active_tools = []
    try:
        for idx in selected_indices:
            tool = AVAILABLE_TOOLS[int(idx)]
            script += tool["process_template"] + "\n"
            active_tools.append(tool)
    except (IndexError, ValueError):
        return None, "Invalid tool index selected."

    script += "workflow {\n"

    # Create ref channel whenever fasta is provided
    if "fasta" in user_params:
        script += "    ref_ch = Channel.fromPath(params.fasta)\n"

    # Create reads/data channels
    if "fastq" in user_params and isinstance(user_params["fastq"], list) and len(user_params["fastq"]) == 2:
        script += "    reads_pair_ch = Channel.of( tuple(file(params.fastq[0]), file(params.fastq[1])) )\n"
        script += "    reads_ch = reads_pair_ch\n"
        script += "    data_ch  = reads_pair_ch\n"
    elif "r1" in user_params and "r2" in user_params:
        script += "    reads_pair_ch = Channel.of( tuple(file(params.r1), file(params.r2)) )\n"
        script += "    reads_ch = reads_pair_ch\n"
        script += "    data_ch  = reads_pair_ch\n"
    elif "input" in user_params:
        script += "    reads_ch = Channel.fromFilePairs(params.input, flat: true)\n"
        script += "    data_ch  = reads_ch\n"
    else:
        first_key = list(user_params.keys())[0]
        script += f"    reads_ch = Channel.fromPath(params.{first_key})\n"
        script += f"    data_ch  = reads_ch\n"

    script += "\n"
    script += "    data_ch = reads_ch\n"
    script += "    qc_reads_ch = reads_ch.flatten()\n\n"
    script += "    def assembly_ch_defined = false\n\n"


    for tool in active_tools:
        pid = tool["id"]

        if pid == "SPADES":
            script += "    spades_res = SPADES(data_ch)\n"
            script += "    assembly_ch = spades_res.assembly\n"
            script += "    data_ch = spades_res.files\n"   # IMPORTANT: keep pipeline as a channel
            script += "    assembly_ch_defined = true\n\n"


        elif pid == "QUAST":
            script += "    if( !assembly_ch_defined ) error 'QUAST requires an assembly. Select SPADES before QUAST.'\n"
            script += "    if( !params.fasta ) error 'QUAST requires -fasta reference.'\n"
            script += "    quast_in_ch = assembly_ch.combine(ref_ch)\n"
            script += "    QUAST(quast_in_ch)\n\n"

        else:
            if tool["type"] == "qc":
                script += f"    {pid}(qc_reads_ch)\n\n"
            elif tool["type"] == "transform":
                script += f"    data_ch = {pid}(data_ch)\n\n"

    script += "}\n"
    return script, None


def setup_nextflow(container):
    check = container.exec_run("which nextflow")
    if check.exit_code != 0:
        cmd = "curl -s https://get.nextflow.io | bash && mv nextflow /usr/local/bin/ && chmod +x /usr/local/bin/nextflow"
        container.exec_run(f"/bin/bash -c '{cmd}'", user="root")


def run_pipeline(tenant_container, input_args: str, tool_indices):
    setup_nextflow(tenant_container)

    nf_script, error = generate_nextflow_script(tool_indices, input_args)
    if error:
        return error

    work_dir = f"/home/{tenant_container.name}/pipeline_run_{int(time.time())}"
    script_path = f"{work_dir}/main.nf"

    res = tenant_container.exec_run(["/bin/bash", "-lc", f"mkdir -p {work_dir}"], user="root")
    if res.exit_code != 0:
        return "Pipeline failed: could not create work_dir\n" + getattr(res, "output", b"").decode(errors="replace")

    write_cmd = f"cat <<'__NF_EOF__' > {script_path}\n{nf_script}\n__NF_EOF__"
    res = tenant_container.exec_run(["/bin/bash", "-lc", write_cmd], user="root")
    if res.exit_code != 0:
        out = getattr(res, "output", b"").decode(errors="replace")
        return f"Pipeline failed: main.nf was not created\n{out}"

    cmd = f"cd {work_dir} && nextflow run main.nf"
    res = tenant_container.exec_run(["/bin/bash", "-lc", cmd], user="root")

    output_log = getattr(res, "output", b"").decode(errors="replace")
    if res.exit_code == 0:
        return (
            "Pipeline completed successfully.\n"
            f"Results saved to: {work_dir}/results\n\n"
            f"Logs:\n{output_log}"
        )

    return f"Pipeline failed.\n\nLogs:\n{output_log}"


if __name__ == "__main__":
    pass
