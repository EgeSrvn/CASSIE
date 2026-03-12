import os
import time
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Union


def _run(cmd: List[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def ensure_local_registry(
    *,
    registry_host: str = "localhost",
    registry_port: int = 5000,
    container_name: str = "local-registry",
) -> str:
    """
    Start a local Docker registry container if not running.
    Returns registry base like: "localhost:5000"
    """
    registry = f"{registry_host}:{registry_port}"

    # Is it running?
    ps = _run(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"], check=False).stdout or ""
    if container_name not in ps.splitlines():
        # Exists but stopped?
        allc = _run(["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"], check=False).stdout or ""
        if container_name in allc.splitlines():
            _run(["docker", "start", container_name])
        else:
            _run([
                "docker", "run", "-d",
                "--restart=always",
                "-p", f"{registry_port}:5000",
                "--name", container_name,
                "registry:2"
            ])

    # Sanity ping registry
    import urllib.request
    url = f"http://{registry}/v2/_catalog"
    for _ in range(5):
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                resp.read()
            return registry
        except Exception:
            time.sleep(1)

    raise RuntimeError(
        f"Local registry did not respond at {url}. "
        f"Check Docker Desktop and whether port {registry_port} is free."
    )


def tag_and_push_to_registry(
    *,
    local_image: str,
    registry: str,
    remote_repo: str,
    remote_tag: Optional[str] = None,
) -> str:
    """
    Tags local_image and pushes it to the local registry.
    Example:
      local_image="fastqc:0.12.1"
      registry="localhost:5000"
      remote_repo="fastqc"
      remote_tag="0.12.1"

    Returns: "localhost:5000/fastqc:0.12.1"
    """
    # Validate local image exists
    try:
        _run(["docker", "image", "inspect", local_image])
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Local image '{local_image}' not found.\n"
            f"Run: docker images\n"
            f"STDERR:\n{e.stderr}"
        ) from e

    # Infer tag if not provided
    if remote_tag is None:
        if ":" in local_image:
            remote_tag = local_image.split(":", 1)[1]
        else:
            remote_tag = "latest"

    remote_image = f"{registry}/{remote_repo}:{remote_tag}"

    try:
        _run(["docker", "tag", local_image, remote_image])
        _run(["docker", "push", remote_image])
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to tag/push image to {remote_image}.\n"
            f"If Kubernetes can't pull it, add insecure-registries ['{registry}'] "
            f"in Docker Desktop → Settings → Docker Engine.\n"
            f"STDERR:\n{e.stderr}"
        ) from e

    return remote_image


def windows_path_to_docker_desktop_hostpath(win_path: Union[str, Path]) -> str:
    """
    Docker Desktop Kubernetes hostPath mapping for Windows:
      C:\\Users\\Eren\\... -> /run/desktop/mnt/host/c/Users/Eren/...

    If you're not on Docker Desktop Windows, do NOT use this; pass your native hostPath.
    """
    p = Path(win_path).resolve()
    drive = p.drive.replace(":", "").lower()
    parts = p.parts[1:]  # drop "C:\\"
    tail = "/".join(parts).replace("\\", "/")
    return f"/run/desktop/mnt/host/{drive}/{tail}"


def write_k8s_job_yaml(
    *,
    job_name: str,
    image: str,
    command: List[str],
    args: List[str],
    namespace: str = "default",
    volume_mounts: Optional[List[Dict]] = None,
    volumes: Optional[List[Dict]] = None,
    image_pull_policy: str = "Always",
    backoff_limit: int = 0,
    restart_policy: str = "Never",
    out_path: Union[str, Path] = "job.yaml",
) -> Path:
    """
    Writes a general Kubernetes Job YAML file.

    volume_mounts example:
      [{"name":"shared-data","mountPath":"/data"}]

    volumes example (hostPath):
      [{"name":"shared-data","hostPath":{"path":"/run/.../test","type":"Directory"}}]
    """
    volume_mounts = volume_mounts or []
    volumes = volumes or []

    # Minimal YAML manual construction (no external libs)
    def indent(lines: List[str], n: int) -> List[str]:
        pad = " " * n
        return [pad + line if line else line for line in lines]

    def dump_obj(obj, level=0) -> List[str]:
        # very small YAML dumper for dict/list/scalars; enough for job specs here
        lines = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{k}:")
                    lines.extend(indent(dump_obj(v, level + 1), 2))
                else:
                    if isinstance(v, str):
                        lines.append(f"{k}: {v}")
                    else:
                        lines.append(f"{k}: {json.dumps(v)}")
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    lines.append("-")
                    lines.extend(indent(dump_obj(item, level + 1), 2))
                else:
                    lines.append(f"- {item}")
        else:
            lines.append(str(obj))
        return lines

    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": namespace},
        "spec": {
            "backoffLimit": backoff_limit,
            "template": {
                "spec": {
                    "restartPolicy": restart_policy,
                    "containers": [
                        {
                            "name": "main",
                            "image": image,
                            "imagePullPolicy": image_pull_policy,
                            "command": command,
                            "args": args,
                            **({"volumeMounts": volume_mounts} if volume_mounts else {}),
                        }
                    ],
                    **({"volumes": volumes} if volumes else {}),
                }
            },
        },
    }

    yaml_lines = dump_obj(job)
    out_path = Path(out_path)
    out_path.write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    return out_path


