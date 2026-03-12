import os
import subprocess
from pathlib import Path
from test1 import ensure_local_registry, tag_and_push_to_registry


def _run(cmd, cwd=None):
    print("[cmd]", " ".join(cmd))
    return subprocess.run(cmd, check=True, cwd=cwd)


def push_images(spec, registry_host="localhost", registry_port=5000, registry_container_name="local-registry"):
    registry = ensure_local_registry(
        registry_host=registry_host,
        registry_port=registry_port,
        container_name=registry_container_name,
    )

    pushed = {}
    for tool_name, tool in spec["tools"].items():
        local_image = tool["image"]
        remote_repo = tool["remote_repo"]
        remote_tag = tool.get("tag")

        pushed_image = tag_and_push_to_registry(
            local_image=local_image,
            registry=registry,
            remote_repo=remote_repo,
            remote_tag=remote_tag,
        )
        pushed[tool_name] = pushed_image

    return registry, pushed


def _nf_escape_script(s: str) -> str:
    # keep scripts readable in Nextflow triple-quoted strings
    return s.strip("\n")


def generate_nextflow_files(spec, pushed_images, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Map logical input names -> Nextflow variable names
    input_names = list(spec["inputs"].keys())

    # Build connection map: tool.input <- tool.output
    # e.g. quast.contigs_fasta <- spades.contigs_fasta
    conn_to = {}  # key: (tool, input) -> value: (tool, output)
    for edge in spec.get("connections", []):
        f_tool, f_out = edge["from"].split(".", 1)
        t_tool, t_in  = edge["to"].split(".", 1)
        conn_to[(t_tool, t_in)] = (f_tool, f_out)

    # For each tool, determine which of its declared inputs come from:
    # - pipeline inputs
    # - previous tool outputs
    tools_order = list(spec["tools"].keys())  # keep user order (simple; you can topological-sort later)

    # Create channels for pipeline inputs
    main_lines = []
    main_lines.append("nextflow.enable.dsl=2")
    main_lines.append("")
    main_lines.append("workflow {")
    main_lines.append("  // pipeline inputs")
    for name in input_names:
        main_lines.append(f"  ch_{name} = Channel.fromPath(params.{name})")
    main_lines.append("")

    # Keep track of channels produced by tools: ch_tool_outputname
    produced = {}

    # Emit each tool call
    for tool_name in tools_order:
        tool = spec["tools"][tool_name]
        # Build input channel list in the tool’s declared order
        arg_chs = []
        for inp in tool.get("in", []):
            # Is this input connected from a previous tool output?
            if (tool_name, inp) in conn_to:
                f_tool, f_out = conn_to[(tool_name, inp)]
                arg_chs.append(f"ch_{f_tool}_{f_out}")
            else:
                # else assume pipeline input
                arg_chs.append(f"ch_{inp}")

        call = f"  {tool_name}_res = {tool_name}({', '.join(arg_chs)})"
        main_lines.append(call)

        # Capture emitted outputs as channels
        for out_name in tool.get("out", []):
            produced[(tool_name, out_name)] = f"{tool_name}_res.{out_name}"
            main_lines.append(f"  ch_{tool_name}_{out_name} = {tool_name}_res.{out_name}")

        main_lines.append("")

    # “final outputs” publish hint (just prints paths; actual publish done in process publishDir)
    final_outs = spec.get("final_outputs", [])
    if final_outs:
        main_lines.append("  // final outputs (print paths)")
        for ref in final_outs:
            t, o = ref.split(".", 1)
            main_lines.append(f"  ch_{t}_{o}.view {{ it }}")
        main_lines.append("")

    main_lines.append("}")
    main_lines.append("")

    # Define processes
    proc_lines = []
    for tool_name in tools_order:
        tool = spec["tools"][tool_name]
        image = pushed_images[tool_name]
        publish_subdir = spec.get("publish_subdir", "results")

        # Inputs in declared order as paths
        proc_lines.append(f"process {tool_name} {{")
        proc_lines.append(f"  container '{image}'")
        proc_lines.append("  errorStrategy 'terminate'")
        proc_lines.append(f"  publishDir \"{publish_subdir}/{tool_name}\", mode: 'copy'")
        proc_lines.append("")
        proc_lines.append("  input:")
        for inp in tool.get("in", []):
            proc_lines.append(f"    path {inp}")
        proc_lines.append("")
        proc_lines.append("  output:")
        # Use "emit:" blocks so workflow can reference results.<name>
        for emit_name, emit_glob in tool.get("emit", {}).items():
            proc_lines.append(f"    path '{emit_glob}', emit: {emit_name}")
        proc_lines.append("")
        proc_lines.append("  script:")
        proc_lines.append('  """')
        proc_lines.append(_nf_escape_script(tool["script"]))
        proc_lines.append('  """')
        proc_lines.append("}")
        proc_lines.append("")

    main_nf = "\n".join(main_lines + proc_lines)
    (out_dir / "main.nf").write_text(main_nf, encoding="utf-8")

    # Nextflow config for Kubernetes execution
    # Note: serviceAccount / namespace optional, tune to your cluster
    nextflow_cfg = f"""
profiles {{
  k8s {{
    process.executor = 'k8s'
    k8s.namespace = 'default'
    // If your registry is insecure, Kubernetes must be configured to allow it.
    // (Docker Desktop: Settings -> Docker Engine -> insecure-registries)
  }}
}}
"""
    (out_dir / "nextflow.config").write_text(nextflow_cfg.strip() + "\n", encoding="utf-8")


def run_nextflow(pipeline_dir: Path, params: dict, profile="k8s"):
    cmd = ["nextflow", "run", "main.nf", "-profile", profile]
    for k, v in params.items():
        cmd += ["--" + k, str(v)]
    _run(cmd, cwd=str(pipeline_dir))


def build_and_run(spec, pipeline_dir, params):
    pipeline_dir = Path(pipeline_dir)

    registry, pushed_images = push_images(spec)
    print("[registry]", registry)
    for k, v in pushed_images.items():
        print(f"[image] {k} -> {v}")

    generate_nextflow_files(spec, pushed_images, pipeline_dir)
    run_nextflow(pipeline_dir, params, profile="k8s")


if __name__ == "__main__":
    from tool_specs import PIPELINE_SPEC 

    # Example params (YOU set these paths)
    params = {
        "reads_1": r"/run/desktop/mnt/host/c/Users/Eren/Desktop/CASSIE/kubernetes/test/ecoli_f.fastq",
        "reads_2": r"/run/desktop/mnt/host/c/Users/Eren/Desktop/CASSIE/kubernetes/test/ecoli_r.fastq",
        "reference_fasta": r"/run/desktop/mnt/host/c/Users/Eren/Desktop/CASSIE/kubernetes/test/ref.fasta",
    }

    build_and_run(PIPELINE_SPEC, pipeline_dir="nf_out", params=params)