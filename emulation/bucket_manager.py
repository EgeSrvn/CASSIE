import boto3
import docker
import os
import time
import tkinter as tk
from tkinter import filedialog

# -------------------------------------------------------------------
# 🔹 Ensure MinIO container is running (AWS-compatible local S3)
# -------------------------------------------------------------------
def ensure_minio_container():
    """
    Ensure a MinIO Docker container is running locally.

    If the container is not running, it will start an existing container
    or create and start a new one. The container is configured to run
    MinIO with default credentials and ports.
    """
    client = docker.from_env()
    container_name = "minio"
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            print("[*] Starting existing MinIO container...")
            container.start()
        else:
            print("[*] MinIO container already running.")
    except docker.errors.NotFound:
        print("[*] MinIO container not found. Creating a new one...")
        client.containers.run(
            "minio/minio:latest",
            "server /data --console-address :9001",
            name=container_name,
            detach=True,
            tty=True,
            ports={"9000/tcp": 9000, "9001/tcp": 9001},  # API + console
            environment={
                "MINIO_ROOT_USER": "minioadmin",
                "MINIO_ROOT_PASSWORD": "minioadmin",
            },
            volumes={"minio_data": {"bind": "/data", "mode": "rw"}}
        )
        print("[+] MinIO container started.")
        time.sleep(6)  # Give it a few seconds to initialize


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
    Create a unique S3 bucket for a user.

    Args:
        username (str): The username for whom the bucket is created.
        s3 (boto3.client, optional): An existing S3 client. Defaults to None.

    Returns:
        str: The name of the created or existing bucket.
    """
    s3 = s3 or init_s3_client()
    bucket_name = f"user-{username.lower()}-bucket"
    existing = s3.list_buckets().get("Buckets", [])
    if any(b["Name"] == bucket_name for b in existing):
        print(f"[*] Bucket '{bucket_name}' already exists for user '{username}'.")
        return bucket_name

    s3.create_bucket(Bucket=bucket_name)
    print(f"[+] Created bucket '{bucket_name}' for user '{username}'.")
    return bucket_name


def delete_user_bucket(username, s3=None):
    """
    Delete a user's S3 bucket and its contents.

    Args:
        username (str): The username whose bucket is to be deleted.
        s3 (boto3.client, optional): An existing S3 client. Defaults to None.
    """
    s3 = s3 or init_s3_client()
    bucket_name = f"user-{username.lower()}-bucket"
    try:
        objects = s3.list_objects_v2(Bucket=bucket_name)
        if 'Contents' in objects:
            for obj in objects['Contents']:
                s3.delete_object(Bucket=bucket_name, Key=obj['Key'])
        s3.delete_bucket(Bucket=bucket_name)
        print(f"[-] Deleted bucket '{bucket_name}' for user '{username}'.")
    except Exception as e:
        print(f"[!] Failed to delete bucket '{bucket_name}': {e}")


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


def upload_file(username, file_path, s3=None):
    """
    Upload a file to a user's S3 bucket.

    Args:
        username (str): The username whose bucket the file will be uploaded to.
        file_path (str): The local path of the file to upload.
        s3 (boto3.client, optional): An existing S3 client. Defaults to None.
    """
    s3 = s3 or init_s3_client()
    bucket_name = f"user-{username.lower()}-bucket"
    if not os.path.isfile(file_path):
        print(f"[!] File '{file_path}' does not exist.")
        return
    file_name = os.path.basename(file_path)
    s3.upload_file(file_path, bucket_name, file_name)
    print(f"[+] Uploaded '{file_name}' to bucket '{bucket_name}'.")


def list_user_bucket(username, s3=None):
    """
    List all files in a user's S3 bucket.

    Args:
        username (str): The username whose bucket contents will be listed.
        s3 (boto3.client, optional): An existing S3 client. Defaults to None.
    """
    s3 = s3 or init_s3_client()
    bucket_name = f"user-{username.lower()}-bucket"
    try:
        response = s3.list_objects_v2(Bucket=bucket_name)
        contents = response.get("Contents", [])
        if not contents:
            print(f"[~] Bucket '{bucket_name}' is empty.")
            return
        print(f"\n=== Files in '{bucket_name}' ===")
        for obj in contents:
            print(obj["Key"])
        print("===============================")
    except Exception as e:
        print(f"[!] Cannot list bucket '{bucket_name}': {e}")
