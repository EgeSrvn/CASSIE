"""
MinIO/S3 client service for CASSIE backend.

This module provides a service for interacting with MinIO (local S3-compatible storage)
or AWS S3. It supports file operations in a shared bucket with per-user object prefixes.

Usage:
    from backend.api.services.minio_client import MinIOClient
    
    client = MinIOClient()
    client.ensure_user_bucket(user_id=1, username="testuser")
    client.upload_file(user_id=1, local_path="/path/to/file.fastq", s3_key="data/file.fastq")
"""

import boto3
import os
import hashlib
import time
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, urlunparse
from botocore.exceptions import ClientError, BotoCoreError
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

S3_CONNECT_TIMEOUT_SECONDS = int(os.getenv("S3_CONNECT_TIMEOUT_SECONDS", "20"))
S3_READ_TIMEOUT_SECONDS = int(os.getenv("S3_READ_TIMEOUT_SECONDS", "300"))
S3_RETRY_ATTEMPTS = int(os.getenv("S3_RETRY_ATTEMPTS", "8"))
S3_UPLOAD_VERIFY_TIMEOUT_SECONDS = float(os.getenv("S3_UPLOAD_VERIFY_TIMEOUT_SECONDS", "30"))
S3_UPLOAD_VERIFY_INTERVAL_SECONDS = float(os.getenv("S3_UPLOAD_VERIFY_INTERVAL_SECONDS", "0.5"))
S3_MULTIPART_THRESHOLD_BYTES = int(os.getenv("S3_MULTIPART_THRESHOLD_BYTES", str(64 * 1024 * 1024)))
S3_MULTIPART_CHUNK_BYTES = int(os.getenv("S3_MULTIPART_CHUNK_BYTES", str(64 * 1024 * 1024)))