def apply_job_and_wait(
    *,
    job_name: str,
    job_yaml_path: Union[str, Path],
    namespace: str = "default",
    timeout_seconds: int = 600,
    delete_first: bool = True,
) -> str:
    """
    Applies job YAML and waits until it succeeds or fails.
    Returns logs as string.
    """
    job_yaml_path = Path(job_yaml_path)

    # Delete existing job (optional)
    if delete_first:
        _run(["kubectl", "delete", "job", job_name, "-n", namespace, "--ignore-not-found"], check=False)

    # Apply
    try:
        _run(["kubectl", "apply", "-f", str(job_yaml_path)])
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "kubectl apply failed. Common causes:\n"
            "- Docker Desktop Kubernetes not running\n"
            "- Wrong kubectl context\n\n"
            "Try:\n"
            "  kubectl config use-context docker-desktop\n"
            "  kubectl get nodes\n\n"
            f"STDERR:\n{e.stderr}"
        ) from e

    start = time.time()
    last = ""
    while True:
        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for job '{job_name}'.")

        out = _run(["kubectl", "get", "job", job_name, "-n", namespace, "-o", "json"]).stdout
        job = json.loads(out)

        succeeded = job.get("status", {}).get("succeeded", 0) or 0
        failed = job.get("status", {}).get("failed", 0) or 0
        active = job.get("status", {}).get("active", 0) or 0

        status = f"active={active} succeeded={succeeded} failed={failed}"
        if status != last:
            print(f"[job status] {status}")
            last = status

        if succeeded >= 1 or failed >= 1:
            break
        time.sleep(2)

    logs = _run(["kubectl", "logs", f"job/{job_name}", "-n", namespace], check=False).stdout or ""
    print("\n=== Job Logs ===\n" + (logs if logs.strip() else "(no logs)"))

    if "failed=" in last and "failed=0" not in last and "succeeded=0" in last:
        raise RuntimeError(f"Job '{job_name}' failed.\nLogs:\n{logs}")

    return logs


def assert_outputs_exist(
    *,
    output_dir: Union[str, Path],
    expected_files: List[str],
) -> Dict[str, str]:
    """
    Checks that expected_files exist in output_dir.
    Returns dict of file -> absolute path.
    Raises if any missing.
    """
    output_dir = Path(output_dir).resolve()
    missing = []
    found = {}
    for f in expected_files:
        p = output_dir / f
        if not p.exists():
            missing.append(f)
        else:
            found[f] = str(p)
    if missing:
        files = sorted([p.name for p in output_dir.iterdir() if p.is_file()])
        raise RuntimeError(
            "Job completed but expected outputs are missing:\n"
            + "\n".join(f" - {m}" for m in missing)
            + "\n\nDirectory contents:\n"
            + "\n".join(f" - {x}" for x in files[:200])
        )
    return found


