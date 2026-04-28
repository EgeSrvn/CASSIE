"""
Data file service for managing files in folders.

This module provides operations for uploading, managing, and organizing files in user folders.
"""

import os
import tempfile
import hashlib
import re
import time
import uuid
import shutil
from typing import Optional, List, Dict, Any
from datetime import datetime
from backend.api.database.db_init import get_db_connection
from backend.api.models.pipeline_model import FileInDB, FileType
from backend.api.services.folder_service import get_folder_by_id
from backend.api.services.minio_client import get_minio_client
from backend.api.services.user_limit_service import validate_user_storage_capacity
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)
minio_client = get_minio_client()

MAX_STORED_FILENAME_LENGTH = 180


def _safe_data_filename(filename: str) -> str:
    raw_name = str(filename or "").strip()
    clean_name = os.path.basename(raw_name) if raw_name else ""
    clean_name = re.sub(r'[\\/:*?"<>|]+', "_", clean_name).strip(" .")
    return (clean_name or "input.dat")[:MAX_STORED_FILENAME_LENGTH]


def make_storage_data_filename(filename: str) -> str:
    """Return a unique internal object basename for storage."""
    clean_name = _safe_data_filename(filename)
    prefix = f"{time.time_ns()}_{uuid.uuid4().hex[:10]}"
    extension = "".join(os.path.splitext(clean_name)[1:])
    stem = clean_name[:-len(extension)] if extension else clean_name
    reserved = len(prefix) + 1 + len(extension)
    max_stem_length = max(MAX_STORED_FILENAME_LENGTH - reserved, 1)
    return f"{prefix}_{stem[:max_stem_length]}{extension}"


def _dedupe_display_filename(filename: str, existing_names: set[str]) -> str:
    """Return a readable filename that will not collide in a single job workspace."""
    clean_name = _safe_data_filename(filename)
    if clean_name.lower() not in existing_names:
        return clean_name

    extension = "".join(os.path.splitext(clean_name)[1:])
    stem = clean_name[:-len(extension)] if extension else clean_name
    index = 2
    while True:
        suffix = f" ({index})"
        max_stem_length = max(MAX_STORED_FILENAME_LENGTH - len(suffix) - len(extension), 1)
        candidate = f"{stem[:max_stem_length]}{suffix}{extension}"
        if candidate.lower() not in existing_names:
            return candidate
        index += 1


def build_data_s3_key(user_id: int, stored_filename: str, folder_id: Optional[int]) -> str:
    """Build the logical object key for a canonical stored filename."""
    filename = _safe_data_filename(stored_filename)
    if folder_id:
        folder_obj = get_folder_by_id(folder_id, user_id)
        folder_path = folder_obj.path.replace('/', '_') if folder_obj else f"folder_{folder_id}"
        return f"data/{user_id}/{folder_path}/{filename}"
    return f"data/{user_id}/root/{filename}"


