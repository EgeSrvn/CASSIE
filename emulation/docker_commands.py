import docker

# Configuration
VM_NAMES = ["vm1", "vm2", "vm3"]
IMAGE_NAME = "ubuntu:22.04"   # Replace with your own VM image
NETWORK_NAME = "workflow-net"
CPU_COUNT = 2
MEMORY_LIMIT = "4g"
DATA_BASE_PATH = "C:/data"  # Adjust for Windows or use absolute path you prefer

client = docker.from_env()

def ensure_network():
    """Create the Docker network if it doesn't exist."""
    networks = [net.name for net in client.networks.list()]
    if NETWORK_NAME not in networks:
        print(f"Creating network '{NETWORK_NAME}'...")
        client.networks.create(NETWORK_NAME)
    else:
        print(f"Network '{NETWORK_NAME}' already exists.")

def ensure_vms():
    """Create VM containers if they don't exist."""
    for name in VM_NAMES:
        try:
            container = client.containers.get(name)
            print(f"Container '{name}' already exists (status: {container.status}).")
        except docker.errors.NotFound:
            print(f"Creating container '{name}'...")
            client.containers.run(
                image=IMAGE_NAME,
                name=name,
                command="sleep infinity",  # keep container running
                detach=True,
                network=NETWORK_NAME,
                nano_cpus=CPU_COUNT * 1_000_000_000,  # 1e9 = 1 CPU
                mem_limit=MEMORY_LIMIT,
                volumes={f"{DATA_BASE_PATH}/{name}": {"bind": "/data", "mode": "rw"}},
            )
    start_vm(VM_NAMES[0])  # Start the first VM by default

def list_vms():
    """List all containers and their status."""
    containers = client.containers.list(all=True)
    if not containers:
        print("No containers found.")
        return
    print("\n=== Containers ===")
    for c in containers:
        print(f"{c.name}: {c.status}")
    print("==================\n")

def start_vm(vm_name):
    """Start one specific VM container."""
    try:
        container = client.containers.get(vm_name)
        if container.status != "running":
            print(f"Starting container '{vm_name}'...")
            container.start()
        else:
            print(f"Container '{vm_name}' is already running.")
    except docker.errors.NotFound:
        print(f"Container '{vm_name}' not found.")

def stop_vm(vm_name):
    """Stop one specific VM container."""
    try:
        container = client.containers.get(vm_name)
        if container.status == "running":
            print(f"Stopping container '{vm_name}'...")
            container.stop()
        else:
            print(f"Container '{vm_name}' is not running.")
    except docker.errors.NotFound:
        print(f"Container '{vm_name}' not found.")

def execute_in_vm(vm_name, command):
    """Execute a command inside a specific VM container."""
    try:
        container = client.containers.get(vm_name)
        if container.status != "running":
            print(f"Container '{vm_name}' is not running. Starting it now...")
            container.start()
        print(f"Executing command in '{vm_name}': {command}")
        exec_log = container.exec_run(command)
        print(exec_log.output.decode())
    except docker.errors.NotFound:
        print(f"Container '{vm_name}' not found.")

def start_all():
    """Start all containers."""
    for name in VM_NAMES:
        start_vm(name)

def stop_all():
    """Stop all containers."""
    for name in VM_NAMES:
        stop_vm(name)