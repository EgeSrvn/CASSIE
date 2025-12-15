import docker
import os
import time
import shlex

# -------------------------------------------------------------------
# 🔹 Tool Definitions (Unchanged)
# -------------------------------------------------------------------
AVAILABLE_TOOLS = [
    {
        "name": "FastQC",
        "id": "FASTQC",
        "type": "qc",
        "description": "Quality control for raw sequence data",
        "process_template": """
process FASTQC {
    publishDir "$params.outdir/FastQC", mode: 'copy'

    input:
    path reads

    output:
    path "out/*"

    script:
    \"\"\"
    mkdir -p out
    # If reads is a list/tuple (paired), this expands to "file1 file2"
    runfastqc "$reads" "/data"
    \"\"\"
}
"""
    },
    {
        "name": "SPAdes",
        "id": "SPADES",
        "type": "transform",
        "description": "Genome assembler",
        "process_template": """
process SPADES {
    publishDir "$params.outdir/SPAdes", mode: 'copy'

    input:
    # SPAdes expects a tuple of two files for paired mode
    tuple path(r1), path(r2)

    output:
    path "out/contigs.fasta", emit: assembly
    path "out/*"

    script:
    \"\"\"
    mkdir -p out
    runspades "$r1" "$r2" "/data"
    \"\"\"
}
"""
    },
    {
        "name": "QUAST",
        "id": "QUAST",
        "type": "qc",
        "description": "Assembly quality assessment",
        "process_template": """
process QUAST {
    publishDir "$params.outdir/QUAST", mode: 'copy'

    input:
    path assembly

    output:
    path "out/*"

    script:
    \"\"\"
    mkdir -p out
    runquast "$assembly" "/data"
    \"\"\"
}
"""
    },
    {
        "name": "GenomeScope2",
        "id": "GENOMESCOPE2",
        "type": "qc",
        "description": "Reference-free profiling",
        "process_template": """
process GENOMESCOPE2 {
    publishDir "$params.outdir/GenomeScope2", mode: 'copy'

    input:
    path reads

    output:
    path "out/*"

    script:
    \"\"\"
    mkdir -p out
    rungenomescope2 "$reads" "/data"
    \"\"\"
}
"""
    }
]

def get_tool_list():
    return [t["name"] for t in AVAILABLE_TOOLS]

