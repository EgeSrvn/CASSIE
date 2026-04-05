"""
MinIO/S3 client service for CASSIE backend.

This module provides a service for interacting with MinIO (local S3-compatible storage)
or AWS S3. It supports per-user bucket management and file operations.

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
from botocore.config import Config

from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


class MinIOClient:
    """
    MinIO/S3 client service for file storage operations.
    
    Supports both MinIO (local) and AWS S3 (production) through configuration.
    Provides per-user bucket management and file operations.
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
        
        # Configure boto3 for MinIO or AWS S3
        # Increase connection timeout and add retry configuration
        config = Config(
            signature_version='s3v4',
            retries={'max_attempts': 3, 'mode': 'standard'},
            connect_timeout=10,
            read_timeout=10,
            max_pool_connections=10
        )
        
        client_kwargs = {
            'service_name': 's3',
            'aws_access_key_id': minio_config.access_key,
            'aws_secret_access_key': minio_config.secret_key,
            'region_name': minio_config.region,
            'config': config,
        }
        
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
                # Test connection with timeout
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
        Generate bucket name for a user.
        
        Args:
            user_id: User ID
            username: Optional username (for backward compatibility)
        
        Returns:
            str: Bucket name (e.g., "cassie-user-1")
        """
        prefix = self._config.minio.bucket_prefix.rstrip('-')
        return f"{prefix}-user-{user_id}"

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
    
    def ensure_user_bucket(self, user_id: int, username: Optional[str] = None) -> str:
        """
        Ensure a user's bucket exists, creating it if necessary.
        
        Args:
            user_id: User ID
            username: Optional username (for backward compatibility)
        
        Returns:
            str: Bucket name
        
        Raises:
            RuntimeError: If bucket creation fails
        """
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            # Check if bucket exists
            try:
                self.s3_client.head_bucket(Bucket=bucket_name)
                self._logger.debug(f"Bucket '{bucket_name}' already exists")
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
                # AWS S3 - may need location constraint
                try:
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
            
            self._logger.info(f"Created bucket '{bucket_name}' for user {user_id}")
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
        Upload a file to user's bucket.
        
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
        
        # Calculate file size and checksum
        file_size = os.path.getsize(local_path)
        checksum = self._calculate_checksum(local_path)
        
        try:
            extra_args = {}
            if metadata:
                extra_args['Metadata'] = metadata
            
            self.s3_client.upload_file(
                local_path,
                bucket_name,
                s3_key,
                ExtraArgs=extra_args
            )
            
            self._logger.info(
                f"Uploaded file '{s3_key}' to bucket '{bucket_name}' "
                f"(size: {file_size} bytes, checksum: {checksum})"
            )
            
            return {
                'bucket': bucket_name,
                'key': s3_key,
                'size': file_size,
                'checksum': checksum,
                'path': local_path
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
        Download a file from user's bucket.
        
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
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path) if os.path.dirname(local_path) else '.', exist_ok=True)
            
            self.s3_client.download_file(bucket_name, s3_key, local_path)
            
            self._logger.info(f"Downloaded file '{s3_key}' from bucket '{bucket_name}' to '{local_path}'")
            return local_path
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchKey':
                raise RuntimeError(f"File '{s3_key}' not found in bucket '{bucket_name}'")
            elif error_code == 'NoSuchBucket':
                raise RuntimeError(f"Bucket '{bucket_name}' not found")
            else:
                error_msg = f"Failed to download file '{s3_key}': {e}"
                self._logger.error(error_msg)
                raise RuntimeError(error_msg)
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
        List files in user's bucket.
        
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
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=bucket_name,
                Prefix=prefix or '',
                MaxKeys=max_keys
            )
            
            files = []
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        files.append({
                            'key': obj['Key'],
                            'size': obj['Size'],
                            'last_modified': obj['LastModified'].isoformat(),
                            'etag': obj['ETag'].strip('"')
                        })
            
            self._logger.debug(f"Listed {len(files)} files from bucket '{bucket_name}' with prefix '{prefix}'")
            return files
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchBucket':
                # Bucket doesn't exist, return empty list
                self._logger.debug(f"Bucket '{bucket_name}' does not exist, returning empty list")
                return []
            else:
                error_msg = f"Failed to list files in bucket '{bucket_name}': {e}"
                self._logger.error(error_msg)
                raise RuntimeError(error_msg)
        except BotoCoreError as e:
            error_msg = f"Failed to list files in bucket '{bucket_name}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def delete_file(
        self,
        user_id: int,
        s3_key: str,
        username: Optional[str] = None
    ) -> bool:
        """
        Delete a file from user's bucket.
        
        Args:
            user_id: User ID
            s3_key: S3 object key
            username: Optional username (for backward compatibility)
        
        Returns:
            bool: True if deleted, False if not found
        
        Raises:
            RuntimeError: If deletion fails
        """
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            self.s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
            self._logger.info(f"Deleted file '{s3_key}' from bucket '{bucket_name}'")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchKey':
                self._logger.warning(f"File '{s3_key}' not found in bucket '{bucket_name}'")
                return False
            else:
                error_msg = f"Failed to delete file '{s3_key}': {e}"
                self._logger.error(error_msg)
                raise RuntimeError(error_msg)
        except BotoCoreError as e:
            error_msg = f"Failed to delete file '{s3_key}': {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def generate_presigned_url(
        self,
        user_id: int,
        s3_key: str,
        expiration: int = 3600,
        username: Optional[str] = None,
        http_method: str = 'GET'
    ) -> str:
        """
        Generate a presigned URL for a file.
        
        Args:
            user_id: User ID
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)
            username: Optional username (for backward compatibility)
            http_method: HTTP method (GET or PUT, default: GET)
        
        Returns:
            str: Presigned URL
        
        Raises:
            RuntimeError: If URL generation fails
        """
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object' if http_method.upper() == 'GET' else 'put_object',
                Params={'Bucket': bucket_name, 'Key': s3_key},
                ExpiresIn=expiration
            )
            url = self._rewrite_url_base(url, self._config.minio.public_endpoint)
            
            self._logger.debug(f"Generated presigned URL for '{s3_key}' (expires in {expiration}s)")
            return url
            
        except (ClientError, BotoCoreError) as e:
            error_msg = f"Failed to generate presigned URL for '{s3_key}': {e}"
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
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                return False
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
        bucket_name = self._get_bucket_name(user_id, username)
        
        try:
            response = self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
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
