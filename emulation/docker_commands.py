import subprocess
import docker
import json
import os
import time
import base64


# -------------------------------------------------------------------
# 🔹 Configuration
# -------------------------------------------------------------------
VM_NAMES = ["vm1", "vm2", "vm3"]
IMAGE_NAME = "ubuntu:22.04"
NETWORK_NAME = "workflow-net"
CPU_COUNT = 2           # CPUs per VM container (logical count)
MEMORY_LIMIT = "4g"     # Memory limit per VM container (string)
DATA_BASE_PATH = "C:/data"  # Adjust for your host OS

TENANT_MAP_FILE = os.path.join("data", "tenant_map.json")
client = docker.from_env()

# -------------------------------------------------------------------
# 🔹 Helpers for resource division
# -------------------------------------------------------------------
def _parse_memory(mem_str):
    """Parse memory string like '4g' or '512m' -> bytes (int)."""
    s = mem_str.strip().lower()
    if s.endswith("g"):
        return int(float(s[:-1]) * 1024 ** 3)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1024 ** 2)
    # assume bytes
    return int(s)

def _format_memory(bytes_val):
    """Format bytes into simplest 'Ng' or 'Nm' string for docker mem_limit."""
    gb = bytes_val // (1024 ** 3)
    if gb >= 1 and bytes_val % (1024 ** 3) == 0:
        return f"{gb}g"
    mb = bytes_val // (1024 ** 2)
    return f"{max(1, mb)}m"

def divide_resources_for_tenant(vm_name):
    """
    Simple division of a VM's resources among tenants assigned to it.
    Looks at tenant_map (persistent) to count tenants and divides CPU and memory evenly.
    Returns (nano_cpus, mem_limit_string).
    """
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
    """Create the Docker network if it doesn't exist."""
    existing_networks = [net.name for net in client.networks.list()]
    if NETWORK_NAME not in existing_networks:
        print(f"[+] Creating network '{NETWORK_NAME}'...")
        client.networks.create(NETWORK_NAME)
    else:
        print(f"[*] Network '{NETWORK_NAME}' already exists.")

# -------------------------------------------------------------------
# 🔹 Provisioning Logic
# -------------------------------------------------------------------
def provision_vm(container, name, command_file="provisioning_commands.txt"):
    """
    Executes provisioning commands from a text file inside the container.
    Does NOT create marker files; can run every time.
    """
    if not os.path.exists(command_file):
        print(f"[!] Provisioning file '{command_file}' not found.")
        return

    container.reload()
    was_running = container.status == "running"
    if not was_running:
        print(f"[*] Starting '{name}' temporarily for provisioning...")
        container.start()
        time.sleep(2)

    # Read commands from file
    with open(command_file, "r") as f:
        commands = f.read()

    # Use heredoc to safely write the script inside container
    dest_path = f"/tmp/provision_{name}.sh"
    container.exec_run([
        '/bin/sh', '-c',
        f"cat <<'EOF' > {dest_path}\n{commands}\nEOF"
    ])
    container.exec_run(['/bin/sh', '-c', f"chmod +x {dest_path}"])

    # Execute the script
    print(f"[*] Executing provisioning script in '{name}'...")
    result = container.exec_run(['/bin/sh', dest_path], user="root")
    exit_code = getattr(result, "exit_code", None)
    output = getattr(result, "output", b"").decode(errors="replace")

    if exit_code == 0 or exit_code is None:
        print(f"[✓] Provisioning completed successfully for '{name}'.")
    else:
        print(f"[!] Provisioning failed for '{name}' (exit {exit_code}).\nOutput:\n{output}")

    if not was_running:
        print(f"[*] Stopping '{name}' after provisioning...")
        container.stop()

