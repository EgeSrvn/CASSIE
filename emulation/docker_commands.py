import docker
import os

# -------------------------------------------------------------------
# 🔹 Configuration
# -------------------------------------------------------------------
VM_NAMES = ["vm1", "vm2", "vm3"]
IMAGE_NAME = "ubuntu:22.04"
NETWORK_NAME = "workflow-net"
CPU_COUNT = 2           # CPUs per container
MEMORY_LIMIT = "4g"     # Memory limit per container
DATA_BASE_PATH = "C:/data"  # Adjust for your host OS

client = docker.from_env()

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
# 🔹 VM Management
# -------------------------------------------------------------------
def ensure_vms():
    """
    Ensure that all VM containers exist (but don't force-start them).
    They act as persistent worker VMs for different tenants.
    """
    ensure_network()

    for name in VM_NAMES:
        try:
            container = client.containers.get(name)
            print(f"[*] Container '{name}' already exists (status: {container.status}).")
        except docker.errors.NotFound:
            print(f"[+] Creating container '{name}'...")
            os.makedirs(f"{DATA_BASE_PATH}/{name}", exist_ok=True)
            client.containers.run(
                image=IMAGE_NAME,
                name=name,
                command="sleep infinity",  # Keep the container alive
                detach=True,
                network=NETWORK_NAME,
                nano_cpus=int(CPU_COUNT * 1e9),  # Convert to nanoseconds
                mem_limit=MEMORY_LIMIT,
                tty=True,
                stdin_open=True,
                volumes={
                    f"{DATA_BASE_PATH}/{name}": {"bind": "/data", "mode": "rw"}
                },
            )
    print("[✓] VM initialization check complete.")


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

        print(f"[>] Executing in '{vm_name}': {command}")
        exec_result = container.exec_run(command)
        print(exec_result.output.decode())
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
