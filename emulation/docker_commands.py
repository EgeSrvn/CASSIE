import subprocess
import docker
import json
import os
from pathlib import Path
import platform
import time
import base64
import threading


# -------------------------------------------------------------------
# 🔹 Configuration
# -------------------------------------------------------------------
VM_NAMES = ["vm1"]
IMAGE_NAME = "ubuntu:22.04"
NETWORK_NAME = "workflow-net"
CPU_COUNT = 2           # CPUs per VM container (logical count)
MEMORY_LIMIT = "4g"     # Memory limit per VM container (string)
DATA_BASE_PATH = ""  

if platform.system() == "Windows":
    DATA_BASE_PATH = "C:/data"
else:
    DATA_BASE_PATH = os.path.join(os.getcwd(), "emulation_run", "data")

IS_LINUX = platform.system() == "Linux"

os.makedirs(DATA_BASE_PATH, exist_ok=True)

TENANT_MAP_FILE = Path(DATA_BASE_PATH) / "tenant_map.json"
TENANT_MAP_FILE.parent.mkdir(exist_ok=True, parents=True)

client = docker.from_env()

# -------------------------------------------------------------------
# 🔹 Helpers for resource division
# -------------------------------------------------------------------
def _parse_memory(mem_str):
    """Parse a Docker-style memory string into bytes."""
    s = mem_str.strip().lower()
    if s.endswith("g"):
        return int(float(s[:-1]) * 1024 ** 3)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1024 ** 2)
    # assume bytes
    return int(s)


def _format_memory(bytes_val):
    """Format a byte count to a compact memory string used by Docker."""
    gb = bytes_val // (1024 ** 3)
    if gb >= 1 and bytes_val % (1024 ** 3) == 0:
        return f"{gb}g"
    mb = bytes_val // (1024 ** 2)
    return f"{max(1, mb)}m"


