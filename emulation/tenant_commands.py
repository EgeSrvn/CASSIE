import threading
import docker
from bucket_manager import create_user_bucket, delete_bucket, init_s3_client
from db_manager import get_connection

# Docker client (unused directly here, kept for future expansion)
client = docker.from_env()

# VM capacities and runtime loads
VM_CAPACITY = {"vm1": 16, "vm2": 8, "vm3": 4}
VM_LOAD = {"vm1": 0, "vm2": 0, "vm3": 0}

# Runtime registry: tenant_name -> {vm, bucket, user_id}
TENANT_REGISTRY = {}

# Lock to protect TENANT_REGISTRY and VM_LOAD
TENANT_LOCK = threading.Lock()


# --------------------------
# DB helpers
# --------------------------
def _get_user_row(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, bucket_name FROM users WHERE id = %s;", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row  # (username, bucket_name) or None


# --------------------------
# Tenant / bucket functions
# --------------------------
def find_available_vm():
    """Return first VM with available capacity (no locking)."""
    for vm, cap in VM_CAPACITY.items():
        if VM_LOAD[vm] < cap:
            return vm
    return None


def add_tenant_to_db(tenant_name, vm_name, user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tenants (name, vm_name, user_id)
        VALUES (%s, %s, %s)
    """, (tenant_name, vm_name, user_id))
    conn.commit()
    cur.close()
    conn.close()


def remove_tenant_from_db(tenant_name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tenants WHERE name = %s;", (tenant_name,))
    conn.commit()
    cur.close()
    conn.close()


def ensure_user_bucket(user_id):
    """
    Ensure user has a bucket. Returns bucket_name.
    If user's bucket_name is not set in DB, create it and update DB.
    """
    s3 = init_s3_client()
    row = _get_user_row(user_id)
    if not row:
        raise RuntimeError(f"user_id={user_id} not found in DB")
    username, bucket_name = row
    if bucket_name:
        return bucket_name

    # Create user bucket and update DB
    new_bucket = create_user_bucket(username, s3=s3)  # returns bucket_name
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET bucket_name = %s WHERE id = %s;", (new_bucket, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return new_bucket


def add_tenant(tenant_name, vm_name=None, user_id=None):
    """
    Add a tenant for a specific user, create their bucket, and assign a VM.
    Allows same tenant names for different users.
    """
    s3 = init_s3_client()

    # Check if tenant already exists for this user
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tenants WHERE name = %s AND user_id = %s;", (tenant_name, user_id))
    exists = cur.fetchone()
    if exists:
        print(f"[!] Tenant '{tenant_name}' already exists for your account.")
        cur.close()
        conn.close()
        return
    cur.close()
    conn.close()

    # Choose VM automatically if not given
    if not vm_name:
        vm_name = find_available_vm()
        if not vm_name:
            print("No available VM capacity.")
            return

    if VM_LOAD[vm_name] >= VM_CAPACITY[vm_name]:
        print(f"{vm_name} has reached maximum capacity.")
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE id = %s;", (user_id,))
    username = cur.fetchone()[0]
    cur.close()
    conn.close()

    bucket_name = create_user_bucket(username, s3)

    # Update runtime registry
    TENANT_REGISTRY[(tenant_name, user_id)] = {"vm": vm_name, "bucket": bucket_name}
    VM_LOAD[vm_name] += 1

    # Insert into database
    add_tenant_to_db(tenant_name, vm_name, user_id)

    print(f"[+] Tenant '{tenant_name}' for user_id={user_id} assigned to {vm_name} with bucket '{bucket_name}'.")



def remove_tenant(tenant_name, user_id):
    """
    Remove a tenant for a specific user: delete bucket and DB entry.
    """
    s3 = init_s3_client()
    key = (tenant_name, user_id)
    tenant = TENANT_REGISTRY.get(key)
    if not tenant:
        print(f"[!] Tenant '{tenant_name}' not found for your account.")
        return

    # Delete bucket
    delete_bucket(tenant["bucket"], s3)

    # Decrease VM load
    VM_LOAD[tenant["vm"]] -= 1

    # Remove from runtime registry
    del TENANT_REGISTRY[key]

    # Remove from database
    remove_tenant_from_db(tenant_name, user_id)

    print(f"[-] Tenant '{tenant_name}' for user_id={user_id} removed successfully.")


def remove_tenant_from_db(tenant_name, user_id):
    """Remove a tenant entry for a specific user from the database."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM tenants WHERE name = %s AND user_id = %s;",
        (tenant_name, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    print(f"[DB] Tenant '{tenant_name}' for user_id={user_id} removed from database.")


def show_user_tenants(user_id):
    """
    Return a list of tenants for the given user from runtime.
    Each item is a tuple: (tenant_name, vm_name, bucket_name)
    """
    result = []
    for key, tenant_info in TENANT_REGISTRY.items():
        # Ensure key is a tuple of length 2
        if isinstance(key, tuple) and len(key) == 2:
            tenant_name, uid = key
            if uid == user_id:
                result.append((tenant_name, tenant_info["vm"], tenant_info["bucket"]))
        else:
            print(f"[!] Unexpected key in TENANT_REGISTRY: {key}")
    return result

def remove_all_user_tenants(user_id):
    """Delete all tenants for a user."""
    tenants = show_user_tenants(user_id)  # returns list of (tenant_name, vm_name, bucket)
    for tenant_name, _, _ in tenants:     # unpack 3 values
        remove_tenant(tenant_name, user_id)
    return {"user_id": user_id, "removed": len(tenants)}