"""
Storage service for database operations.

This module provides database operations for file management.
"""

from typing import Optional, List
from datetime import datetime
from contextlib import contextmanager
from backend.api.database.db_init import get_db_connection
from backend.api.models.pipeline_model import FileInDB, FileCreate, FileUpdate, FileResponse, FileType
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def create_file_record(file_data: FileCreate) -> FileInDB:
    """
    Create a new file record in the database.
    
    Args:
        file_data: File creation data
        
    Returns:
        FileInDB: Created file with database fields
        
    Raises:
        ValueError: If job_id doesn't exist
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify job exists (only if job_id is provided)
            if file_data.job_id is not None:
                cur.execute("SELECT id FROM jobs WHERE id = %s", (file_data.job_id,))
                if not cur.fetchone():
                    raise ValueError(f"Job with id {file_data.job_id} not found")
            
            # Insert file record (job_id can be NULL for staging)
            cur.execute("""
                INSERT INTO files (job_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, folder_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at, created_at
            """, (
                file_data.job_id,
                file_data.filename,
                file_data.s3_key,
                file_data.file_type.value,
                file_data.file_format,
                file_data.size_bytes,
                file_data.checksum,
                file_data.uploaded_at or datetime.utcnow()
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
            logger.error(f"Error creating file record: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_existing_file_record_by_fingerprint(
    *,
    job_id: int,
    filename: str,
    file_type: FileType,
    size_bytes: int,
    checksum: str,
) -> Optional[FileInDB]:
    """Return an existing job file matching the exact upload fingerprint."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT id, job_id, folder_id, filename, s3_key, file_type, file_format,
                       size_bytes, checksum, uploaded_at, created_at
                FROM files
                WHERE job_id = %s
                  AND filename = %s
                  AND file_type = %s
                  AND size_bytes = %s
                  AND checksum = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id, filename, file_type.value, size_bytes, checksum),
            )
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
                created_at=row[10],
            )
        finally:
            cur.close()


def get_file_by_id(file_id: int, user_id: Optional[int] = None) -> Optional[FileInDB]:
    """
    Get a file by ID, optionally filtered by user_id (through job ownership).
    
    Args:
        file_id: File ID to search for
        user_id: Optional user ID to verify ownership through job
        
    Returns:
        FileInDB: File if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if user_id:
                # Verify file belongs to user through job ownership OR is a staging file for this user
                # Staging files have s3_key like "staging/{user_id}/..."
                cur.execute("""
                    SELECT f.id, f.job_id, f.folder_id, f.filename, f.s3_key, f.file_type, f.file_format, 
                           f.size_bytes, f.checksum, f.uploaded_at, f.created_at
                    FROM files f
                    LEFT JOIN jobs j ON f.job_id = j.id
                    WHERE f.id = %s AND (
                        (f.job_id IS NOT NULL AND j.user_id = %s) OR
                        (f.job_id IS NULL AND f.s3_key LIKE %s)
                    )
                """, (file_id, user_id, f"staging/{user_id}/%"))
            else:
                cur.execute("""
                    SELECT id, job_id, folder_id, filename, s3_key, file_type, file_format, 
                           size_bytes, checksum, uploaded_at, created_at
                    FROM files
                    WHERE id = %s
                """, (file_id,))
            
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
        finally:
            cur.close()


def get_files_by_user(user_id: int, job_id: Optional[int] = None, file_type: Optional[FileType] = None, limit: int = 100, offset: int = 0) -> List[FileInDB]:
    """
    Get all files for a user (through job ownership), optionally filtered by job_id and file_type.
    
    Args:
        user_id: User ID to filter by (through job ownership)
        job_id: Optional job ID filter
        file_type: Optional file type filter
        limit: Maximum number of files to return
        offset: Number of files to skip
        
    Returns:
        List[FileInDB]: List of files
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            query = """
                SELECT f.id, f.job_id, f.folder_id, f.filename, f.s3_key, f.file_type, f.file_format, 
                       f.size_bytes, f.checksum, f.uploaded_at, f.created_at
                FROM files f
                INNER JOIN jobs j ON f.job_id = j.id
                WHERE j.user_id = %s
            """
            params = [user_id]
            
            if job_id:
                query += " AND f.job_id = %s"
                params.append(job_id)
            
            if file_type:
                query += " AND f.file_type = %s"
                params.append(file_type.value)
            
            # Order by file_type first (output files first, then input), then by created_at
            # This ensures important output files appear first
            query += " ORDER BY CASE f.file_type WHEN 'output' THEN 0 WHEN 'input' THEN 1 ELSE 2 END, f.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            cur.execute(query, params)
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
        finally:
            cur.close()


