"""
Data file service for managing files in folders.

This module provides operations for uploading, managing, and organizing files in user folders.
"""

import os
import tempfile
import hashlib
import time
from typing import Optional, List, Dict, Any
from datetime import datetime
from backend.api.database.db_init import get_db_connection
from backend.api.models.pipeline_model import FileInDB, FileType
from backend.api.services.folder_service import get_folder_by_id
from backend.api.services.minio_client import get_minio_client
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)
minio_client = get_minio_client()


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
            
            # Generate S3 key
            timestamp = int(time.time())
            if folder_id:
                folder_obj = get_folder_by_id(folder_id, user_id)
                folder_path = folder_obj.path.replace('/', '_') if folder_obj else f"folder_{folder_id}"
                s3_key = f"data/{user_id}/{folder_path}/{timestamp}_{filename}"
            else:
                s3_key = f"data/{user_id}/root/{timestamp}_{filename}"
            
            # Ensure user bucket exists
            from backend.api.services.user_service import get_user_by_id
            user = get_user_by_id(user_id)
            if not user:
                raise ValueError(f"User with id {user_id} not found")
            
            minio_client.ensure_user_bucket(user_id=user_id, username=user.username)
            
            # Save to temp file and upload
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
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
                        filename,
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

            timestamp = int(time.time())
            if folder_id:
                folder_obj = get_folder_by_id(folder_id, user_id)
                folder_path = folder_obj.path.replace('/', '_') if folder_obj else f"folder_{folder_id}"
                s3_key = f"data/{user_id}/{folder_path}/{timestamp}_{filename}"
            else:
                s3_key = f"data/{user_id}/root/{timestamp}_{filename}"

            from backend.api.services.user_service import get_user_by_id
            user = get_user_by_id(user_id)
            if not user:
                raise ValueError(f"User with id {user_id} not found")

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
                filename,
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
                    WHERE f.folder_id IS NULL AND f.s3_key LIKE %s
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
                WHERE f.id = %s AND (fo.user_id = %s OR (f.folder_id IS NULL AND f.s3_key LIKE %s))
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
            
            # Verify job exists and belongs to user (if job_id provided)
            if job_id:
                cur.execute("SELECT id, user_id FROM jobs WHERE id = %s", (job_id,))
                job_row = cur.fetchone()
                if not job_row or job_row[1] != user_id:
                    raise ValueError(f"Job with id {job_id} not found or doesn't belong to user")
            
            # Create new file record with job_id (can be NULL initially, updated later)
            cur.execute("""
                INSERT INTO files (job_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, 
                          size_bytes, checksum, uploaded_at, created_at
            """, (
                job_id,
                source_file.filename,
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
