import subprocess
import docker
import json
import os
from pathlib import Path
import platform
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
DATA_BASE_PATH = ""  

if platform.system() == "Windows":
    DATA_BASE_PATH = "C:/data"
else:
    DATA_BASE_PATH = os.path.join(os.getcwd(), "emulation_run", "data")

os.makedirs(DATA_BASE_PATH, exist_ok=True)

TENANT_MAP_FILE = Path(DATA_BASE_PATH) / "tenant_map.json"
TENANT_MAP_FILE.parent.mkdir(exist_ok=True, parents=True)

client = docker.from_env()

# -------------------------------------------------------------------
# 🔹 Helpers for resource division
# -------------------------------------------------------------------
def _parse_memory(mem_str):
    """Parse a Docker-style memory string into bytes.

    Supports suffixes 'g' and 'm' (case-insensitive). If no suffix is
    present the value is interpreted as bytes.

    Args:
        mem_str (str): Memory string like '4g', '512m' or raw bytes.

    Returns:
        int: Memory size in bytes.
    """
    s = mem_str.strip().lower()
    if s.endswith("g"):
        return int(float(s[:-1]) * 1024 ** 3)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1024 ** 2)
    # assume bytes
    return int(s)


def _format_memory(bytes_val):
    """Format a byte count to a compact memory string used by Docker.

    Chooses 'Ng' if evenly divisible by a gigabyte, otherwise returns
    an integer number of megabytes with 'm' suffix. Ensures at least
    '1m' is returned.

    Args:
        bytes_val (int): Memory size in bytes.

    Returns:
        str: Memory string like '4g' or '512m'.
    """
    gb = bytes_val // (1024 ** 3)
    if gb >= 1 and bytes_val % (1024 ** 3) == 0:
        return f"{gb}g"
    mb = bytes_val // (1024 ** 2)
    return f"{max(1, mb)}m"


def divide_resources_for_tenant(vm_name):
    """Divide a VM's CPU and memory resources among tenants assigned to it.

    Reads the persistent tenant map to determine how many tenants are
    already assigned to the given vm_name and conservatively assumes one
    additional tenant (count+1) when computing per-tenant allocations.

    CPU is returned as Docker's nano_cpus integer. Memory is returned as
    a Docker mem_limit string.

    Args:
        vm_name (str): Name of the VM to divide resources for.

    Returns:
        tuple: (nano_cpus: int, mem_limit_str: str)
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
    """Ensure the Docker network for VMs exists, creating it if necessary.

    Uses the global NETWORK_NAME and the docker client configured at module import.
    Prints progress to stdout.

    Returns:
        None
    """
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
    """Run provisioning commands inside a container from a text file.

    The function will start the container temporarily if it is not running,
    write the contents of command_file into a script under /tmp inside the
    container, make it executable and execute it as root. The container is
    stopped again if it was not running originally.

    Args:
        container (docker.models.containers.Container): Container object.
        name (str): Logical name used for temporary filenames and logging.
        command_file (str): Path to a local file containing shell commands.

    Returns:
        None

    Notes:
        - Any output and non-zero exit codes are printed to stdout.
        - If command_file does not exist the function returns early.
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
    """Ensure all configured VM containers exist and are provisioned.

    For each name in VM_NAMES this will:
      - create the Docker network if missing,
      - create the container if it does not exist (with configured resources),
      - run provisioning inside each container.

    Returns:
        None
    """
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
    """Start a single VM container if it is not already running.

    Args:
        vm_name (str): Name of the VM container.

    Returns:
        None
    """
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
    """Stop a single VM container if it is running.

    Args:
        vm_name (str): Name of the VM container.

    Returns:
        None
    """
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
    """Print the status of all configured VM containers to stdout.

    Uses VM_NAMES to determine which containers to check. Missing containers
    are reported as '[NOT FOUND]'.

    Returns:
        None
    """
    print("\n=== Containers ===")
    for name in VM_NAMES:
        try:
            container = client.containers.get(name)
            print(f"{name}: {container.status}")
        except docker.errors.NotFound:
            print(f"{name}: [NOT FOUND]")
    print("==================\n")


def start_all():
    """Start all configured VM containers.

    Iterates VM_NAMES and calls start_vm on each entry.

    Returns:
        None
    """
    for name in VM_NAMES:
        start_vm(name)


def stop_all():
    """Stop all configured VM containers.

    Iterates VM_NAMES and calls stop_vm on each entry.

    Returns:
        None
    """
    for name in VM_NAMES:
        stop_vm(name)


def get_vm_status(vm_name):
    """Return the status of a specific VM container.

    Args:
        vm_name (str): Name of the VM container.

    Returns:
        str: Container status string (e.g. 'running', 'exited') or 'not_found'.
    """
    try:
        container = client.containers.get(vm_name)
        return container.status
    except docker.errors.NotFound:
        return "not_found"