def upload_data_file(
    user_id: int,
    file_content: bytes,
    filename: str,
    folder_id: Optional[int],
    file_format: Optional[str] = None
) -> FileInDB:
    """
    Upload a file to a folder.
    
    Args:
        user_id: User ID
        file_content: File content as bytes
        filename: Original filename
        folder_id: Target folder ID (None for root)
        file_format: Optional file format
        
    Returns:
        FileInDB: Created file record
        
    Raises:
        ValueError: If folder doesn't exist or belongs to different user
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Validate folder if provided
            if folder_id:
                folder = get_folder_by_id(folder_id, user_id)
                if not folder:
                    raise ValueError(f"Folder with id {folder_id} not found")
            
            # Calculate file size and checksum
            file_size = len(file_content)
            hash_md5 = hashlib.md5()
            hash_md5.update(file_content)
            checksum = hash_md5.hexdigest()
            
            display_filename = _safe_data_filename(filename)
            stored_filename = make_storage_data_filename(display_filename)
            s3_key = build_data_s3_key(user_id, stored_filename, folder_id)
            
            # Ensure user bucket exists
            from backend.api.services.user_service import get_user_by_id
            user = get_user_by_id(user_id)
            if not user:
                raise ValueError(f"User with id {user_id} not found")

            storage_ok, storage_error = validate_user_storage_capacity(
                user_id=user_id,
                username=user.username,
                incoming_bytes=file_size,
                available_bytes=shutil.disk_usage(tempfile.gettempdir()).free,
            )
            if not storage_ok:
                raise ValueError(storage_error)
            
            minio_client.ensure_user_bucket(user_id=user_id, username=user.username)
            
            # Save to temp file and upload
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(stored_filename)[1]) as temp_file:
                temp_path = temp_file.name
                temp_file.write(file_content)
                temp_file.flush()
                
                try:
                    # Upload to MinIO
                    upload_result = minio_client.upload_file(
                        user_id=user_id,
                        local_path=temp_path,
                        s3_key=s3_key,
                        username=user.username
                    )
                    
                    # Create file record
                    cur.execute("""
                        INSERT INTO files (folder_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at, created_at
                    """, (
                        folder_id,
                        display_filename,
                        s3_key,
                        'input',  # Folder files are always input type
                        file_format,
                        file_size,
                        checksum,
                        datetime.utcnow()
                    ))
                    
                    row = cur.fetchone()
                    conn.commit()
                    
                    return FileInDB(
                        id=row[0],
                        job_id=row[1],
                        folder_id=row[2],
                        filename=row[3],
                        s3_key=row[4],
                        file_type=FileType(row[5]),
                        file_format=row[6],
                        size_bytes=row[7],
                        checksum=row[8],
                        uploaded_at=row[9],
                        created_at=row[10]
                    )
                    
                finally:
                    # Cleanup temp file
                    if os.path.exists(temp_path):
                        try:
                            os.unlink(temp_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete temp file {temp_path}: {e}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error uploading data file: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def upload_data_file_from_path(
    user_id: int,
    local_path: str,
    filename: str,
    folder_id: Optional[int],
    file_format: Optional[str] = None
) -> FileInDB:
    """
    Register an already-downloaded local file as a user data-library file.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            if folder_id:
                folder = get_folder_by_id(folder_id, user_id)
                if not folder:
                    raise ValueError(f"Folder with id {folder_id} not found")

            file_size = os.path.getsize(local_path)
            hash_md5 = hashlib.md5()
            with open(local_path, "rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    hash_md5.update(chunk)
            checksum = hash_md5.hexdigest()

            display_filename = _safe_data_filename(filename)
            stored_filename = make_storage_data_filename(display_filename)
            s3_key = build_data_s3_key(user_id, stored_filename, folder_id)

            from backend.api.services.user_service import get_user_by_id
            user = get_user_by_id(user_id)
            if not user:
                raise ValueError(f"User with id {user_id} not found")

            storage_ok, storage_error = validate_user_storage_capacity(
                user_id=user_id,
                username=user.username,
                incoming_bytes=file_size,
                available_bytes=shutil.disk_usage(local_path).free,
            )
            if not storage_ok:
                raise ValueError(storage_error)

            minio_client.ensure_user_bucket(user_id=user_id, username=user.username)
            minio_client.upload_file(
                user_id=user_id,
                local_path=local_path,
                s3_key=s3_key,
                username=user.username
            )

            cur.execute("""
                INSERT INTO files (folder_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at, created_at
            """, (
                folder_id,
                display_filename,
                s3_key,
                'input',
                file_format,
                file_size,
                checksum,
                datetime.utcnow()
            ))

            row = cur.fetchone()
            conn.commit()

            return FileInDB(
                id=row[0],
                job_id=row[1],
                folder_id=row[2],
                filename=row[3],
                s3_key=row[4],
                file_type=FileType(row[5]),
                file_format=row[6],
                size_bytes=row[7],
                checksum=row[8],
                uploaded_at=row[9],
                created_at=row[10]
            )

        except Exception as e:
            conn.rollback()
            logger.error(f"Error uploading data file from path: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def create_data_file_record_for_existing_object(
    user_id: int,
    filename: str,
    s3_key: str,
    folder_id: Optional[int],
    file_format: Optional[str],
    size_bytes: int,
    checksum: Optional[str] = None,
) -> FileInDB:
    """Create a data-library record after object storage confirms direct upload."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (s3_key,))

            if folder_id:
                folder = get_folder_by_id(folder_id, user_id)
                if not folder:
                    raise ValueError(f"Folder with id {folder_id} not found")

            cur.execute("""
                SELECT f.id, f.job_id, f.folder_id, f.filename, f.s3_key, f.file_type, f.file_format,
                       f.size_bytes, f.checksum, f.uploaded_at, f.created_at
                FROM files f
                LEFT JOIN folders fo ON f.folder_id = fo.id
                WHERE f.s3_key = %s
                  AND f.job_id IS NULL
                  AND (
                        fo.user_id = %s
                        OR (f.folder_id IS NULL AND f.s3_key LIKE %s)
                  )
                ORDER BY f.created_at DESC, f.id DESC
                LIMIT 1
            """, (s3_key, user_id, f"data/{user_id}/%"))
            existing_row = cur.fetchone()
            if existing_row:
                conn.commit()
                return FileInDB(
                    id=existing_row[0],
                    job_id=existing_row[1],
                    folder_id=existing_row[2],
                    filename=existing_row[3],
                    s3_key=existing_row[4],
                    file_type=FileType(existing_row[5]),
                    file_format=existing_row[6],
                    size_bytes=existing_row[7],
                    checksum=existing_row[8],
                    uploaded_at=existing_row[9],
                    created_at=existing_row[10],
                )

            cur.execute("""
                INSERT INTO files (folder_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at, created_at
            """, (
                folder_id,
                filename,
                s3_key,
                'input',
                file_format,
                size_bytes,
                checksum,
                datetime.utcnow(),
            ))

            row = cur.fetchone()
            conn.commit()

            return FileInDB(
                id=row[0],
                job_id=row[1],
                folder_id=row[2],
                filename=row[3],
                s3_key=row[4],
                file_type=FileType(row[5]),
                file_format=row[6],
                size_bytes=row[7],
                checksum=row[8],
                uploaded_at=row[9],
                created_at=row[10],
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating direct-upload data file record: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def prune_missing_data_file_records(user_id: int, username: Optional[str] = None) -> int:
    """Remove data-library DB rows whose confirmed object is no longer in storage."""
    prefix = f"data/{user_id}/"

    try:
        storage_files = minio_client.list_files(
            user_id=user_id,
            prefix=prefix,
            username=username,
            max_keys=10000,
        )
    except Exception as e:
        logger.warning(
            "Skipping stale data-file pruning for user %s because object storage could not be listed: %s",
            user_id,
            e,
        )
        return 0

    existing_keys = {str(file_info.get("key") or "") for file_info in storage_files}

    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT f.id, f.filename, f.s3_key
                FROM files f
                LEFT JOIN folders fo ON f.folder_id = fo.id
                WHERE f.job_id IS NULL
                  AND (
                        fo.user_id = %s
                        OR (f.folder_id IS NULL AND f.s3_key LIKE %s)
                  )
            """, (user_id, f"{prefix}%"))

            stale_rows = [
                (row[0], row[1], row[2])
                for row in cur.fetchall()
                if row[2] not in existing_keys
            ]
            if not stale_rows:
                return 0

            stale_ids = [row[0] for row in stale_rows]
            cur.execute("DELETE FROM files WHERE id = ANY(%s)", (stale_ids,))
            conn.commit()

            logger.warning(
                "Pruned %s stale data-file records for user %s: %s",
                len(stale_rows),
                user_id,
                ", ".join(f"{filename} ({s3_key})" for _, filename, s3_key in stale_rows[:10]),
            )
            return len(stale_rows)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error pruning stale data-file records for user {user_id}: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_data_files_by_folder(folder_id: Optional[int], user_id: int) -> List[FileInDB]:
    """
    Get all files in a folder.
    
    Args:
        folder_id: Folder ID (None for root)
        user_id: User ID for verification
        
    Returns:
        List[FileInDB]: List of files
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if folder_id:
                # Verify folder belongs to user
                folder = get_folder_by_id(folder_id, user_id)
                if not folder:
                    return []
                
                cur.execute("""
                    SELECT id, job_id, folder_id, filename, s3_key, file_type, file_format, 
                           size_bytes, checksum, uploaded_at, created_at
                    FROM files
                    WHERE folder_id = %s
                    ORDER BY filename
                """, (folder_id,))
            else:
                # Get files in root (no folder_id, but must be user's data files)
                # Files in data/ prefix belong to this user
                cur.execute("""
                    SELECT f.id, f.job_id, f.folder_id, f.filename, f.s3_key, f.file_type, f.file_format, 
                           f.size_bytes, f.checksum, f.uploaded_at, f.created_at
                    FROM files f
                WHERE f.folder_id IS NULL
                  AND f.job_id IS NULL
                  AND f.s3_key LIKE %s
                ORDER BY f.filename
                """, (f"data/{user_id}/%",))
            
            rows = cur.fetchall()
            files = []
            
            for row in rows:
                files.append(FileInDB(
                    id=row[0],
                    job_id=row[1],
                    folder_id=row[2],
                    filename=row[3],
                    s3_key=row[4],
                    file_type=FileType(row[5]),
                    file_format=row[6],
                    size_bytes=row[7],
                    checksum=row[8],
                    uploaded_at=row[9],
                    created_at=row[10]
                ))
            
            return files
            
        except Exception as e:
            logger.error(f"Error getting data files: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_data_file_by_id(file_id: int, user_id: int) -> Optional[FileInDB]:
    """
    Get a data file by ID, verifying it belongs to the user.
    
    Args:
        file_id: File ID
        user_id: User ID for verification
        
    Returns:
        FileInDB: File if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT f.id, f.job_id, f.folder_id, f.filename, f.s3_key, f.file_type, f.file_format, 
                       f.size_bytes, f.checksum, f.uploaded_at, f.created_at
                FROM files f
                LEFT JOIN folders fo ON f.folder_id = fo.id
                WHERE f.id = %s
                  AND f.job_id IS NULL
                  AND (fo.user_id = %s OR (f.folder_id IS NULL AND f.s3_key LIKE %s))
            """, (file_id, user_id, f"data/{user_id}/%"))
            
            row = cur.fetchone()
            
            if not row:
                return None
            
            return FileInDB(
                id=row[0],
                job_id=row[1],
                folder_id=row[2],
                filename=row[3],
                s3_key=row[4],
                file_type=FileType(row[5]),
                file_format=row[6],
                size_bytes=row[7],
                checksum=row[8],
                uploaded_at=row[9],
                created_at=row[10]
            )
            
        except Exception as e:
            logger.error(f"Error getting data file: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def rename_data_file(file_id: int, user_id: int, new_name: str) -> Optional[FileInDB]:
    """
    Rename a data file.
    
    Args:
        file_id: File ID
        user_id: User ID for verification
        new_name: New filename
        
    Returns:
        FileInDB: Updated file, None if not found
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify file exists and belongs to user
            file_obj = get_data_file_by_id(file_id, user_id)
            if not file_obj:
                return None
            
            # Update filename
            cur.execute("""
                UPDATE files
                SET filename = %s
                WHERE id = %s
                RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, 
                          size_bytes, checksum, uploaded_at, created_at
            """, (new_name, file_id))
            
            row = cur.fetchone()
            conn.commit()
            
            if row:
                return FileInDB(
                    id=row[0],
                    job_id=row[1],
                    folder_id=row[2],
                    filename=row[3],
                    s3_key=row[4],
                    file_type=FileType(row[5]),
                    file_format=row[6],
                    size_bytes=row[7],
                    checksum=row[8],
                    uploaded_at=row[9],
                    created_at=row[10]
                )
            
            return None
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error renaming data file: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def move_data_file(file_id: int, user_id: int, target_folder_id: Optional[int]) -> Optional[FileInDB]:
    """
    Move a file to a different folder.
    
    Args:
        file_id: File ID
        user_id: User ID for verification
        target_folder_id: Target folder ID (None for root)
        
    Returns:
        FileInDB: Updated file, None if not found
        
    Raises:
        ValueError: If target folder doesn't exist or belongs to different user
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify file exists and belongs to user
            file_obj = get_data_file_by_id(file_id, user_id)
            if not file_obj:
                return None
            
            # Validate target folder if provided
            if target_folder_id:
                folder = get_folder_by_id(target_folder_id, user_id)
                if not folder:
                    raise ValueError(f"Target folder with id {target_folder_id} not found")
            
            # Update folder_id
            cur.execute("""
                UPDATE files
                SET folder_id = %s
                WHERE id = %s
                RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, 
                          size_bytes, checksum, uploaded_at, created_at
            """, (target_folder_id, file_id))
            
            row = cur.fetchone()
            conn.commit()
            
            if row:
                return FileInDB(
                    id=row[0],
                    job_id=row[1],
                    folder_id=row[2],
                    filename=row[3],
                    s3_key=row[4],
                    file_type=FileType(row[5]),
                    file_format=row[6],
                    size_bytes=row[7],
                    checksum=row[8],
                    uploaded_at=row[9],
                    created_at=row[10]
                )
            
            return None
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error moving data file: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def delete_data_file(file_id: int, user_id: int) -> bool:
    """
    Delete a data file from folder and MinIO.
    
    Args:
        file_id: File ID
        user_id: User ID for verification
        
    Returns:
        bool: True if deleted, False if not found
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify file exists and belongs to user
            file_obj = get_data_file_by_id(file_id, user_id)
            if not file_obj:
                return False
            
            # Delete from MinIO
            try:
                from backend.api.services.user_service import get_user_by_id
                user = get_user_by_id(user_id)
                if user:
                    minio_client.delete_file(
                        user_id=user_id,
                        s3_key=file_obj.s3_key,
                        username=user.username
                    )
                else:
                    logger.warning(f"User {user_id} not found, skipping MinIO deletion for file {file_id}")
            except Exception as e:
                logger.warning(f"Failed to delete file {file_obj.s3_key} from MinIO: {e}")
                # Continue to delete database record even if MinIO deletion fails
            
            # Delete from database
            cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
            deleted = cur.rowcount > 0
            
            conn.commit()
            return deleted
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting data file: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def copy_data_file_to_job(file_id: int, user_id: int, job_id: int) -> Optional[FileInDB]:
    """
    Copy a folder file to a job (create new file record with job_id).
    
    Args:
        file_id: Source file ID (in folder)
        user_id: User ID for verification
        job_id: Target job ID
        
    Returns:
        FileInDB: New file record associated with job, None if not found
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify source file exists and belongs to user
            source_file = get_data_file_by_id(file_id, user_id)
            if not source_file:
                return None

            from backend.api.services.user_service import get_user_by_id
            user = get_user_by_id(user_id)
            storage_info = minio_client.get_file_info(
                user_id=user_id,
                s3_key=source_file.s3_key,
                username=user.username if user else None,
            )
            if not storage_info:
                raise ValueError(
                    f"Stored file '{source_file.filename}' is missing from object storage. "
                    "Delete it from Storage and upload it again."
                )
            
            # Verify job exists and belongs to user (if job_id provided)
            if job_id:
                cur.execute("SELECT id, user_id FROM jobs WHERE id = %s", (job_id,))
                job_row = cur.fetchone()
                if not job_row or job_row[1] != user_id:
                    raise ValueError(f"Job with id {job_id} not found or doesn't belong to user")
            
            cur.execute(
                "SELECT lower(filename) FROM files WHERE job_id = %s",
                (job_id,),
            )
            existing_job_names = {row[0] for row in cur.fetchall() if row[0]}
            job_filename = _dedupe_display_filename(source_file.filename, existing_job_names)

            # Create new file record with job_id (can be NULL initially, updated later)
            cur.execute("""
                INSERT INTO files (job_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, 
                          size_bytes, checksum, uploaded_at, created_at
            """, (
                job_id,
                job_filename,
                source_file.s3_key,  # Same S3 key (file is shared, not copied)
                source_file.file_type.value,
                source_file.file_format,
                source_file.size_bytes,
                source_file.checksum,
                source_file.uploaded_at or datetime.utcnow()
            ))
            
            row = cur.fetchone()
            conn.commit()
            
            return FileInDB(
                id=row[0],
                job_id=row[1],
                folder_id=row[2],
                filename=row[3],
                s3_key=row[4],
                file_type=FileType(row[5]),
                file_format=row[6],
                size_bytes=row[7],
                checksum=row[8],
                uploaded_at=row[9],
                created_at=row[10]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error copying data file to job: {e}", exc_info=True)
            raise
        finally:
            cur.close()