# -------------------------------------------------------------------
# 🔹 VM Management
# -------------------------------------------------------------------
def ensure_vms():
    """Ensure all VM containers exist and are provisioned."""
    ensure_network()

    for name in VM_NAMES:
        try:
            container = client.containers.get(name)
            print(f"[*] Container '{name}' already exists (status: {container.status}).")
        except docker.errors.NotFound:
            print(f"[+] Creating container '{name}'...")
            os.makedirs(f"{DATA_BASE_PATH}/{name}", exist_ok=True)
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
                volumes={f"{DATA_BASE_PATH}/{name}": {"bind": "/data", "mode": "rw"}},
            )
            time.sleep(2)
        provision_vm(container, name)

    print("[✓] VM initialization and provisioning complete.")


def start_vm(vm_name):
    """Start one specific VM container."""
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
    """Stop one specific VM container."""
    try:
        container = client.containers.get(vm_name)
        if container.status == "running":
            print(f"[-] Stopping container '{vm_name}'...")
            container.stop()
        else:
            print(f"[*] Container '{vm_name}' is already stopped.")
    except docker.errors.NotFound:
        print(f"[!] Container '{vm_name}' not found.")


def execute_in_vm(vm_name, command):
    """Execute a command inside a specific VM container."""
    try:
        container = client.containers.get(vm_name)
        if container.status != "running":
            print(f"[*] Container '{vm_name}' not running. Starting it now...")
            container.start()
            time.sleep(2)

        print(f"[>] Executing in '{vm_name}': {command}")
        exec_result = container.exec_run(["/bin/sh", "-lc", command])
        print(exec_result.output.decode(errors="replace"))
    except docker.errors.NotFound:
        print(f"[!] Container '{vm_name}' not found.")


def list_vms():
    """List all containers managed by this system."""
    print("\n=== Containers ===")
    for name in VM_NAMES:
        try:
            container = client.containers.get(name)
            print(f"{name}: {container.status}")
        except docker.errors.NotFound:
            print(f"{name}: [NOT FOUND]")
    print("==================\n")


def start_all():
    """Start all VM containers."""
    for name in VM_NAMES:
        start_vm(name)


def stop_all():
    """Stop all VM containers."""
    for name in VM_NAMES:
        stop_vm(name)


def get_vm_status(vm_name):
    """Return the status of a specific VM (running/stopped/not found)."""
    try:
        container = client.containers.get(vm_name)
        return container.status
    except docker.errors.NotFound:
        return "not_found"

def tenant_container_name(tenant_name, user_id):
    return f"tenant_{tenant_name}_{user_id}" if user_id is not None else f"tenant_{tenant_name}"

