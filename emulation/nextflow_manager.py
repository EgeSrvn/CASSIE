import docker
import os
import time

# -------------------------------------------------------------------
# 🔹 Tool Definitions
# -------------------------------------------------------------------
# type: "qc" (does not modify input flow) or "transform" (modifies input flow)
AVAILABLE_TOOLS = [
    {
        "name": "FastQC",
        "id": "FASTQC",
        "type": "qc",
        "description": "Quality control for raw sequence data",
        "process_template": """
process FASTQC {
    publishDir "$params.outdir/FastQC", [mode: 'copy']

    input:
    path reads

    output:
    path "out/*"

    script:
    \"\"\"
    mkdir -p out
    runfastqc "$reads" "/data"
    \"\"\"
}
"""
    },
    {
        "name": "GenomeScope2",
        "id": "GENOMESCOPE2",
        "type": "qc", 
        "description": "Reference-free profiling of polyploid genomes",
        "process_template": """
process GENOMESCOPE2 {
    publishDir "$params.outdir/GenomeScope2", [mode: 'copy']

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
    },
    {
        "name": "SPAdes",
        "id": "SPADES",
        "type": "transform",
        "description": "Genome assembler",
        "process_template": """
process SPADES {
    publishDir "$params.outdir/SPAdes", [mode: 'copy']

    input:
    path reads

    output:
    path "out/*"

    script:
    \"\"\"
    mkdir -p out
    runspades "$reads" "/data"
    \"\"\"
}
"""
    }
]


def get_tool_list():
    """Return a list of tool names for display."""
    return [t["name"] for t in AVAILABLE_TOOLS]

def generate_nextflow_script(selected_indices, input_filename):
    """
    Generate the content of a Nextflow main.nf script.
    
    Logic:
    1. Start with the input channel.
    2. Iterate through selected tools.
    3. If QC: Run process on current channel, do NOT update current channel.
    4. If Transform: Run process, UPDATE current channel to use output of this process.
    """
    
    # 1. Header and Parameters
    script = """
nextflow.enable.dsl=2

params.input = "{}"
params.outdir = "$baseDir/results"

""".format(input_filename)

    # 2. Add Process Definitions
    active_tools = []
    try:
        for idx in selected_indices:
            tool = AVAILABLE_TOOLS[int(idx)]
            script += tool["process_template"] + "\n"
            active_tools.append(tool)
    except IndexError:
        return None, "Invalid tool index selected."

    # 3. Build Workflow Logic
    script += "workflow {\n"
    script += "    data_ch = Channel.fromPath(params.input)\n\n"

    for tool in active_tools:
        process_name = tool["id"]
        if tool["type"] == "qc":
            # Fork: Use data_ch but don't reassign it
            script += f"    {process_name}(data_ch)\n"
        elif tool["type"] == "transform":
            # Chain: Update data_ch with the output
            script += f"    data_ch = {process_name}(data_ch)\n"

    script += "}\n"
    
    return script, None

def setup_nextflow(container):
    """Ensure Nextflow is installed in the tenant container."""
    # Check if nextflow exists
    check = container.exec_run("which nextflow")
    if check.exit_code != 0:
        print(f"[*] Installing Nextflow in {container.name}...")
        # Needs curl and java (java assumed present per Dockerfile)
        cmd = "curl -s https://get.nextflow.io | bash && mv nextflow /usr/local/bin/ && chmod +x /usr/local/bin/nextflow"
        container.exec_run(f"/bin/bash -c '{cmd}'", user="root")

def run_pipeline(tenant_container, input_path, tool_indices):
    """
    Orchestrate the pipeline execution in the tenant.

    1. Ensure Nextflow is present.
    2. Generate main.nf.
    3. Write main.nf safely to tenant.
    4. Run Nextflow using the absolute script path.
    """

    # 1) Setup
    setup_nextflow(tenant_container)

    # 2) Generate Script
    nf_script, error = generate_nextflow_script(tool_indices, input_path)
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

    # ✅ SAFE write (no shell expansion, no quote-breaking)
    write_cmd = f"cat <<'__NF_EOF__' > {script_path}\n{nf_script}\n__NF_EOF__"
    res = tenant_container.exec_run(
        ["/bin/bash", "-lc", write_cmd],
        user="root"
    )
    out = getattr(res, "output", b"").decode(errors="replace")
    if res.exit_code != 0:
        return f"Pipeline failed: could not write main.nf\n{out}"

    # Hard-check that main.nf exists and is non-empty
    res = tenant_container.exec_run(
        ["/bin/bash", "-lc", f"test -s {script_path} && head -n 20 {script_path}"],
        user="root"
    )
    if res.exit_code != 0:
        out = getattr(res, "output", b"").decode(errors="replace")
        return f"Pipeline failed: main.nf was not created (or empty)\n{out}"

    # 4) Execute Nextflow (use absolute path so cwd doesn't matter)
    print(f"[*] Starting Nextflow pipeline in {tenant_container.name}...")
    cmd = f"nextflow run {script_path}"
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
    """
    Orchestrate the pipeline execution in the tenant.
    
    1. Ensure Nextflow is present.
    2. Generate main.nf.
    3. Write main.nf to tenant.
    4. Run Nextflow.
    """

    # 1. Setup
    setup_nextflow(tenant_container)
    
    # 2. Generate Script
    # input_path is likely /home/tenant_.../uploads/...
    nf_script, error = generate_nextflow_script(tool_indices, input_path)
    if error:
        return error

    # 3. Write Script to Container
    # We use a temp file in the container
    work_dir = f"/home/{tenant_container.name}/pipeline_run_{int(time.time())}"
    tenant_container.exec_run(f"mkdir -p {work_dir}", user="root")
    
    # Create the file locally inside the container using echo/cat hack
    # (Escaping quotes for bash is tricky, simplified here)
    script_path = f"{work_dir}/main.nf"
    
    # Using a helper to write content safely
    write_cmd = f"cat <<'EOF' > {script_path}\n{nf_script}\nEOF"
    tenant_container.exec_run(write_cmd, user="root")
    
    # 4. Execute
    print(f"[*] Starting Nextflow pipeline in {tenant_container.name}...")
    cmd = f"cd {work_dir} && nextflow run main.nf"
    
    # We run detached or wait? For this emulation, we wait (blocking).
    res = tenant_container.exec_run(f"/bin/bash -c '{cmd}'", user="root")
    
    output_log = res.output.decode(errors="replace")
    
    if res.exit_code == 0:
        return f"Pipeline completed successfully.\nResults saved to: {work_dir}/results\n\nLogs:\n{output_log}"
    else:
        return f"Pipeline failed.\n\nLogs:\n{output_log}"