def tenant_container_name(tenant_name, user_id):
    """Construct the canonical tenant container name.

    If user_id is provided the name includes it to allow duplicate tenant
    names across different users.

    Args:
        tenant_name (str): Logical tenant name.
        user_id (Optional[str|int]): Optional user identifier.

    Returns:
        str: Container name like 'tenant_<name>_<user_id>' or 'tenant_<name>'.
    """
    return f"tenant_{tenant_name}_{user_id}" if user_id is not None else f"tenant_{tenant_name}"


def create_tenant_container(vm_name, tenant_name, user_id=None, cpu_quota=None, mem_limit=None):
    """Create a tenant container derived from a VM container image.

    This function:
      - ensures a persistent host directory for the tenant home,
      - computes resource defaults if not provided,
      - commits the VM container as a base image (if necessary),
      - runs a new container from that base image with the requested limits,
      - shares the VM network by using network_mode 'container:<vm>'.

    Args:
        vm_name (str): VM container name to derive the image from.
        tenant_name (str): Logical tenant name.
        user_id (Optional[str|int]): Optional user identifier to isolate names.
        cpu_quota (Optional[int]): nano_cpus integer for Docker (overrides computed).
        mem_limit (Optional[str]): mem_limit string for Docker (overrides computed).

    Returns:
        docker.models.containers.Container: The newly created (or existing) tenant container.
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
    """Ensure a tenant container exists and create an OS user inside it.

    This will create the tenant container (if needed), start it if not
    running, then create a Linux user with the same name as the tenant
    container and set ownership of the home directory.

    Args:
        vm_name (str): VM to derive the tenant from.
        tenant_name (str): Tenant name.
        user_id (Optional[str|int]): Optional user id to disambiguate names.
        cpu_quota (Optional[int]): Optional nano_cpus for container creation.
        mem_limit (Optional[str]): Optional mem_limit for container creation.

    Returns:
        docker.models.containers.Container: The tenant container object.
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
    """Return the Docker container object for a tenant by name.

    Args:
        tenant_name (str): Tenant's logical name.
        user_id (Optional[str|int]): Optional user scope.

    Returns:
        docker.models.containers.Container: The container object.

    Raises:
        docker.errors.NotFound: If the tenant container does not exist.
    """
    suffix = f"_{user_id}" if user_id is not None else ""
    container_name = f"tenant_{tenant_name}{suffix}"
    return client.containers.get(container_name)


def remove_tenant_container(tenant_name, user_id=None, force=True):
    """Remove (delete) a tenant container if it exists.

    Performs a best-effort removal and prints status.

    Args:
        tenant_name (str): Tenant name.
        user_id (Optional[str|int]): Optional user id to disambiguate.
        force (bool): If True, force removal of running containers.

    Returns:
        bool: True if removal was attempted and succeeded, False otherwise.
    """
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
    """Load the persistent tenant->VM mapping from disk.

    Returns an empty dict if the mapping file does not exist.

    Returns:
        dict: Mapping of tenant keys to VM names.
    """
    if not os.path.exists(TENANT_MAP_FILE):
        return {}
    with open(TENANT_MAP_FILE, "r") as f:
        return json.load(f)


def save_tenant_map(data):
    """Save the tenant->VM mapping to disk.

    Ensures the parent directory exists and writes JSON with indentation.

    Args:
        data (dict): Mapping of tenant keys to VM names.

    Returns:
        None
    """
    os.makedirs(os.path.dirname(TENANT_MAP_FILE), exist_ok=True)
    with open(TENANT_MAP_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _tenant_map_key(tenant_name, user_id):
    """Create a stable key for tenant map storage that includes user scope.

    When user_id is None the key is simply tenant_name; otherwise it uses
    'tenant_name|user_id' to avoid collisions between users.

    Args:
        tenant_name (str): Tenant name.
        user_id (Optional[str|int]): Optional user identifier.

    Returns:
        str: Stable dictionary key for tenant mapping.
    """
    if user_id is None:
        return tenant_name
    return f"{tenant_name}|{user_id}"


def assign_tenant_to_vm(tenant_name, user_id=None):
    """Assign a tenant to one of the configured VMs and persist the assignment.

    If the tenant (or tenant+user scope) already has an assignment that is
    returned. Otherwise a simple least-used selection across vm1, vm2, vm3
    is performed and the mapping is saved.

    Args:
        tenant_name (str): Logical tenant name.
        user_id (Optional[str|int]): Optional user identifier to disambiguate.

    Returns:
        str: Chosen VM name for the tenant.
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