def run_tool_job_with_local_registry(
    *,
    # Registry
    registry_host: str = "localhost",
    registry_port: int = 5000,
    registry_container_name: str = "local-registry",

    # Image publish
    local_image: str,
    remote_repo: str,
    remote_tag: Optional[str] = None,

    # Job
    job_name: str,
    namespace: str = "default",
    command: List[str],
    args: List[str],

    # Volumes
    host_dir: Optional[Union[str, Path]] = None,
    container_mount_path: Optional[str] = None,
    docker_desktop_windows_hostpath: bool = True,  # set False on Linux EC2 (then host_dir used as-is)

    # Output validation (optional)
    expected_outputs: Optional[List[str]] = None,

    # Paths/timeouts
    job_yaml_out_path: Optional[Union[str, Path]] = None,
    timeout_seconds: int = 6000000,
) -> Dict:
    """
    One general orchestrator:
      1) ensure local registry
      2) tag+push local_image -> registry
      3) create job YAML that runs the tool
      4) apply and wait
      5) optionally verify outputs exist

    You can reuse this for ANY tool image and ANY input files.
    """
    registry = ensure_local_registry(
        registry_host=registry_host,
        registry_port=registry_port,
        container_name=registry_container_name,
    )

    pushed_image = tag_and_push_to_registry(
        local_image=local_image,
        registry=registry,
        remote_repo=remote_repo,
        remote_tag=remote_tag,
    )

    volume_mounts = []
    volumes = []

    if host_dir and container_mount_path:
        host_dir = Path(host_dir).resolve()
        if not host_dir.exists():
            raise FileNotFoundError(f"host_dir does not exist: {host_dir}")

        hostpath = str(host_dir)
        if docker_desktop_windows_hostpath:
            hostpath = windows_path_to_docker_desktop_hostpath(host_dir)

        volume_mounts = [{"name": "shared-data", "mountPath": container_mount_path}]
        volumes = [{"name": "shared-data", "hostPath": {"path": hostpath, "type": "Directory"}}]

    if job_yaml_out_path is None:
        # If host_dir is provided, write YAML next to it; else current directory
        base_dir = Path(host_dir) if host_dir else Path.cwd()
        job_yaml_out_path = base_dir / f"{job_name}.yaml"

    job_yaml = write_k8s_job_yaml(
        job_name=job_name,
        namespace=namespace,
        image=pushed_image,
        command=command,
        args=args,
        volume_mounts=volume_mounts,
        volumes=volumes,
        out_path=job_yaml_out_path,
    )

    logs = apply_job_and_wait(
        job_name=job_name,
        namespace=namespace,
        job_yaml_path=job_yaml,
        timeout_seconds=timeout_seconds,
        delete_first=True,
    )

    output_paths = None
    if expected_outputs and host_dir:
        output_paths = assert_outputs_exist(output_dir=host_dir, expected_files=expected_outputs)

    return {
        "registry": registry,
        "pushed_image": pushed_image,
        "job_yaml_path": str(Path(job_yaml).resolve()),
        "job_name": job_name,
        "namespace": namespace,
        "logs": logs,
        "outputs": output_paths,
    }




# -------------------------
# Example: FastQC
# -------------------------
# result = run_tool_job_with_local_registry(
#     local_image="fastqc:0.12.1",
#     remote_repo="fastqc",
#     job_name="fastqc-job",
#     command=["bash", "-lc"],
#     args=["fastqc /data/ecoli_f.fastq -o /data"],
#     host_dir=r"C:\Users\Eren\Desktop\CASSIE\kubernetes\test",
#     container_mount_path="/data",
#     expected_outputs=["ecoli_f_fastqc.html", "ecoli_f_fastqc.zip"],
# )
# print(result)

run_tool_job_with_local_registry(
     local_image="spades:latest",
     remote_repo="spades",
     job_name="spades-job",
     command=["bash", "-lc"],
     args=["spades -1 /data/ecoli_f.fastq -2 /data/ecoli_r.fastq -o /data"],
     host_dir=r"C:\Users\Eren\Desktop\CASSIE\kubernetes\test",
     container_mount_path="/data",
     expected_outputs=["spades_out/contigs.fasta", "spades_out/spades.log"],
 )