def create_tenant_container(vm_name, tenant_name, user_id=None, cpu_quota=None, mem_limit=None):
    """
    Create a Docker container per tenant inside a VM container.
    Fully isolated: CPU/memory limits, home directory.
    Inherits Python/pip and all packages from the VM.
    """
    suffix = f"_{user_id}" if user_id is not None else ""
    container_name = f"tenant_{tenant_name}{suffix}"
    home_dir_host = os.path.join(DATA_BASE_PATH, container_name)
    os.makedirs(home_dir_host, exist_ok=True)  # persistent home per tenant

    # Check if tenant container already exists
    try:
        cont = client.containers.get(container_name)
        print(f"[*] Tenant container '{container_name}' already exists (status: {cont.status}).")
        return cont
    except docker.errors.NotFound:
        pass

    # Compute default resources
    if cpu_quota is None or mem_limit is None:
        try:
            computed_cpu, computed_mem = divide_resources_for_tenant(vm_name)
        except Exception:
            computed_cpu, computed_mem = int(CPU_COUNT * 1e9 // 2), "2g"
        if cpu_quota is None:
            cpu_quota = int(computed_cpu)
        if mem_limit is None:
            mem_limit = computed_mem

    # Commit the VM as a base image for tenants
    tenant_base_image = f"tenant_base_{vm_name}"
    try:
        client.images.get(tenant_base_image)
        print(f"[*] Tenant base image '{tenant_base_image}' already exists.")
    except docker.errors.ImageNotFound:
        print(f"[+] Committing VM '{vm_name}' as base image '{tenant_base_image}'...")
        vm_container = client.containers.get(vm_name)
        client.api.commit(vm_container.id, tenant_base_image)

    # Run tenant container from VM base image
    cont = client.containers.run(
        image=tenant_base_image,
        name=container_name,
        command="sleep infinity",
        detach=True,
        network_mode=f"container:{vm_name}",  # share VM network
        nano_cpus=int(cpu_quota),
        mem_limit=mem_limit,
        tty=True,
        stdin_open=True,
        volumes={home_dir_host: {"bind": f"/home/{container_name}", "mode": "rw"}},
    )

    print(f"[+] Tenant container '{container_name}' created from VM '{vm_name}' "
          f"(cpu_nano={cpu_quota}, mem={mem_limit}). Python and pip are inherited from VM.")

    return cont

def create_tenant_user(vm_name, tenant_name, user_id=None, cpu_quota=None, mem_limit=None):
    """
    Create (or ensure) a tenant container attached to the given VM and create the tenant OS user
    inside that tenant container. Returns the container object.
    """
    cont = create_tenant_container(vm_name, tenant_name, user_id, cpu_quota=cpu_quota, mem_limit=mem_limit)
    container_name = tenant_container_name(tenant_name, user_id)
    home_dir = f"/home/{container_name}"

    # Ensure container is running
    try:
        cont.reload()
        if cont.status != "running":
            cont.start()
            time.sleep(1)
    except Exception:
        pass

    username = container_name

    # Attempt to create tenant OS user
    try:
        res = cont.exec_run(f"id -u {username}", user="root")
        if res.exit_code != 0:
            # user doesn't exist → create
            create_cmd = f"useradd -m -d {home_dir} -s /bin/bash {username} || true"
            chown_cmd = f"chown -R {username}:{username} {home_dir} || true"
            res_create = cont.exec_run(f"/bin/sh -c '{create_cmd} && {chown_cmd}'", user="root")
            if res_create.exit_code != 0:
                print(f"[!] Warning: Failed to create tenant user {username}. Output:\n{res_create.output.decode(errors='replace')}")
    except Exception as e:
        print(f"[!] Exception while creating tenant user: {e}")

    print(f"[+] Tenant user '{username}' ready in container '{cont.name}'.")
    return cont

# -------------------------------------------------------------------
# 🔹 Tenant helpers (container lifecycle)
# -------------------------------------------------------------------
def get_tenant_container(tenant_name, user_id=None):
    """Return container object for tenant or raise docker.errors.NotFound."""
    suffix = f"_{user_id}" if user_id is not None else ""
    container_name = f"tenant_{tenant_name}{suffix}"
    return client.containers.get(container_name)

def remove_tenant_container(tenant_name, user_id=None, force=True):
    """Remove a tenant container by name (best-effort)."""
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
    """Create a stable key for tenant->vm mapping that allows duplicate tenant names across users."""
    if user_id is None:
        return tenant_name
    return f"{tenant_name}|{user_id}"


def assign_tenant_to_vm(tenant_name, user_id=None):
    """Assign a tenant (optionally scoped to a specific user) to one of the VMs.

    When user_id is provided the mapping key is tenant_name|user_id so multiple users can
    have the same tenant_name without colliding.
    """
    vms = ["vm1", "vm2", "vm3"]
    tenant_map = load_tenant_map()

    key = _tenant_map_key(tenant_name, user_id)
    if key in tenant_map:
        return tenant_map[key]

    # Simple round-robin / least-used based on tenant_map contents
    counts = {vm: 0 for vm in vms}
    for vm in tenant_map.values():
        if vm in counts:
            counts[vm] += 1

    chosen_vm = min(counts, key=counts.get)
    tenant_map[key] = chosen_vm
    save_tenant_map(tenant_map)
    print(f"[+] Assigned tenant '{tenant_name}' (user_id={user_id}) to VM '{chosen_vm}'.")
    return chosen_vm
