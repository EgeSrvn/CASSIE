import time
import shlex
from tool_registry import get_tool_registry

AVAILABLE_TOOLS = get_tool_registry()


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
        script += "    reads_pair_ch = Channel.fromFilePairs(params.input, flat: true)\n"
        script += "    reads_ch = reads_pair_ch\n"
        script += "    data_ch  = reads_pair_ch\n"
    elif "fasta" in user_params:
        script += "    // Detected single 'fasta'\n"
        script += "    reads_ch = Channel.fromPath(params.fasta)\n"
        script += "    data_ch  = reads_ch\n"
    else:
        first_key = list(user_params.keys())[0]
        script += f"    reads_ch = Channel.fromPath(params.{first_key})\n"
        script += f"    data_ch  = reads_ch\n"
        script += "    reads_pair_ch = reads_ch\n"


    script += "\n"
    script += "    data_ch = reads_ch\n"
    script += "    qc_reads_ch = reads_ch.flatten()\n\n"
    script += "    def assembly_ch_defined = false\n\n"


    for tool in active_tools:
        pid = tool["id"]

        if pid == "SPADES":
            script += "    spades_res = SPADES(data_ch)\n"
            script += "    assembly_ch = spades_res.assembly\n"
            script += "    data_ch = spades_res.files\n"
            script += "    assembly_ch_defined = true\n\n"

        elif pid == "QUAST":
            script += "    if( !assembly_ch_defined ) error 'QUAST requires an assembly. Select SPADES before QUAST.'\n"
            script += "    if( !params.fasta ) error 'QUAST requires -fasta reference.'\n"
            script += "    quast_in_ch = assembly_ch.combine(ref_ch)\n"
            script += "    QUAST(quast_in_ch)\n\n"

        elif pid == "GENOMESCOPE2":
            # Run once per read pair (not per mate)
            script += "    GENOMESCOPE2(reads_pair_ch)\n\n"

        else:
            if tool["type"] == "qc":
                script += f"    {pid}(qc_reads_ch)\n\n"
            elif tool["type"] == "transform":
                script += f"    data_ch = {pid}(data_ch)\n\n"


    script += "}\n"
    return script, None


def setup_nextflow(container):
    # Ensure container is running before executing commands
    container.reload()
    if container.status != "running":
        container.start()
        time.sleep(2)  # Wait for container to be fully up
    
    check = container.exec_run("which nextflow")
    if check.exit_code != 0:
        cmd = "curl -s https://get.nextflow.io | bash && mv nextflow /usr/local/bin/ && chmod +x /usr/local/bin/nextflow"
        container.exec_run(f"/bin/bash -c '{cmd}'", user="root")


def run_pipeline(tenant_container, input_args: str, tool_indices):
    # Ensure container is running before executing commands
    tenant_container.reload()
    if tenant_container.status != "running":
        tenant_container.start()
        time.sleep(2)  # Wait for container to be fully up
    
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

    # Pipeline failed - try to extract detailed error logs from Nextflow work directory
    error_details = output_log
    error_details += f"\n\n=== Work Directory: {work_dir} ===\n"
    error_details += f"To manually check logs, run: docker exec {tenant_container.name} find {work_dir}/work -name '.command.*'\n\n"
    
    try:
        # List all work subdirectories first
        list_work_cmd = f"ls -la {work_dir}/work 2>/dev/null | head -20"
        list_res = tenant_container.exec_run(["/bin/bash", "-lc", list_work_cmd], user="root")
        if list_res.exit_code == 0 and list_res.output:
            error_details += "=== Work Directory Contents ===\n"
            error_details += list_res.output.decode(errors="replace")
            error_details += "\n"
        
        # Find failed process work directories (Nextflow stores logs in work/*/ directories)
        # Try to find any work subdirectory
        find_work_cmd = f"find {work_dir}/work -type d -maxdepth 1 2>/dev/null | head -5"
        work_res = tenant_container.exec_run(["/bin/bash", "-lc", find_work_cmd], user="root")
        
        if work_res.exit_code == 0 and work_res.output:
            work_dirs = [d.strip() for d in work_res.output.decode(errors="replace").split('\n') if d.strip() and d.strip() != f"{work_dir}/work"]
            
            for work_subdir in work_dirs[:3]:  # Check first 3 work directories
                if work_subdir:
                    error_details += f"\n=== Checking {work_subdir} ===\n"
                    # Look for .command.err and .command.log in this directory
                    for log_name in ['.command.err', '.command.log', '.command.out', '.command.sh']:
                        log_path = f"{work_subdir}/{log_name}"
                        cat_cmd = f"test -f {log_path} && cat {log_path} 2>/dev/null || echo 'File not found'"
                        cat_res = tenant_container.exec_run(["/bin/bash", "-lc", cat_cmd], user="root")
                        if cat_res.exit_code == 0 and cat_res.output:
                            log_content = cat_res.output.decode(errors="replace")
                            if log_content.strip() and "File not found" not in log_content:
                                error_details += f"\n--- {log_name} ---\n"
                                # Limit to last 100 lines to avoid huge output
                                if log_content.count('\n') > 100:
                                    log_content = '\n'.join(log_content.split('\n')[-100:])
                                    error_details += "... (showing last 100 lines) ...\n"
                                error_details += log_content
                                error_details += "\n"
        
        # Fallback: try to find any .command.err files recursively
        if "=== .command.err" not in error_details and ".command.err" not in error_details:
            find_err_cmd = f"find {work_dir}/work -name '.command.err' 2>/dev/null | head -3"
            find_res = tenant_container.exec_run(["/bin/bash", "-lc", find_err_cmd], user="root")
            if find_res.exit_code == 0 and find_res.output:
                err_files = [f.strip() for f in find_res.output.decode(errors="replace").split('\n') if f.strip()]
                for err_file in err_files:
                    cat_res = tenant_container.exec_run(["/bin/bash", "-lc", f"cat {err_file} 2>/dev/null"], user="root")
                    if cat_res.exit_code == 0 and cat_res.output:
                        err_content = cat_res.output.decode(errors="replace")
                        if err_content.strip():
                            error_details += f"\n\n=== Error from {err_file} ===\n"
                            if err_content.count('\n') > 100:
                                err_content = '\n'.join(err_content.split('\n')[-100:])
                                error_details += "... (showing last 100 lines) ...\n"
                            error_details += err_content
                            error_details += "\n"
    except Exception as e:
        error_details += f"\n\n(Note: Could not extract detailed logs: {e})\n"
        import traceback
        error_details += traceback.format_exc()

    return f"Pipeline failed.\n\nLogs:\n{error_details}"


if __name__ == "__main__":
    pass
