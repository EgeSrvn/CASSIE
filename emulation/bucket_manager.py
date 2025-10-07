import boto3
import tkinter as tk
from tkinter import filedialog
import os

import docker
import boto3

def ensure_minio_container():
    """Ensure a MinIO Docker container is running locally."""
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
            "server /data",
            name=container_name,
            detach=True,
            tty=True,
            ports={"9000/tcp": 9000, "9001/tcp": 9001},  # Console port
            environment={
                "MINIO_ROOT_USER": "minioadmin",
                "MINIO_ROOT_PASSWORD": "minioadmin",
            },
            volumes={"minio_data": {"bind": "/data", "mode": "rw"}}
        )
        print("[+] MinIO container started.")


def init_s3_client():
    """Initialize and return an S3 client."""
    ensure_minio_container()
    return boto3.client(
        's3',
        endpoint_url='http://localhost:9000',   # MinIO API
        aws_access_key_id='minioadmin',
        aws_secret_access_key='minioadmin',
    )

def create_bucket(bucket_name, s3=None):
    """Create a new S3 bucket."""
    s3.create_bucket(Bucket=bucket_name)
    print(f"Bucket '{bucket_name}' created!")

def delete_bucket(bucket_name, s3=None):
    """Delete an existing S3 bucket after emptying it."""
    # List and delete all objects in the bucket
    objects = s3.list_objects_v2(Bucket=bucket_name)
    if 'Contents' in objects:
        for obj in objects['Contents']:
            s3.delete_object(Bucket=bucket_name, Key=obj['Key'])
    s3.delete_bucket(Bucket=bucket_name)
    print(f"Bucket '{bucket_name}' emptied and deleted!")

def delete_all_buckets(s3=None):
    """Delete all S3 buckets after emptying them."""
    response = s3.list_buckets()
    buckets = response.get('Buckets', [])
    for bucket in buckets:
        delete_bucket(bucket['Name'], s3=s3)
    if not buckets:
        print("No buckets to delete.")

def auto_create_bucket(s3=None):
    """Automatically create a bucket with a timestamped name."""
    import time
    bucket_name = f"bucket-{int(time.time())}"
    create_bucket(bucket_name, s3=s3)
    return bucket_name

def list_buckets(s3=None):
    """List all S3 buckets."""
    response = s3.list_buckets()
    buckets = response.get('Buckets', [])
    if not buckets:
        print("No buckets found.")
        return
    print("\n=== Buckets ===")
    for bucket in buckets:
        print(bucket['Name'])
    print("===============\n")

def open_file_selector():
    """Open a file selector dialog and return the selected file path."""
    root = tk.Tk()
    root.withdraw()  # Hide the root window
    file_path = filedialog.askopenfilename()
    return file_path

def upload_file(bucket_name, file_path, s3=None):
    """Upload a file to a specified S3 bucket."""
    if not os.path.isfile(file_path):
        print(f"File '{file_path}' does not exist.")
        return
    file_name = os.path.basename(file_path)
    s3.upload_file(file_path, bucket_name, file_name)
    print(f"File '{file_name}' uploaded to bucket '{bucket_name}'.")