def update_file(file_id: int, user_id: int, file_update: FileUpdate) -> Optional[FileInDB]:
    """
    Update a file record.
    
    Args:
        file_id: File ID to update
        user_id: User ID to verify ownership through job
        file_update: File update data
        
    Returns:
        FileInDB: Updated file if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Build update query dynamically based on provided fields
            updates = []
            values = []
            
            if file_update.job_id is not None:
                updates.append("job_id = %s")
                values.append(file_update.job_id)
            
            if file_update.filename is not None:
                updates.append("filename = %s")
                values.append(file_update.filename)
            
            if file_update.file_format is not None:
                updates.append("file_format = %s")
                values.append(file_update.file_format)
            
            if file_update.size_bytes is not None:
                updates.append("size_bytes = %s")
                values.append(file_update.size_bytes)
            
            if file_update.checksum is not None:
                updates.append("checksum = %s")
                values.append(file_update.checksum)
            
            if not updates:
                # No updates provided, just return the existing file
                return get_file_by_id(file_id, user_id)
            
            # Add WHERE clause with ownership verification
            values.append(file_id)
            
            if file_update.job_id is not None:
                # Verify new job belongs to user
                cur.execute("SELECT id FROM jobs WHERE id = %s AND user_id = %s", (file_update.job_id, user_id))
                if not cur.fetchone():
                    raise ValueError(f"Job {file_update.job_id} not found or doesn't belong to user {user_id}")
                
                # Update file: allow if file has no job_id (staging) or if current job belongs to user
                query = f"""
                    UPDATE files
                    SET {', '.join(updates)}
                    WHERE files.id = %s AND (
                        files.job_id IS NULL OR 
                        EXISTS (SELECT 1 FROM jobs j WHERE j.id = files.job_id AND j.user_id = %s)
                    )
                    RETURNING files.id, files.job_id, files.filename, files.s3_key, files.file_type, 
                              files.file_format, files.size_bytes, files.checksum, files.uploaded_at, files.created_at
                """
                values.append(user_id)
            else:
                # No job_id update, verify through existing job or allow if job_id is NULL
                # For staging files (job_id IS NULL), we need a way to verify ownership
                # For now, allow update if job_id is NULL (staging files) or if job belongs to user
                query = f"""
                    UPDATE files
                    SET {', '.join(updates)}
                    WHERE files.id = %s AND (
                        files.job_id IS NULL OR 
                        EXISTS (SELECT 1 FROM jobs j WHERE j.id = files.job_id AND j.user_id = %s)
                    )
                    RETURNING files.id, files.job_id, files.filename, files.s3_key, files.file_type, 
                              files.file_format, files.size_bytes, files.checksum, files.uploaded_at, files.created_at
                """
                values.append(user_id)
            
            cur.execute(query, values)
            row = cur.fetchone()
            
            if not row:
                return None
            
            conn.commit()
            
            return FileInDB(
                id=row[0],
                job_id=row[1],
                filename=row[2],
                s3_key=row[3],
                file_type=FileType(row[4]),
                file_format=row[5],
                size_bytes=row[6],
                checksum=row[7],
                uploaded_at=row[8],
                created_at=row[9]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating file: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def delete_file_record(file_id: int, user_id: int) -> bool:
    """
    Delete a file record from the database.
    
    Note: This only deletes the database record, not the actual file in S3.
    The actual file deletion should be handled separately.
    
    Args:
        file_id: File ID to delete
        user_id: User ID to verify ownership through job
        
    Returns:
        bool: True if file was deleted, False if not found or not accessible
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                DELETE FROM files
                USING jobs j
                WHERE files.job_id = j.id AND files.id = %s AND j.user_id = %s
            """, (file_id, user_id))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting file record: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def delete_file_records_for_job(user_id: int, job_id: int, file_type: Optional[FileType] = None) -> int:
    """
    Delete all file records for a job, optionally limited to a file type.

    Args:
        user_id: User ID to verify ownership through the job
        job_id: Job whose file records should be deleted
        file_type: Optional file type filter

    Returns:
        int: Number of deleted file records
    """
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            query = """
                DELETE FROM files
                USING jobs j
                WHERE files.job_id = j.id
                  AND j.id = %s
                  AND j.user_id = %s
            """
            params: List[object] = [job_id, user_id]

            if file_type is not None:
                query += " AND files.file_type = %s"
                params.append(file_type.value)

            cur.execute(query, params)
            deleted_count = cur.rowcount
            conn.commit()
            return deleted_count
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting file records for job {job_id}: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def count_files_by_user(user_id: int, job_id: Optional[int] = None, file_type: Optional[FileType] = None) -> int:
    """
    Count files for a user, optionally filtered by job_id and file_type.
    
    Args:
        user_id: User ID to filter by (through job ownership)
        job_id: Optional job ID filter
        file_type: Optional file type filter
        
    Returns:
        int: Number of files
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            query = """
                SELECT COUNT(*)
                FROM files f
                INNER JOIN jobs j ON f.job_id = j.id
                WHERE j.user_id = %s
            """
            params = [user_id]
            
            if job_id:
                query += " AND f.job_id = %s"
                params.append(job_id)
            
            if file_type:
                query += " AND f.file_type = %s"
                params.append(file_type.value)
            
            cur.execute(query, params)
            return cur.fetchone()[0]
        finally:
            cur.close()
