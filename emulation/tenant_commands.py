from .bucket_manager import create_user_bucket, delete_bucket, init_s3_client
from .db_manager import get_connection
from .docker_commands import (
    client,
    create_tenant_user, 
    assign_tenant_to_vm,
    divide_resources_for_tenant,
    remove_tenant_container,
    get_tenant_container,
)
import docker
import threading
import time
import os

# VM capacities and runtime loads
VM_CAPACITY = {"vm1": 16, "vm2": 8, "vm3": 4}
VM_LOAD = {"vm1": 0, "vm2": 0, "vm3": 0}

# Runtime registry: tenant_name -> {vm, bucket, container}
TENANT_REGISTRY = {}

# Lock to protect TENANT_REGISTRY and VM_LOAD
TENANT_LOCK = threading.Lock()


# --------------------------
# DB helpers
# --------------------------
def _get_user_row(user_id):
    """Retrieve a user's row from the database.

    Args:
        user_id (int): Database user id.

    Returns:
        tuple|None: (username, bucket_name) if the user exists, otherwise None.

    Notes:
        Closes the DB connection before returning.
    """
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
    """Return the first VM that currently has free capacity.

    This is a best-effort check and does not acquire any locks.

    Returns:
        str|None: VM name with available capacity, or None if none available.
    """
    for vm, cap in VM_CAPACITY.items():
        if VM_LOAD.get(vm, 0) < cap:
            return vm
    return None


def add_tenant_to_db(tenant_name, vm_name, user_id):
    """Insert a tenant record into the tenants database table.

    Args:
        tenant_name (str): Logical tenant name.
        vm_name (str): Assigned VM name.
        user_id (int): Owner user's id.

    Returns:
        None
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tenants (name, vm_name, user_id)
        VALUES (%s, %s, %s)
    """, (tenant_name, vm_name, user_id))
    conn.commit()
    cur.close()
    conn.close()


def ensure_user_bucket(user_id):
    """Ensure a user has an S3 bucket and return its name.

    If the user's bucket is not recorded in the DB this will create a new
    bucket via bucket_manager.create_user_bucket and update the DB.

    Args:
        user_id (int): Database user id.

    Returns:
        str: Bucket name for the user.

    Raises:
        RuntimeError: If the user_id is not found in the database.
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


# helper: stable container name for a tenant
def tenant_container_name(tenant_name, user_id):
    """Return the canonical tenant container name.

    Args:
        tenant_name (str): Tenant logical name.
        user_id (int|None): Optional user id to scope the tenant.

    Returns:
        str: Container name in form 'tenant_<name>_<user_id>' or 'tenant_<name>'.
    """
    return f"tenant_{tenant_name}_{user_id}" if user_id is not None else f"tenant_{tenant_name}"


def add_tenant(tenant_name, vm_name=None, user_id=None):
    """Create a tenant for a user: bucket, container and DB entry.

    Workflow:
      - verify tenant does not already exist for the user,
      - assign or use provided VM (persisted via assign_tenant_to_vm),
      - ensure capacity on the VM,
      - create or ensure user's S3 bucket,
      - compute per-tenant resource hints,
      - create tenant container and OS user,
      - update runtime registry and DB.

    Args:
        tenant_name (str): Logical tenant name.
        vm_name (str|None): Optional preferred VM name.
        user_id (int): Owner user's id.

    Returns:
        None

    Notes:
        Best-effort: failures in container creation do not roll back bucket or DB changes.
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

    # Choose/assign VM (persist mapping)
    if not vm_name:
        vm_name = assign_tenant_to_vm(tenant_name, user_id)

    # Capacity check (best-effort)
    if VM_LOAD.get(vm_name, 0) >= VM_CAPACITY.get(vm_name, 0):
        print(f"[!] {vm_name} has reached maximum capacity.")
        return

    # Ensure user exists and create bucket
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE id = %s;", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        print(f"[!] user_id={user_id} not found.")
        return
    username = row[0]

    bucket_name = create_user_bucket(username, s3)

    # compute resource hints for tenant inside vm
    try:
        cpu_quota, mem_limit = divide_resources_for_tenant(vm_name)
    except Exception:
        cpu_quota, mem_limit = None, None

    # Update runtime registry
    key = (tenant_name, user_id)
    TENANT_REGISTRY[key] = {"vm": vm_name, "bucket": bucket_name}
    VM_LOAD[vm_name] = VM_LOAD.get(vm_name, 0) + 1

    # Create tenant container + user inside assigned VM (best-effort)
    try:
        cont = create_tenant_user(vm_name, tenant_name, user_id, cpu_quota=cpu_quota, mem_limit=mem_limit)
        TENANT_REGISTRY[key]["container"] = cont.name
    except Exception as e:
        print(f"[!] Warning: failed to create tenant container/user: {e}")
        TENANT_REGISTRY.pop(key, None)
        VM_LOAD[vm_name] = max(0, VM_LOAD.get(vm_name, 1) - 1)
        raise

    # Insert into database
    add_tenant_to_db(tenant_name, vm_name, user_id)

    print(f"[+] Tenant '{tenant_name}' for user_id={user_id} assigned to {vm_name} with bucket '{bucket_name}'.")
    
    # Write progress to VM container logs for Docker Desktop visibility
    try:
        from .docker_commands import client
        vm_container = client.containers.get(vm_name)
        vm_container.exec_run(
            ["/bin/sh", "-c", f"echo '[TENANT] Tenant {tenant_name} assigned to {vm_name}, bucket: {bucket_name}' > /proc/1/fd/1"],
            user="root"
        )
    except:
        pass  # Non-critical


