# vm_manager.py
import docker
import os
from bucket_manager import create_bucket, delete_bucket, init_s3_client

# Connect to Docker
client = docker.from_env()

# Define VM capacity and tenant slice rules
'''
VM_SLICES = {
    "vm1": {"tenants": 16, "cpu_per_tenant": 0.25, "mem_per_tenant": 0.5},
    "vm2": {"tenants": 8,  "cpu_per_tenant": 0.5,  "mem_per_tenant": 1},
    "vm3": {"tenants": 4,  "cpu_per_tenant": 1,    "mem_per_tenant": 2},
}
'''

# Tenant registry: {tenant_name: {"vm": str, "id": int}}
TENANT_REGISTRY = {}

VM_CAPACITY = {
    "vm1": 16,
    "vm2": 8,
    "vm3": 4
}
VM_LOAD = {
    "vm1": 0,
    "vm2": 0,
    "vm3": 0
}

def find_available_vm():
    """Find a VM with available capacity."""
    for vm, capacity in VM_CAPACITY.items():
        if VM_LOAD[vm] < capacity:
            return vm
    return None

# Add a tenant to a VM
def add_tenant(tenant_name, vm_name=None):
    """Add a tenant and create their bucket."""
    s3 = init_s3_client()

    # Choose VM automatically if not given
    if not vm_name:
        vm_name = find_available_vm()
        if not vm_name:
            print("No available VM capacity.")
            return

    if VM_LOAD[vm_name] >= VM_CAPACITY[vm_name]:
        print(f"{vm_name} has reached maximum capacity.")
        return

    bucket_name = f"{tenant_name}-bucket"
    create_bucket(bucket_name, s3)

    tenant_info = {"vm": vm_name, "bucket": bucket_name}
    TENANT_REGISTRY[tenant_name] = tenant_info
    VM_LOAD[vm_name] += 1

    print(f"[+] Tenant '{tenant_name}' assigned to {vm_name} with bucket '{bucket_name}'.")

def remove_tenant(tenant_name):
    """Remove tenant and delete their bucket."""
    s3 = init_s3_client()
    tenant = TENANT_REGISTRY.get(tenant_name)
    if not tenant:
        print("Tenant not found.")
        return

    delete_bucket(tenant["bucket"], s3)
    VM_LOAD[tenant["vm"]] -= 1
    del TENANT_REGISTRY[tenant_name]
    print(f"[-] Tenant '{tenant_name}' removed.")

def show_tenants():
    """Show all tenants."""
    if not TENANT_REGISTRY:
        print("No tenants yet.")
        return
    print("\n=== Active Tenants ===")
    for t, info in TENANT_REGISTRY.items():
        print(f"{t} → {info['vm']} → {info['bucket']}")
    print("=======================")

def remove_all_tenants():
    """Remove all tenants and their buckets."""
    s3 = init_s3_client()
    for tenant in list(TENANT_REGISTRY.keys()):
        remove_tenant(tenant)
    print("All tenants removed.")
