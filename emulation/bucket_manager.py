import boto3
import docker
import os
import time
import tkinter as tk
from tkinter import filedialog
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError, ConnectionClosedError
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
        # Give MinIO time to initialize (it needs a few seconds after starting)
        time.sleep(5)

    print("[✓] MinIO container is running at http://minio:9000")
    # Note: Actual readiness will be tested by init_s3_client() with retry logic


# -------------------------------------------------------------------
# 🔹 Initialize S3 client
# -------------------------------------------------------------------
def init_s3_client(endpoint_url=None):
    """
    Initialize and return an S3 client compatible with MinIO.
    Includes retry logic and proper connection configuration.
    
    Tries endpoints in order:
    1. 'http://minio:9000' (Docker network DNS - for code running inside Docker)
    2. 'http://localhost:9000' (host port mapping - for code running on host)
    
    Args:
        endpoint_url (str, optional): Override endpoint URL. If None, tries both endpoints.

    Returns:
        boto3.client: A configured S3 client for interacting with MinIO.
    
    Raises:
        RuntimeError: If unable to connect to MinIO after trying all endpoints.
    """
    ensure_minio_container()
    
    # Configure boto3 with retry and timeout settings (same as backend)
    config = Config(
        signature_version='s3v4',
        retries={'max_attempts': 2, 'mode': 'standard'},  # Reduced retries since we try multiple endpoints
        connect_timeout=5,
        read_timeout=5,
        max_pool_connections=10
    )
    
    # Try endpoints in order if not explicitly provided
    endpoints_to_try = []
    if endpoint_url:
        endpoints_to_try = [endpoint_url]
    else:
        # Determine which endpoints to try based on environment
        # If running on host (backend), try localhost first
        # If running in Docker, try minio DNS first
        if os.path.exists('/.dockerenv'):
            # Running inside Docker - try Docker network DNS first
            endpoints_to_try = ['http://minio:9000', 'http://localhost:9000']
        else:
            # Running on host - try host port mapping first
            endpoints_to_try = ['http://localhost:9000', 'http://127.0.0.1:9000']
    
    last_error = None
    
    for endpoint_url in endpoints_to_try:
        client_kwargs = {
            'service_name': 's3',
            'endpoint_url': endpoint_url,
            'aws_access_key_id': 'minioadmin',
            'aws_secret_access_key': 'minioadmin',
            'region_name': 'us-east-1',  # MinIO doesn't care about region, but boto3 requires it
            'config': config,
        }
        
        # Try to connect with this endpoint
        try:
            client = boto3.client(**client_kwargs)
            # Test connection with a simple operation
            client.list_buckets()
            print(f"[✓] Connected to MinIO at {endpoint_url}")
            return client
        except (ClientError, BotoCoreError, ConnectionClosedError, Exception) as e:
            last_error = e
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[*] Failed to connect to MinIO at {endpoint_url}: {error_type}: {error_msg}")
            # Continue to next endpoint
            continue
    
    # If we get here, all endpoints failed
    raise RuntimeError(
        f"Unable to connect to MinIO after trying endpoints: {', '.join(endpoints_to_try)}. "
        f"Last error: {type(last_error).__name__}: {str(last_error)}. "
        f"Ensure MinIO container is running and accessible."
    ) from last_error


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