def remove_tenant(tenant_name, user_id):
    """Remove a tenant: container, runtime registry and DB entry.

    Performs best-effort cleanup:
      - attempts to remove the tenant container via helper or directly,
      - decrements VM load and removes runtime registry entry,
      - deletes the tenant row from the DB.
    """
    s3 = init_s3_client()
    key = (tenant_name, user_id)
    tenant = TENANT_REGISTRY.get(key)
    if not tenant:
        print(f"[!] Tenant '{tenant_name}' not found for your account.")
        return

    # Attempt to remove the tenant container (best-effort) using docker_commands helper
    try:
        removed = remove_tenant_container(tenant_name, user_id, force=True)
        if not removed:
            # fallback: try direct client removal if helper returned False
            container_name = tenant.get("container") or tenant_container_name(tenant_name, user_id)
            try:
                cont = client.containers.get(container_name)
                cont.remove(force=True)
            except docker.errors.NotFound:
                pass
    except Exception as e:
        print(f"[!] Failed to remove container via helper: {e}")

    # NOTE: We no longer delete the shared S3 bucket here.

    # Decrease VM load
    vm = tenant.get("vm")
    if vm in VM_LOAD:
        VM_LOAD[vm] = max(0, VM_LOAD[vm] - 1)

    # Remove from runtime registry
    del TENANT_REGISTRY[key]

    # Remove from database
    remove_tenant_from_db(tenant_name, user_id)

    print(f"[-] Tenant '{tenant_name}' for user_id={user_id} removed successfully.")


def remove_tenant_from_db(tenant_name, user_id):
    """Delete a tenant row from the database for a given user.

    Args:
        tenant_name (str): Tenant logical name.
        user_id (int): Owner user's id.

    Returns:
        None
    """
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
    """Return runtime tenant list for a user.

    Iterates the in-memory TENANT_REGISTRY and returns entries for the
    specified user.

    Args:
        user_id (int): Owner user's id.

    Returns:
        list of tuple: Each item is (tenant_name, vm_name, bucket_name, container_name).
    """
    result = []
    for key, tenant_info in TENANT_REGISTRY.items():
        # Ensure key is a tuple of length 2
        if isinstance(key, tuple) and len(key) == 2:
            tenant_name, uid = key
            if uid == user_id:
                container_name = tenant_info.get("container") or tenant_container_name(tenant_name, uid)
                result.append((tenant_name, tenant_info["vm"], tenant_info["bucket"], container_name))
        else:
            print(f"[!] Unexpected key in TENANT_REGISTRY: {key}")
    return result


def remove_all_user_tenants(user_id):
    """Remove all tenants for a given user.

    Calls remove_tenant for each tenant found via show_user_tenants.

    Args:
        user_id (int): Owner user's id.

    Returns:
        dict: Summary with keys 'user_id' and 'removed' count.
    """
    tenants = show_user_tenants(user_id)  # returns list of (tenant_name, vm_name, bucket, container)
    removed = 0
    for tenant_name, _, _, _ in tenants:
        remove_tenant(tenant_name, user_id)
        removed += 1
    return {"user_id": user_id, "removed": removed}


def open_tenant_terminal(tenant_name, user_id):
    """Open an interactive shell inside a tenant container and return a socket.

    Attempts to start the tenant container if needed, verifies the tenant OS
    user exists and falls back to root if not. Uses the docker API to create
    and start an exec instance and returns the socket for interactive use.

    Args:
        tenant_name (str): Tenant logical name.
        user_id (int): Owner user's id.

    Returns:
        socket|str: A docker socket-like object for the exec session on success,
                    or an error message string on failure.
    """
    container_name = tenant_container_name(tenant_name, user_id)
    username = container_name
    home_dir = f"/home/{container_name}"

    try:
        container = get_tenant_container(tenant_name, user_id)
        container.reload()
        if container.status != "running":
            container.start()
            time.sleep(5)  # wait a bit for the container to be fully up"
    except docker.errors.NotFound:
        return f"[!] Tenant container '{container_name}' not found."

    # Verify tenant user exists
    try:
        res = container.exec_run(f"id -u {username}", user="root")
        if res.exit_code != 0:
            print(f"[!] User '{username}' not found in container. Falling back to root.")
            username = "root"
            home_dir = "/root"
    except Exception:
        username = "root"
        home_dir = "/root"

    cmd = f"bash -c 'if [ -f {home_dir}/.bashrc ]; then source {home_dir}/.bashrc; fi; exec bash'"

    # Retry exec_create + exec_start in case of transient 404 (common on Windows Docker)
    # Retry exec_create + exec_start to avoid transient 404 errors
    for attempt in range(3):
        try:
            exec_id = client.api.exec_create(
                container.id,
                cmd,
                tty=True,
                stdin=True,
                stdout=True,
                stderr=True,
                workdir=home_dir,
                user=username,
            )["Id"]
            sock = client.api.exec_start(exec_id, tty=True, socket=True)
            break
        except docker.errors.NotFound:
            time.sleep(0.2)
    else:
        return f"[!] Failed to start tenant shell for container '{container_name}'."

    return sock