class MinIOClient:
    """
    MinIO/S3 client service for file storage operations.
    
    Supports both MinIO (local) and AWS S3 (production) through configuration.
    Uses one shared bucket and scopes each user's objects under a dedicated prefix.
    """
    
    def __init__(self, s3_client: Optional[Any] = None):
        """
        Initialize MinIO/S3 client.
        
        Args:
            s3_client: Optional boto3 S3 client (for testing). If None, creates a new client.
        """
        self._s3_client = s3_client
        self._config = get_config()
        self._logger = get_logger(__name__)
        self._cors_checked_buckets = set()
    
    @property
    def s3_client(self):
        """Get or create S3 client."""
        if self._s3_client is None:
            self._s3_client = self._create_s3_client()
        return self._s3_client
    
    def _create_s3_client(self):
        """
        Create and configure boto3 S3 client.
        
        Returns:
            boto3.client: Configured S3 client
        """
        minio_config = self._config.minio
        
        config = Config(
            signature_version='s3v4',
            retries={'max_attempts': S3_RETRY_ATTEMPTS, 'mode': 'adaptive'},
            connect_timeout=S3_CONNECT_TIMEOUT_SECONDS,
            read_timeout=S3_READ_TIMEOUT_SECONDS,
            max_pool_connections=25
        )
        
        client_kwargs = {
            'service_name': 's3',
            'region_name': minio_config.region,
            'config': config,
        }

        if minio_config.access_key and minio_config.secret_key:
            client_kwargs['aws_access_key_id'] = minio_config.access_key
            client_kwargs['aws_secret_access_key'] = minio_config.secret_key
        
        # Any configured endpoint is treated as an S3-compatible custom endpoint
        # (MinIO locally, MinIO in Docker Compose, or a remote S3-compatible store).
        if minio_config.endpoint:
            client_kwargs['endpoint_url'] = minio_config.endpoint
            self._logger.info(f"Initializing S3 client with custom endpoint: {minio_config.endpoint}")
        else:
            # AWS S3 (no endpoint_url)
            self._logger.info("Initializing AWS S3 client")
        
        # Retry connection with exponential backoff
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                client = boto3.client(**client_kwargs)
                client.list_buckets()
                self._logger.info("S3 client initialized successfully")
                return client
            except Exception as e:
                # Catch all exceptions (ClientError, BotoCoreError, ConnectionError, etc.)
                error_type = type(e).__name__
                error_msg = str(e)
                
                if attempt < max_retries - 1:
                    self._logger.warning(
                        f"Failed to connect to S3/MinIO (attempt {attempt + 1}/{max_retries}): {error_type}: {error_msg}. "
                        f"Retrying in {retry_delay} seconds..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    self._logger.error(f"Failed to initialize S3 client after {max_retries} attempts: {error_type}: {error_msg}")
                    raise RuntimeError(f"Failed to connect to S3/MinIO after {max_retries} attempts: {error_msg}")
    
    def _get_bucket_name(self, user_id: int, username: Optional[str] = None) -> str:
        """
        Resolve the shared storage bucket name.
        
        Args:
            user_id: User ID (unused, kept for backward compatibility)
            username: Optional username (unused, kept for backward compatibility)
        
        Returns:
            str: Shared bucket name
        """
        return self._config.minio.bucket_prefix.rstrip('-')

    def _get_legacy_bucket_name(self, user_id: int, username: Optional[str] = None) -> str:
        """Return the pre-migration per-user bucket name for compatibility reads."""
        prefix = self._config.minio.bucket_prefix.rstrip('-')
        return f"{prefix}-user-{user_id}"

    def _normalize_s3_key(self, s3_key: str) -> str:
        """Normalize logical object keys stored in the database."""
        return str(s3_key or "").lstrip("/")

    def _get_user_prefix(self, user_id: int) -> str:
        """Return the per-user prefix inside the shared bucket."""
        return f"users/{user_id}"

    def _get_object_key(self, user_id: int, s3_key: str) -> str:
        """Map a logical key to the physical key stored in the shared bucket."""
        logical_key = self._normalize_s3_key(s3_key)
        user_prefix = self._get_user_prefix(user_id)
        return f"{user_prefix}/{logical_key}" if logical_key else f"{user_prefix}/"

    def _strip_user_prefix(self, user_id: int, object_key: str) -> str:
        """Convert a physical shared-bucket key back to the logical DB key."""
        user_prefix = f"{self._get_user_prefix(user_id)}/"
        if object_key.startswith(user_prefix):
            return object_key[len(user_prefix):]
        return object_key

    def _get_primary_storage_location(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None,
    ) -> tuple[str, str]:
        """Return the shared-bucket location for a logical object key."""
        return self._get_bucket_name(user_id, username), self._get_object_key(user_id, s3_key)

    def _get_read_locations(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None,
    ) -> List[tuple[str, str]]:
        """
        Return possible storage locations for a logical object key.

        The first entry is always the new shared-bucket layout. A legacy per-user
        bucket location is included as a fallback so existing data remains readable
        after the storage migration.
        """
        logical_key = self._normalize_s3_key(s3_key)
        primary_location = self._get_primary_storage_location(user_id, logical_key, username)
        legacy_location = (self._get_legacy_bucket_name(user_id, username), logical_key)

        locations: List[tuple[str, str]] = []
        for location in (primary_location, legacy_location):
            if location not in locations:
                locations.append(location)
        return locations

    def get_read_locations(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Expose candidate storage locations for callers outside this client."""
        return [
            {"bucket": bucket_name, "key": object_key}
            for bucket_name, object_key in self._get_read_locations(user_id, s3_key, username)
        ]

    def _head_object(self, bucket_name: str, object_key: str) -> Optional[Dict[str, Any]]:
        """Return object metadata if the object exists, otherwise None."""
        try:
            return self.s3_client.head_object(Bucket=bucket_name, Key=object_key)
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in {'404', 'NoSuchKey', 'NoSuchBucket', 'NotFound'}:
                return None
            raise

    def _resolve_existing_location(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None,
    ) -> Optional[tuple[str, str]]:
        """Find the first existing physical location for a logical key."""
        for bucket_name, object_key in self._get_read_locations(user_id, s3_key, username):
            if self._head_object(bucket_name, object_key):
                return bucket_name, object_key
        return None

    def _wait_for_uploaded_object(
        self,
        bucket_name: str,
        object_key: str,
        expected_size: int,
        timeout_seconds: float = S3_UPLOAD_VERIFY_TIMEOUT_SECONDS,
    ) -> Dict[str, Any]:
        """Wait until object storage confirms the uploaded object exists."""
        deadline = time.monotonic() + timeout_seconds
        last_error: Optional[Exception] = None

        while True:
            try:
                head = self.s3_client.head_object(Bucket=bucket_name, Key=object_key)
                content_length = int(head.get("ContentLength", -1))
                if content_length == expected_size:
                    return head
                last_error = RuntimeError(
                    f"object size mismatch: expected {expected_size} bytes, got {content_length} bytes"
                )
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code not in {'404', 'NoSuchKey', 'NoSuchBucket', 'NotFound'}:
                    raise
                last_error = e

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Storage did not confirm object '{object_key}' in bucket '{bucket_name}' "
                    f"within {timeout_seconds:.0f}s"
                ) from last_error

            time.sleep(S3_UPLOAD_VERIFY_INTERVAL_SECONDS)

    def _rewrite_url_base(self, url: str, endpoint: Optional[str]) -> str:
        """
        Replace scheme/netloc in a generated URL while preserving path/query.

        This lets the backend talk to MinIO on an internal Docker hostname while
        returning browser-usable URLs such as localhost:9010.
        """
        if not endpoint:
            return url

        parsed_url = urlparse(url)
        parsed_endpoint = urlparse(endpoint)

        if not parsed_endpoint.scheme or not parsed_endpoint.netloc:
            return url

        return urlunparse(parsed_url._replace(
            scheme=parsed_endpoint.scheme,
            netloc=parsed_endpoint.netloc,
        ))

    def _build_presign_client(self):
        """Return the best client to use when generating browser-facing presigned URLs."""
        minio_config = self._config.minio
        if not minio_config.public_endpoint or minio_config.public_endpoint == minio_config.endpoint:
            return self.s3_client

        public_client_kwargs = {
            'service_name': 's3',
            'region_name': minio_config.region,
            'endpoint_url': minio_config.public_endpoint,
            'config': Config(
                signature_version='s3v4',
                retries={'max_attempts': 3, 'mode': 'standard'},
                connect_timeout=S3_CONNECT_TIMEOUT_SECONDS,
                read_timeout=S3_READ_TIMEOUT_SECONDS,
                max_pool_connections=25
            ),
        }
        if minio_config.access_key and minio_config.secret_key:
            public_client_kwargs['aws_access_key_id'] = minio_config.access_key
            public_client_kwargs['aws_secret_access_key'] = minio_config.secret_key
        return boto3.client(**public_client_kwargs)

    def _ensure_browser_upload_cors(self, bucket_name: str) -> None:
        """Allow browser presigned uploads to the shared bucket when supported."""
        if bucket_name in self._cors_checked_buckets:
            return

        try:
            self.s3_client.put_bucket_cors(
                Bucket=bucket_name,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedMethods": ["GET", "PUT", "POST", "HEAD", "DELETE"],
                            "AllowedOrigins": ["*"],
                            "AllowedHeaders": ["*"],
                            "ExposeHeaders": ["ETag"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
            self._cors_checked_buckets.add(bucket_name)
        except Exception as e:
            self._logger.warning(
                "Could not apply browser upload CORS policy to bucket '%s': %s",
                bucket_name,
                e,
            )
    
    def ensure_user_bucket(self, user_id: int, username: Optional[str] = None) -> str:
        """
        Ensure the shared storage bucket exists, creating it if necessary.
        
        Args:
            user_id: User ID
            username: Optional username (for backward compatibility)
        
        Returns:
            str: Shared bucket name
        
        Raises:
            RuntimeError: If bucket creation fails
        """
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            # Check if bucket exists
            try:
                self.s3_client.head_bucket(Bucket=bucket_name)
                self._logger.debug(f"Bucket '{bucket_name}' already exists")
                self._ensure_browser_upload_cors(bucket_name)
                return bucket_name
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code == '404':
                    # Bucket doesn't exist, create it
                    pass
                else:
                    raise
            
            # Create bucket
            minio_config = self._config.minio
            
            # When a custom endpoint is configured we are talking to an S3-compatible
            # service such as MinIO, which does not need a location constraint.
            if minio_config.endpoint:
                self.s3_client.create_bucket(Bucket=bucket_name)
            else:
                # AWS S3 - us-east-1 is the special case that omits the location constraint.
                try:
                    if minio_config.region == "us-east-1":
                        self.s3_client.create_bucket(Bucket=bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=bucket_name,
                            CreateBucketConfiguration={'LocationConstraint': minio_config.region}
                        )
                except ClientError as e:
                    # If bucket already exists or other error
                    if e.response.get('Error', {}).get('Code') == 'BucketAlreadyOwnedByYou':
                        self._logger.debug(f"Bucket '{bucket_name}' already exists (owned by you)")
                        return bucket_name
                    raise
            
            self._logger.info(f"Created shared storage bucket '{bucket_name}'")
            self._ensure_browser_upload_cors(bucket_name)
            return bucket_name
            
        except (ClientError, BotoCoreError) as e:
            error_msg = f"Failed to ensure bucket '{bucket_name}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def upload_file(
        self,
        user_id: int,
        local_path: str,
        s3_key: str,
        username: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Upload a file to shared storage under the user's prefix.
        
        Args:
            user_id: User ID
            local_path: Local file path to upload
            s3_key: S3 object key (path within bucket)
            username: Optional username (for backward compatibility)
            metadata: Optional metadata dictionary
        
        Returns:
            dict: Upload result with bucket, key, size, and checksum
        
        Raises:
            FileNotFoundError: If local file doesn't exist
            RuntimeError: If upload fails
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"File not found: {local_path}")
        
        bucket_name = self.ensure_user_bucket(user_id, username)
        object_key = self._get_object_key(user_id, s3_key)
        
        # Calculate file size and checksum
        file_size = os.path.getsize(local_path)
        checksum = self._calculate_checksum(local_path)
        
        try:
            extra_args = {}
            if metadata:
                extra_args['Metadata'] = metadata
            
            transfer_config = TransferConfig(
                multipart_threshold=S3_MULTIPART_THRESHOLD_BYTES,
                multipart_chunksize=S3_MULTIPART_CHUNK_BYTES,
                max_concurrency=4,
                use_threads=True,
            )

            self.s3_client.upload_file(
                local_path,
                bucket_name,
                object_key,
                ExtraArgs=extra_args,
                Config=transfer_config,
            )
            head = self._wait_for_uploaded_object(bucket_name, object_key, file_size)
            
            self._logger.info(
                f"Uploaded file '{s3_key}' to shared bucket '{bucket_name}' as '{object_key}' "
                f"(size: {file_size} bytes, checksum: {checksum})"
            )
            
            return {
                'bucket': bucket_name,
                'key': s3_key,
                'object_key': object_key,
                'size': file_size,
                'checksum': checksum,
                'path': local_path,
                'etag': str(head.get('ETag', '')).strip('"') if head else None,
            }
            
        except (ClientError, BotoCoreError) as e:
            error_msg = f"Failed to upload file '{local_path}' to '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def download_file(
        self,
        user_id: int,
        s3_key: str,
        local_path: str,
        username: Optional[str] = None
    ) -> str:
        """
        Download a file from shared storage, with a legacy per-user-bucket fallback.
        
        Args:
            user_id: User ID
            s3_key: S3 object key
            local_path: Local file path to save to
            username: Optional username (for backward compatibility)
        
        Returns:
            str: Local file path
        
        Raises:
            RuntimeError: If download fails
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path) if os.path.dirname(local_path) else '.', exist_ok=True)

            last_error: Optional[Exception] = None
            for bucket_name, object_key in self._get_read_locations(user_id, s3_key, username):
                try:
                    self.s3_client.download_file(bucket_name, object_key, local_path)
                    self._logger.info(
                        f"Downloaded file '{s3_key}' from bucket '{bucket_name}' "
                        f"(object key '{object_key}') to '{local_path}'"
                    )
                    return local_path
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code in {'404', 'NoSuchKey', 'NoSuchBucket', 'NotFound'}:
                        last_error = e
                        continue
                    error_msg = f"Failed to download file '{s3_key}': {e}"
                    self._logger.error(error_msg)
                    raise RuntimeError(error_msg)

            raise RuntimeError(
                f"File '{s3_key}' not found in shared storage for user {user_id}"
            ) from last_error
        except (BotoCoreError, OSError) as e:
            error_msg = f"Failed to download file '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def list_files(
        self,
        user_id: int,
        prefix: Optional[str] = None,
        username: Optional[str] = None,
        max_keys: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        List files in shared storage for a user, with legacy-bucket compatibility.
        
        Args:
            user_id: User ID
            prefix: Optional prefix to filter files
            username: Optional username (for backward compatibility)
            max_keys: Maximum number of keys to return
        
        Returns:
            list: List of file dictionaries with key, size, last_modified, etag
        
        Raises:
            RuntimeError: If listing fails
        """
        try:
            files = []
            seen_keys = set()
            paginator = self.s3_client.get_paginator('list_objects_v2')
            shared_bucket = self._get_bucket_name(user_id, username)
            shared_prefix = self._get_object_key(user_id, prefix or "")
            legacy_bucket = self._get_legacy_bucket_name(user_id, username)
            candidate_locations = [
                (shared_bucket, shared_prefix, True),
                (legacy_bucket, self._normalize_s3_key(prefix or ""), False),
            ]

            for bucket_name, key_prefix, is_shared_layout in candidate_locations:
                try:
                    pages = paginator.paginate(
                        Bucket=bucket_name,
                        Prefix=key_prefix,
                        MaxKeys=max_keys
                    )
                    for page in pages:
                        if 'Contents' not in page:
                            continue
                        for obj in page['Contents']:
                            logical_key = (
                                self._strip_user_prefix(user_id, obj['Key'])
                                if is_shared_layout
                                else obj['Key']
                            )
                            if logical_key in seen_keys:
                                continue
                            seen_keys.add(logical_key)
                            files.append({
                                'key': logical_key,
                                'size': obj['Size'],
                                'last_modified': obj['LastModified'].isoformat(),
                                'etag': obj['ETag'].strip('"')
                            })
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code == 'NoSuchBucket':
                        continue
                    raise

            self._logger.debug(
                f"Listed {len(files)} files for user {user_id} with logical prefix '{prefix or ''}'"
            )
            return files
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchBucket':
                # Bucket doesn't exist, return empty list
                self._logger.debug(f"No storage bucket exists yet for user {user_id}, returning empty list")
                return []
            else:
                error_msg = f"Failed to list files for user {user_id}: {e}"
                self._logger.error(error_msg)
                raise RuntimeError(error_msg)
        except BotoCoreError as e:
            error_msg = f"Failed to list files for user {user_id}: {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def delete_file(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None
    ) -> bool:
        """
        Delete a file from shared storage and any legacy per-user bucket copy.
        
        Args:
            user_id: User ID
            s3_key: S3 object key
            username: Optional username (for backward compatibility)
        
        Returns:
            bool: True if deleted, False if not found
        
        Raises:
            RuntimeError: If deletion fails
        """
        try:
            deleted_any = False
            for bucket_name, object_key in self._get_read_locations(user_id, s3_key, username):
                try:
                    if not self._head_object(bucket_name, object_key):
                        continue
                    self.s3_client.delete_object(Bucket=bucket_name, Key=object_key)
                    deleted_any = True
                    self._logger.info(
                        f"Deleted file '{s3_key}' from bucket '{bucket_name}' (object key '{object_key}')"
                    )
                except ClientError as e:
                    error_msg = f"Failed to delete file '{s3_key}': {e}"
                    self._logger.error(error_msg)
                    raise RuntimeError(error_msg)
            return deleted_any
        except BotoCoreError as e:
            error_msg = f"Failed to delete file '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def delete_prefix(
        self,
        user_id: int,
        prefix: str,
        username: Optional[str] = None,
    ) -> int:
        """
        Delete every object under a prefix in shared storage and any legacy bucket.

        This is used for job cleanup so partial uploads or outputs that do not
        have database records are removed with the rest of the job.
        """
        deleted_count = 0

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            shared_bucket = self._get_bucket_name(user_id, username)
            shared_prefix = self._get_object_key(user_id, prefix)
            legacy_bucket = self._get_legacy_bucket_name(user_id, username)
            candidate_locations = [
                (shared_bucket, shared_prefix),
                (legacy_bucket, self._normalize_s3_key(prefix)),
            ]

            for bucket_name, key_prefix in candidate_locations:
                try:
                    for page in paginator.paginate(Bucket=bucket_name, Prefix=key_prefix):
                        objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                        if not objects:
                            continue

                        self.s3_client.delete_objects(
                            Bucket=bucket_name,
                            Delete={"Objects": objects, "Quiet": True},
                        )
                        deleted_count += len(objects)
                except ClientError as e:
                    error_code = e.response.get("Error", {}).get("Code", "")
                    if error_code == "NoSuchBucket":
                        continue
                    raise

            if deleted_count:
                self._logger.info(
                    f"Deleted {deleted_count} object(s) under logical prefix '{prefix}' for user {user_id}"
                )
            return deleted_count

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchBucket":
                self._logger.debug(f"No storage bucket exists yet for user {user_id}, nothing to delete")
                return 0

            error_msg = f"Failed to delete objects under prefix '{prefix}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
        except BotoCoreError as e:
            error_msg = f"Failed to delete objects under prefix '{prefix}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def generate_presigned_url(
        self,
        user_id: int,
        s3_key: str,
        expiration: int = 3600,
        username: Optional[str] = None,
        http_method: str = 'GET',
        response_content_disposition: Optional[str] = None
    ) -> str:
        """
        Generate a presigned URL for a file.
        
        Args:
            user_id: User ID
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)
            username: Optional username (for backward compatibility)
            http_method: HTTP method (GET or PUT, default: GET)
            response_content_disposition: Optional download filename/disposition for GET requests
        
        Returns:
            str: Presigned URL
        
        Raises:
            RuntimeError: If URL generation fails
        """
        try:
            resolved_location = self._resolve_existing_location(user_id, s3_key, username)
            if resolved_location:
                bucket_name, object_key = resolved_location
            else:
                bucket_name, object_key = self._get_primary_storage_location(user_id, s3_key, username)

            params = {'Bucket': bucket_name, 'Key': object_key}
            if response_content_disposition and http_method.upper() == 'GET':
                params['ResponseContentDisposition'] = response_content_disposition

            presign_client = self._build_presign_client()

            url = presign_client.generate_presigned_url(
                'get_object' if http_method.upper() == 'GET' else 'put_object',
                Params=params,
                ExpiresIn=expiration
            )
            
            self._logger.debug(f"Generated presigned URL for '{s3_key}' (expires in {expiration}s)")
            return url
            
        except (ClientError, BotoCoreError) as e:
            error_msg = f"Failed to generate presigned URL for '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def create_multipart_upload(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Create a multipart upload session for a browser-direct upload."""
        bucket_name = self.ensure_user_bucket(user_id, username)
        object_key = self._get_object_key(user_id, s3_key)

        try:
            extra_args: Dict[str, Any] = {
                'Bucket': bucket_name,
                'Key': object_key,
            }
            if content_type:
                extra_args['ContentType'] = content_type
            if metadata:
                extra_args['Metadata'] = metadata

            response = self.s3_client.create_multipart_upload(**extra_args)
            upload_id = response.get('UploadId')
            if not upload_id:
                raise RuntimeError("S3 did not return a multipart upload ID")

            return {
                'bucket': bucket_name,
                'key': s3_key,
                'object_key': object_key,
                'upload_id': upload_id,
            }
        except (ClientError, BotoCoreError) as e:
            error_msg = f"Failed to create multipart upload for '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def generate_presigned_upload_part_url(
        self,
        user_id: int,
        s3_key: str,
        upload_id: str,
        part_number: int,
        expiration: int = 3600,
        username: Optional[str] = None,
    ) -> str:
        """Generate a presigned URL for uploading a single multipart chunk."""
        if part_number < 1:
            raise ValueError("Multipart upload part numbers must be >= 1")

        bucket_name, object_key = self._get_primary_storage_location(user_id, s3_key, username)

        try:
            presign_client = self._build_presign_client()
            return presign_client.generate_presigned_url(
                'upload_part',
                Params={
                    'Bucket': bucket_name,
                    'Key': object_key,
                    'UploadId': upload_id,
                    'PartNumber': part_number,
                },
                ExpiresIn=expiration,
            )
        except (ClientError, BotoCoreError) as e:
            error_msg = f"Failed to generate presigned upload-part URL for '{s3_key}' part {part_number}: {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def complete_multipart_upload(
        self,
        user_id: int,
        s3_key: str,
        upload_id: str,
        parts: List[Dict[str, Any]],
        username: Optional[str] = None,
        expected_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Complete a multipart upload and optionally wait for the final object size."""
        if not parts:
            raise ValueError("Multipart upload completion requires at least one uploaded part")

        bucket_name, object_key = self._get_primary_storage_location(user_id, s3_key, username)
        normalized_parts = [
            {
                'ETag': str(part.get('etag') or part.get('ETag') or '').strip(),
                'PartNumber': int(part.get('part_number') or part.get('PartNumber') or 0),
            }
            for part in parts
        ]

        for part in normalized_parts:
            if part['PartNumber'] < 1 or not part['ETag']:
                raise ValueError("Each multipart upload part must include a valid part number and ETag")

        normalized_parts.sort(key=lambda part: part['PartNumber'])

        try:
            response = self.s3_client.complete_multipart_upload(
                Bucket=bucket_name,
                Key=object_key,
                UploadId=upload_id,
                MultipartUpload={'Parts': normalized_parts},
            )
            head = (
                self._wait_for_uploaded_object(bucket_name, object_key, expected_size)
                if expected_size is not None
                else self.s3_client.head_object(Bucket=bucket_name, Key=object_key)
            )
            return {
                'bucket': bucket_name,
                'key': s3_key,
                'object_key': object_key,
                'etag': str(head.get('ETag', '')).strip('"') if head else None,
                'location': response.get('Location'),
            }
        except (ClientError, BotoCoreError) as e:
            error_msg = f"Failed to complete multipart upload for '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)

    def abort_multipart_upload(
        self,
        user_id: int,
        s3_key: str,
        upload_id: str,
        username: Optional[str] = None,
    ) -> None:
        """Abort a multipart upload session if it is still open."""
        bucket_name, object_key = self._get_primary_storage_location(user_id, s3_key, username)
        try:
            self.s3_client.abort_multipart_upload(
                Bucket=bucket_name,
                Key=object_key,
                UploadId=upload_id,
            )
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in {'404', 'NoSuchUpload', 'NoSuchKey', 'NotFound'}:
                return
            error_msg = f"Failed to abort multipart upload for '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
        except BotoCoreError as e:
            error_msg = f"Failed to abort multipart upload for '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def file_exists(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None
    ) -> bool:
        """
        Check if a file exists in user's bucket.
        
        Args:
            user_id: User ID
            s3_key: S3 object key
            username: Optional username (for backward compatibility)
        
        Returns:
            bool: True if file exists, False otherwise
        """
        try:
            return self._resolve_existing_location(user_id, s3_key, username) is not None
        except ClientError as e:
            # Other errors, log and return False
            self._logger.warning(f"Error checking file existence for '{s3_key}': {e}")
            return False
        except BotoCoreError:
            return False
    
    def get_file_info(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get file metadata from user's bucket.
        
        Args:
            user_id: User ID
            s3_key: S3 object key
            username: Optional username (for backward compatibility)
        
        Returns:
            dict: File metadata (size, last_modified, etag, content_type) or None if not found
        """
        try:
            resolved_location = self._resolve_existing_location(user_id, s3_key, username)
            if not resolved_location:
                return None

            bucket_name, object_key = resolved_location
            response = self.s3_client.head_object(Bucket=bucket_name, Key=object_key)
            return {
                'key': s3_key,
                'size': response['ContentLength'],
                'last_modified': response['LastModified'].isoformat(),
                'etag': response['ETag'].strip('"'),
                'content_type': response.get('ContentType', 'application/octet-stream'),
                'metadata': response.get('Metadata', {})
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                return None
            self._logger.warning(f"Error getting file info for '{s3_key}': {e}")
            return None
        except BotoCoreError as e:
            self._logger.warning(f"Error getting file info for '{s3_key}': {e}")
            return None
    
    def _calculate_checksum(self, file_path: str) -> str:
        """
        Calculate MD5 checksum of a file.
        
        Args:
            file_path: Path to file
        
        Returns:
            str: MD5 checksum (hex)
        """
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()


# Singleton instance (optional, for convenience)
_client_instance: Optional[MinIOClient] = None


def get_minio_client() -> MinIOClient:
    """
    Get or create singleton MinIO client instance.
    
    Returns:
        MinIOClient: Singleton client instance
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = MinIOClient()
    return _client_instance


def reset_minio_client():
    """Reset singleton client instance (for testing)."""
    global _client_instance
    _client_instance = None
