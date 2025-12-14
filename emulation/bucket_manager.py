import boto3
import docker
import os
import time
import tkinter as tk
from tkinter import filedialog
# -------------------------------------------------------------------
# 🔹 Global shared bucket
# -------------------------------------------------------------------
GLOBAL_BUCKET_NAME = "cassie-bucket"  # <- pick any name you like


def ensure_global_bucket(s3=None):
    """
    Ensure that the single shared S3 bucket exists and return its name.

    Args:
        s3 (boto3.client, optional): Existing S3 client. Defaults to None.

    Returns:
        str: Name of the shared bucket.
    """
    s3 = s3 or init_s3_client()
    existing = s3.list_buckets().get("Buckets", [])
    if any(b["Name"] == GLOBAL_BUCKET_NAME for b in existing):
        return GLOBAL_BUCKET_NAME

    s3.create_bucket(Bucket=GLOBAL_BUCKET_NAME)
    print(f"[+] Created global bucket '{GLOBAL_BUCKET_NAME}'.")
    return GLOBAL_BUCKET_NAME

# -------------------------------------------------------------------
# 🔹 Ensure MinIO container is running (AWS-compatible local S3)
# -------------------------------------------------------------------
def ensure_minio_container():
    """
    Ensure a MinIO Docker container is running AND attached to workflow-net
    with DNS name 'minio' so VMs/tenants can reach http://minio:9000.
    """
    client = docker.from_env()
    container_name = "minio"
    network_name = "workflow-net"

    # Ensure network exists
    try:
        client.networks.get(network_name)
    except docker.errors.NotFound:
        client.networks.create(network_name)

    try:
        container = client.containers.get(container_name)
        container.reload()
        print(f"[*] MinIO container '{container_name}' exists (status: {container.status}).")
    except docker.errors.NotFound:
        print("[*] MinIO container not found. Creating a new one...")
        container = client.containers.run(
            "minio/minio:latest",
            "server /data --console-address :9001",
            name=container_name,
            detach=True,
            tty=True,
            network=network_name,             # ✅ attach at creation
            environment={
                "MINIO_ROOT_USER": "minioadmin",
                "MINIO_ROOT_PASSWORD": "minioadmin",
            },
            ports={"9000/tcp": 9000, "9001/tcp": 9001},
            volumes={"minio_data": {"bind": "/data", "mode": "rw"}},
        )
        time.sleep(5)

    # Ensure attached to workflow-net with alias 'minio'
    container.reload()
    networks = container.attrs.get("NetworkSettings", {}).get("Networks", {}) or {}
    if network_name not in networks:
        print(f"[+] Connecting MinIO to '{network_name}' with alias 'minio'...")
        net = client.networks.get(network_name)
        net.connect(container, aliases=["minio"])

    # Ensure running
    container.reload()
    if container.status != "running":
        print("[+] Starting MinIO container...")
        container.start()
        time.sleep(3)

    print("[✓] MinIO ready at http://minio:9000")


# -------------------------------------------------------------------
# 🔹 Initialize S3 client
# -------------------------------------------------------------------
def init_s3_client():
    """
    Initialize and return an S3 client compatible with MinIO.

    Returns:
        boto3.client: A configured S3 client for interacting with MinIO.
    """
    ensure_minio_container()
    return boto3.client(
        's3',
        endpoint_url='http://localhost:9000',  # Local MinIO endpoint
        aws_access_key_id='minioadmin',
        aws_secret_access_key='minioadmin',
    )


def create_user_bucket(username, s3=None):
    """
    Return the single shared S3 bucket used by all users.

    The username argument is kept for backward compatibility but is
    ignored in the current design.
    """
    s3 = s3 or init_s3_client()
    return ensure_global_bucket(s3)

def delete_user_bucket(username, s3=None):
    """
    Legacy helper when buckets were per-user.

    With the global bucket design we do not delete the shared bucket
    here to avoid affecting other users. This function is now a no-op.
    """
    s3 = s3 or init_s3_client()
    ensure_global_bucket(s3)
    print("[*] delete_user_bucket() is a no-op with the global bucket design.")



def delete_all_buckets(s3=None):
    """
    Delete all S3 buckets (admin-only operation).

    Args:
        s3 (boto3.client, optional): An existing S3 client. Defaults to None.
    """
    s3 = s3 or init_s3_client()
    response = s3.list_buckets()
    for bucket in response.get("Buckets", []):
        delete_bucket(bucket["Name"], s3)
    print("[*] All buckets deleted.")


def delete_bucket(bucket_name, s3=None):
    """
    Delete a specific S3 bucket and its contents.

    Args:
        bucket_name (str): The name of the bucket to delete.
        s3 (boto3.client, optional): An existing S3 client. Defaults to None.
    """
    s3 = s3 or init_s3_client()
    try:
        objects = s3.list_objects_v2(Bucket=bucket_name)
        if 'Contents' in objects:
            for obj in objects['Contents']:
                s3.delete_object(Bucket=bucket_name, Key=obj['Key'])
        s3.delete_bucket(Bucket=bucket_name)
        print(f"[-] Bucket '{bucket_name}' deleted.")
    except Exception as e:
        print(f"[!] Error deleting bucket '{bucket_name}': {e}")


# -------------------------------------------------------------------
# 🔹 File Operations (Upload, List, etc.)
# -------------------------------------------------------------------
def open_file_selector():
    """
    Open a file selector dialog and return the selected file path.

    Returns:
        str: The path of the selected file.
    """
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename()

def list_user_bucket(username, s3=None):
    """
    List all files for a user inside the shared S3 bucket.

    Args:
        username (str): The username whose files will be listed.
        s3 (boto3.client, optional): An existing S3 client. Defaults to None.
    """
    s3 = s3 or init_s3_client()
    bucket_name = ensure_global_bucket(s3)
    prefix = f"{username}/"

    try:
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        contents = response.get("Contents", [])
        if not contents:
            print(f"[~] No objects found for user '{username}' in bucket '{bucket_name}'.")
            return

        print(f"\n=== Files for '{username}' in bucket '{bucket_name}' ===")
        for obj in contents:
            key = obj["Key"]
            # Strip username/ prefix for nicer printing
            display_name = key[len(prefix):] if key.startswith(prefix) else key
            print(display_name)
        print("===============================================")
    except Exception as e:
        print(f"[!] Cannot list objects for user '{username}': {e}")

import os
import time

def upload_bytes(username: str, filename: str, data: bytes, s3=None, prefix: str = "uploads", user_id=None):
    """
    Upload raw bytes to the shared S3 bucket.

    Stores objects under:
      uploads/<user_id>_<timestamp>_<filename>
    or if user_id is None:
      uploads/<username>_<timestamp>_<filename>
    """
    s3 = s3 or init_s3_client()
    bucket_name = ensure_global_bucket(s3)

    safe_name = os.path.basename(filename)
    uid = str(user_id) if user_id is not None else username

    key = f"{prefix}/{uid}_{int(time.time())}_{safe_name}"

    s3.put_object(Bucket=bucket_name, Key=key, Body=data)
    print(f"[+] Uploaded '{key}' to bucket '{bucket_name}'.")
    return bucket_name, key