def divide_resources_for_tenant(vm_name):
    """Divide a VM's CPU and memory resources among tenants assigned to it."""
    tenant_map = load_tenant_map()
    count = sum(1 for v in tenant_map.values() if v == vm_name)
    # when creating a new tenant, consider count+1 to be conservative
    tenants = max(1, count + 1)

    # CPU: CPU_COUNT is logical CPUs assigned to VM. convert to nano_cpus
    total_nano = int(CPU_COUNT * 1e9)
    per_tenant_nano = max(1, total_nano // tenants)

    # Memory: parse VM memory limit and divide
    total_mem_bytes = _parse_memory(MEMORY_LIMIT)
    per_tenant_mem_bytes = max(16 * 1024 ** 2, total_mem_bytes // tenants)  # at least 16MB
    mem_limit_str = _format_memory(per_tenant_mem_bytes)

    return per_tenant_nano, mem_limit_str

# -------------------------------------------------------------------
# 🔹 Network Management
# -------------------------------------------------------------------
def ensure_network():
    """Ensure the Docker network for VMs exists."""
    existing_networks = [net.name for net in client.networks.list()]
    if NETWORK_NAME not in existing_networks:
        print(f"[+] Creating network '{NETWORK_NAME}'...")
        client.networks.create(NETWORK_NAME)
    else:
        print(f"[*] Network '{NETWORK_NAME}' already exists.")


# -------------------------------------------------------------------
# 🔹 Provisioning Logic
# -------------------------------------------------------------------
def _exec(container, cmd, user="root"):
    """Helper that works across docker SDK variants."""
    res = container.exec_run(cmd, user=user)
    if hasattr(res, "exit_code"):
        code = res.exit_code
        outb = getattr(res, "output", b"") or b""
        return int(code), outb.decode(errors="replace")
    if isinstance(res, tuple) and len(res) == 2:
        code, outb = res
        outb = outb or b""
        return int(code), outb.decode(errors="replace")
    return 0, str(res)


def provision_vm(container, name, command_file="provisioning_commands.txt"):
    command_file = (Path(__file__).resolve().parent / command_file)
    if not command_file.exists():
        raise FileNotFoundError(f"Provisioning file not found: {command_file}")

    container.reload()
    was_running = container.status == "running"
    if not was_running:
        print(f"[*] Starting '{name}' temporarily for provisioning...")
        container.start()
        time.sleep(2)

    commands = command_file.read_text(encoding="utf-8")
    commands = commands.replace("\r\n", "\n").replace("\r", "\n")

    dest_path = f"/tmp/provision_{name}.sh"

    container.exec_run(
        ["/bin/sh", "-c", f"cat <<'__PROVISION_EOF__' > {dest_path}\n{commands}\n__PROVISION_EOF__"],
        user="root"
    )
    container.exec_run(["/bin/sh", "-c", f"sed -i 's/\\r$//' {dest_path}"], user="root")
    container.exec_run(["/bin/sh", "-c", f"chmod +x {dest_path}"], user="root")

    # Run provisioning script - output goes to Docker logs only (via log_to_container in script)
    # We only log errors to backend, not the full output
    res = container.exec_run(["/bin/bash", "-eux", dest_path], user="root")
    output = getattr(res, "output", b"").decode(errors="replace")

    if getattr(res, "exit_code", 0) != 0:
        # Only print error summary to backend logs
        error_summary = output.split('\n')[-20:]  # Last 20 lines for context
        print(f"[!] Provisioning failed for '{name}'. Exit code: {getattr(res, 'exit_code', 'unknown')}")
        print(f"[!] Error details (see Docker logs for full output):")
        for line in error_summary:
            if line.strip():
                print(f"    {line}")
        raise RuntimeError(f"Provisioning failed for '{name}'. Check Docker logs for container '{name}' for full details.")

    # Hard check
    res = container.exec_run(["/bin/bash", "-c", "test -x /usr/local/bin/fetch"], user="root")
    if res.exit_code != 0:
        raise RuntimeError("fetch missing after provisioning")

    print(f"[✓] Provisioning completed successfully for '{name}'.")

    if not was_running:
        container.stop()

# -------------------------------------------------------------------
# 🔹 VM Management
# -------------------------------------------------------------------
def ensure_vms():
    ensure_network()
    for name in VM_NAMES:
        try:
            container = client.containers.get(name)
            print(f"[*] Container '{name}' already exists (status: {container.status}). Skipping provisioning.")
        except docker.errors.NotFound:
            print(f"[+] Creating container '{name}'...")
            os.makedirs(f"{DATA_BASE_PATH}/{name}", exist_ok=True)
            tools_host = (Path(__file__).resolve().parent / ".." / "dockerized_tools").resolve()
            container = client.containers.run(
                image=IMAGE_NAME,
                name=name,
                command="sleep infinity",
                detach=True,
                network=NETWORK_NAME,
                nano_cpus=int(CPU_COUNT * 1e9),
                mem_limit=MEMORY_LIMIT,
                tty=True,
                stdin_open=True,
                privileged=True,
                dns=["8.8.8.8", "8.8.4.4"],
                volumes={
                    f"{DATA_BASE_PATH}/{name}": {"bind": "/data", "mode": "rw"},
                    str(tools_host): {"bind": "/opt/dockerized_tools", "mode": "ro"},
                    "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                },
            )
            time.sleep(2)
            provision_vm(container, name)
    print("[✓] VM initialization complete.")


def start_vm(vm_name):
    try:
        container = client.containers.get(vm_name)
        if container.status != "running":
            print(f"[+] Starting container '{vm_name}'...")
            container.start()
        else:
            print(f"[*] Container '{vm_name}' is already running.")
    except docker.errors.NotFound:
        print(f"[!] Container '{vm_name}' not found.")


def stop_vm(vm_name):
    try:
        container = client.containers.get(vm_name)
        if container.status == "running":
            print(f"[-] Stopping container '{vm_name}'...")
            container.stop()
        else:
            print(f"[*] Container '{vm_name}' is already stopped.")
    except docker.errors.NotFound:
        print(f"[!] Container '{vm_name}' not found.")


def list_vms():
    print("\n=== Containers ===")
    for name in VM_NAMES:
        try:
            container = client.containers.get(name)
            print(f"{name}: {container.status}")
        except docker.errors.NotFound:
            print(f"{name}: [NOT FOUND]")
    print("==================\n")


def start_all():
    for name in VM_NAMES:
        start_vm(name)


def stop_all():
    for name in VM_NAMES:
        stop_vm(name)


def get_vm_status(vm_name):
    try:
        container = client.containers.get(vm_name)
        return container.status
    except docker.errors.NotFound:
        return "not_found"


def tenant_container_name(tenant_name, user_id):
    return f"tenant_{tenant_name}_{user_id}" if user_id is not None else f"tenant_{tenant_name}"


def create_tenant_container(vm_name, tenant_name, user_id=None, cpu_quota=None, mem_limit=None):
    suffix = f"_{user_id}" if user_id is not None else ""
    container_name = f"tenant_{tenant_name}{suffix}"
    home_dir_host = os.path.join(DATA_BASE_PATH, container_name)
    os.makedirs(home_dir_host, exist_ok=True)

    try:
        cont = client.containers.get(container_name)
        print(f"[*] Tenant container '{container_name}' already exists.")
        return cont
    except docker.errors.NotFound:
        pass

    if cpu_quota is None or mem_limit is None:
        try:
            computed_cpu, computed_mem = divide_resources_for_tenant(vm_name)
        except Exception:
            computed_cpu, computed_mem = int(CPU_COUNT * 1e9 // 2), "2g"
        cpu_quota = int(cpu_quota or computed_cpu)
        mem_limit = mem_limit or computed_mem

    tenant_base_image = f"tenant_base_{vm_name}"

    def commit_vm_async():
        try:
            vm_container = client.containers.get(vm_name)
            print(f"[+] (async) Committing VM '{vm_name}' as '{tenant_base_image}'...")
            client.api.commit(vm_container.id, tenant_base_image)
            print(f"[+] (async) VM '{vm_name}' committed successfully.")
        except Exception as e:
            print(f"[!] (async) VM commit failed: {e}")

    try:
        client.images.get(tenant_base_image)
        print(f"[*] Tenant base image '{tenant_base_image}' already exists.")
    except docker.errors.ImageNotFound:
        # Always use async commit to avoid timeout issues (committing can take a long time)
        print(f"[+] Starting async commit of VM '{vm_name}' as base image '{tenant_base_image}'...")
        print(f"[*] This may take several minutes depending on VM size...")
        commit_thread = threading.Thread(target=commit_vm_async, daemon=True)
        commit_thread.start()

    print(f"[*] Waiting for base image '{tenant_base_image}' to be ready...")
    # Increase wait time to 5 minutes (300 seconds) to handle large VM commits
    max_wait_seconds = 300
    for i in range(max_wait_seconds):
        try:
            client.images.get(tenant_base_image)
            print(f"[✓] Base image '{tenant_base_image}' is ready!")
            break
        except docker.errors.ImageNotFound:
            if i % 10 == 0 and i > 0:
                print(f"    ... waiting for image commit ({i}s / {max_wait_seconds}s)")
            time.sleep(1)
    else:
        raise RuntimeError(
            f"Tenant base image '{tenant_base_image}' not ready after {max_wait_seconds} seconds. "
            f"The commit may still be in progress. Check Docker Desktop for commit status."
        )

    # --- CALCULATE HOST PATH FOR /DATA ---
    host_data_path = os.path.abspath(f"{DATA_BASE_PATH}/{vm_name}")
    
    # Get tools host path (same as in ensure_vms) - mount it so wrappers can access updated scripts
    tools_host = (Path(__file__).resolve().parent / ".." / "dockerized_tools").resolve()

    cont = client.containers.run(
        image=tenant_base_image,
        name=container_name,
        command="sleep infinity",
        detach=True,
        network_mode=f"container:{vm_name}",
        nano_cpus=int(cpu_quota),
        mem_limit=mem_limit,
        tty=True,
        stdin_open=True,
        environment={
            "HOST_DATA_PATH": host_data_path  # <--- Injecting the host path here
        },
        volumes={
            home_dir_host: {"bind": f"/home/{container_name}", "mode": "rw"},
            f"{DATA_BASE_PATH}/{vm_name}": {"bind": "/data", "mode": "rw"},
            "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
            str(tools_host): {"bind": "/opt/dockerized_tools", "mode": "ro"},  # Mount tools so wrappers can access updated scripts
        },
    )

    print(f"[+] Tenant container '{container_name}' created on VM '{vm_name}'.")
    
    # Write progress to VM container logs so it's visible in Docker Desktop
    try:
        vm_container = client.containers.get(vm_name)
        vm_container.exec_run(
            ["/bin/sh", "-c", f"echo '[TENANT] Tenant container {container_name} created successfully' > /proc/1/fd/1"],
            user="root"
        )
    except:
        pass  # Non-critical
    
    return cont


def create_tenant_user(vm_name, tenant_name, user_id=None, cpu_quota=None, mem_limit=None):
    cont = create_tenant_container(vm_name, tenant_name, user_id, cpu_quota=cpu_quota, mem_limit=mem_limit)
    container_name = tenant_container_name(tenant_name, user_id)
    username = container_name
    home_dir = f"/home/{username}"

    try:
        cont.reload()
        if cont.status != "running":
            cont.start()
            time.sleep(1)
    except Exception:
        pass

    def sh(cmd: str):
        return cont.exec_run(["/bin/sh", "-c", cmd], user="root")

    res = sh(f"id -u {username} >/dev/null 2>&1; echo $?")
    if res.exit_code == 0 and res.output.strip() == b"0":
        user_created = False
    else:
        user_created = True
        sh(f"useradd -m -d {home_dir} -s /bin/bash {username} 2>/dev/null || true")
        sh(f"mkdir -p {home_dir}")
        sh(f"chown -R {username}:{username} {home_dir} || true")

    sh("groupadd -f docker || true")
    sh(f"usermod -aG docker {username} || true")
    sh("chgrp docker /var/run/docker.sock 2>/dev/null || true")
    sh("chmod 660 /var/run/docker.sock 2>/dev/null || true")
    sh("mkdir -p /data || true")
    sh(f"chown -R {username}:{username} /data || true")
    sh("chmod 775 /data || true")
    sh(f"mkdir -p {home_dir}/fastqc_out && chown -R {username}:{username} {home_dir}/fastqc_out || true")

    print(f"[+] Tenant user '{username}' ready in container '{cont.name}' (created={user_created}).")
    
    # Write progress to VM container logs for Docker Desktop visibility
    try:
        vm_container = client.containers.get(vm_name)
        vm_container.exec_run(
            ["/bin/sh", "-c", f"echo '[TENANT] Tenant user {username} ready in container {cont.name}' > /proc/1/fd/1"],
            user="root"
        )
    except:
        pass  # Non-critical
    
    return cont

# -------------------------------------------------------------------
# 🔹 Tenant helpers (container lifecycle)
# -------------------------------------------------------------------
def get_tenant_container(tenant_name, user_id=None):
    suffix = f"_{user_id}" if user_id is not None else ""
    container_name = f"tenant_{tenant_name}{suffix}"
    return client.containers.get(container_name)


def remove_tenant_container(tenant_name, user_id=None, force=True):
    try:
        cont = get_tenant_container(tenant_name, user_id)
        cont.remove(force=force)
        print(f"[-] Removed tenant container '{cont.name}'.")
        return True
    except docker.errors.NotFound:
        print(f"[*] Tenant container not found for '{tenant_name}' (user_id={user_id}).")
        return False
    except Exception as e:
        print(f"[!] Failed to remove tenant container: {e}")
        return False

# -------------------------------------------------------------------
# 🔹 Tenant to VM Assignment
# -------------------------------------------------------------------
def load_tenant_map():
    if not os.path.exists(TENANT_MAP_FILE):
        return {}
    with open(TENANT_MAP_FILE, "r") as f:
        return json.load(f)


def save_tenant_map(data):
    os.makedirs(os.path.dirname(TENANT_MAP_FILE), exist_ok=True)
    with open(TENANT_MAP_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _tenant_map_key(tenant_name, user_id):
    if user_id is None:
        return tenant_name
    return f"{tenant_name}|{user_id}"


def assign_tenant_to_vm(tenant_name, user_id=None):
    vms = ["vm1", "vm2", "vm3"]
    tenant_map = load_tenant_map()

    key = _tenant_map_key(tenant_name, user_id)
    if key in tenant_map:
        return tenant_map[key]

    counts = {vm: 0 for vm in vms}
    for vm in tenant_map.values():
        if vm in counts:
            counts[vm] += 1

    chosen_vm = min(counts, key=counts.get)
    tenant_map[key] = chosen_vm
    save_tenant_map(tenant_map)
    print(f"[+] Assigned tenant '{tenant_name}' (user_id={user_id}) to VM '{chosen_vm}'.")
    return chosen_vm