def parse_input_args(arg_str):
    """
    Parses a string like "-fasta ref.fa -fastq fwd.fq -fastq rev.fq"
    into a dictionary: {'fasta': 'ref.fa', 'fastq': ['fwd.fq', 'rev.fq']}
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
            if i + 1 < len(parts) and not parts[i+1].startswith("-"):
                val = parts[i+1]
                i += 2
            else:
                val = "true" # Flag without value
                i += 1
            
            # Handle duplicate keys (append to list)
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
    Generate main.nf with dynamic params and flexible channel creation.
    """
    
    # 1. Header
    script = """
nextflow.enable.dsl=2

params.outdir = "$baseDir/results"
"""

    # 2. Parse User Arguments & Populate Params
    user_params = parse_input_args(input_arg_str)
    
    # If no args provided, default for safety
    if not user_params:
        user_params = {"input": "data/*_{1,2}.fastq"}

    # Write params to script
    for k, v in user_params.items():
        if isinstance(v, list):
            # Create a groovy list string: ["a", "b"]
            val_str = "[" + ", ".join([f"'{x}'" for x in v]) + "]"
            script += f"params.{k} = {val_str}\n"
        else:
            script += f"params.{k} = '{v}'\n"

    script += "\n"

    # 3. Add Process Definitions
    active_tools = []
    try:
        for idx in selected_indices:
            tool = AVAILABLE_TOOLS[int(idx)]
            script += tool["process_template"] + "\n"
            active_tools.append(tool)
    except IndexError:
        return None, "Invalid tool index selected."

    # 4. Build Workflow Logic
    script += "workflow {\n"

    # --- SMART CHANNEL SELECTION ---
    # Heuristic: 
    # 1. If 'fastq' is a list of 2 items (e.g. -fastq fwd -fastq rev), make a tuple.
    # 2. If 'r1' and 'r2' exist, make a tuple.
    # 3. If 'input' exists (glob pattern), use fromFilePairs.
    # 4. Else, take the first param available and make a Path channel.

    if "fastq" in user_params and isinstance(user_params["fastq"], list) and len(user_params["fastq"]) == 2:
        # Explicit paired list
        script += "    // Detected paired list in 'fastq'\n"
        script += "    data_ch = Channel.of( tuple(file(params.fastq[0]), file(params.fastq[1])) )\n"
        
    elif "r1" in user_params and "r2" in user_params:
        # Explicit r1/r2 flags
        script += "    // Detected r1/r2 keys\n"
        script += "    data_ch = Channel.of( tuple(file(params.r1), file(params.r2)) )\n"

    elif "input" in user_params:
        # Standard Nextflow glob (legacy support)
        script += "    // Detected 'input' glob pattern\n"
        script += "    data_ch = Channel.fromFilePairs(params.input, flat: true)\n"

    elif "fasta" in user_params:
        # Single fasta input
        script += "    // Detected single 'fasta'\n"
        script += "    data_ch = Channel.fromPath(params.fasta)\n"
    
    else:
        # Fallback: just grab the first key found and try to use it
        first_key = list(user_params.keys())[0]
        script += f"    // Fallback: using params.{first_key}\n"
        script += f"    data_ch = Channel.fromPath(params.{first_key})\n"

    script += "\n"

    # 5. Chain Processes
    for tool in active_tools:
        process_name = tool["id"]
        if tool["type"] == "qc":
            script += f"    {process_name}(data_ch)\n"
        elif tool["type"] == "transform":
            script += f"    data_ch = {process_name}(data_ch)\n"

    script += "}\n"
    
    return script, None

# ... (rest of setup_nextflow and run_pipeline remains the same) ...
def setup_nextflow(container):
    """Ensure Nextflow is installed in the tenant container."""
    check = container.exec_run("which nextflow")
    if check.exit_code != 0:
        print(f"[*] Installing Nextflow in {container.name}...")
        cmd = "curl -s https://get.nextflow.io | bash && mv nextflow /usr/local/bin/ && chmod +x /usr/local/bin/nextflow"
        container.exec_run(f"/bin/bash -c '{cmd}'", user="root")

def run_pipeline(tenant_container, input_args, tool_indices):
    """
    Orchestrate the pipeline execution.
    input_args is now the raw string of arguments (e.g. "-r1 x -r2 y").
    """

    # 1) Setup
    setup_nextflow(tenant_container)

    # 2) Generate Script
    nf_script, error = generate_nextflow_script(tool_indices, input_args)
    if error:
        return error

    # 3) Work dir + script path
    work_dir = f"/home/{tenant_container.name}/pipeline_run_{int(time.time())}"
    script_path = f"{work_dir}/main.nf"

    # Make sure work dir exists
    res = tenant_container.exec_run(
        ["/bin/bash", "-lc", f"mkdir -p {work_dir}"],
        user="root"
    )
    if res.exit_code != 0:
        return f"Pipeline failed: could not create work_dir\n{getattr(res, 'output', b'').decode(errors='replace')}"

    # Write script safely
    write_cmd = f"cat <<'__NF_EOF__' > {script_path}\n{nf_script}\n__NF_EOF__"
    res = tenant_container.exec_run(
        ["/bin/bash", "-lc", write_cmd],
        user="root"
    )
    
    if res.exit_code != 0:
        out = getattr(res, "output", b"").decode(errors="replace")
        return f"Pipeline failed: main.nf was not created\n{out}"

    # 4) Execute Nextflow
    print(f"[*] Starting Nextflow pipeline in {tenant_container.name}...")
    
    # We run inside the work_dir so 'results' appear there
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
    else:
        return f"Pipeline failed.\n\nLogs:\n{output_log}"