"""
Folder service for database operations.

This module provides database operations for folder management.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager
from backend.api.database.db_init import get_db_connection
from backend.api.models.folder_model import FolderInDB, FolderCreate, FolderUpdate
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def calculate_folder_path(folder_id: int) -> str:
    """
    Calculate the full path for a folder by traversing up the parent chain.
    
    Args:
        folder_id: Folder ID
        
    Returns:
        str: Full path like "root/folder1/subfolder"
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            path_parts = []
            current_id = folder_id
            
            while current_id:
                cur.execute("SELECT id, name, parent_folder_id FROM folders WHERE id = %s", (current_id,))
                row = cur.fetchone()
                
                if not row:
                    break
                    
                folder_id_val, name, parent_id = row
                path_parts.insert(0, name)
                current_id = parent_id
            
            return "/".join(path_parts) if path_parts else "root"
            
        except Exception as e:
            logger.error(f"Error calculating folder path: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def create_folder(user_id: int, folder_data: FolderCreate) -> FolderInDB:
    """
    Create a new folder.
    
    Args:
        user_id: User ID
        folder_data: Folder creation data
        
    Returns:
        FolderInDB: Created folder
        
    Raises:
        ValueError: If parent folder doesn't exist or belongs to different user
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Validate parent folder if provided
            parent_folder_id = folder_data.parent_folder_id
            if parent_folder_id:
                cur.execute("SELECT id, user_id FROM folders WHERE id = %s", (parent_folder_id,))
                parent_row = cur.fetchone()
                
                if not parent_row:
                    raise ValueError(f"Parent folder with id {parent_folder_id} not found")
                
                if parent_row[1] != user_id:
                    raise ValueError("Parent folder belongs to a different user")
            
            # Check for duplicate name in same parent
            if parent_folder_id:
                cur.execute("""
                    SELECT id FROM folders 
                    WHERE user_id = %s AND parent_folder_id = %s AND name = %s
                """, (user_id, parent_folder_id, folder_data.name))
            else:
                cur.execute("""
                    SELECT id FROM folders 
                    WHERE user_id = %s AND parent_folder_id IS NULL AND name = %s
                """, (user_id, folder_data.name))
            
            if cur.fetchone():
                raise ValueError(f"Folder with name '{folder_data.name}' already exists in this location")
            
            # Insert folder
            cur.execute("""
                INSERT INTO folders (user_id, name, parent_folder_id, path, created_at, updated_at)
                VALUES (%s, %s, %s, '', NOW(), NOW())
                RETURNING id, user_id, name, parent_folder_id, path, created_at, updated_at
            """, (
                user_id,
                folder_data.name,
                parent_folder_id
            ))
            
            row = cur.fetchone()
            folder_id = row[0]
            
            # Calculate and update path
            path = calculate_folder_path(folder_id)
            cur.execute("UPDATE folders SET path = %s WHERE id = %s", (path, folder_id))
            
            conn.commit()
            
            return FolderInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                parent_folder_id=row[3],
                path=path,
                created_at=row[5],
                updated_at=row[6]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating folder: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_folder_by_id(folder_id: int, user_id: int) -> Optional[FolderInDB]:
    """
    Get a folder by ID, verifying it belongs to the user.
    
    Args:
        folder_id: Folder ID
        user_id: User ID for verification
        
    Returns:
        FolderInDB: Folder if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, user_id, name, parent_folder_id, path, created_at, updated_at
                FROM folders
                WHERE id = %s AND user_id = %s
            """, (folder_id, user_id))
            
            row = cur.fetchone()
            
            if not row:
                return None
            
            return FolderInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                parent_folder_id=row[3],
                path=row[4],
                created_at=row[5],
                updated_at=row[6]
            )
            
        except Exception as e:
            logger.error(f"Error getting folder: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_folders_by_user(user_id: int, parent_id: Optional[int] = None) -> List[FolderInDB]:
    """
    Get folders for a user, optionally filtered by parent.
    
    Args:
        user_id: User ID
        parent_id: Optional parent folder ID filter
        
    Returns:
        List[FolderInDB]: List of folders
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if parent_id is not None:
                cur.execute("""
                    SELECT id, user_id, name, parent_folder_id, path, created_at, updated_at
                    FROM folders
                    WHERE user_id = %s AND parent_folder_id = %s
                    ORDER BY name
                """, (user_id, parent_id))
            else:
                cur.execute("""
                    SELECT id, user_id, name, parent_folder_id, path, created_at, updated_at
                    FROM folders
                    WHERE user_id = %s
                    ORDER BY path, name
                """, (user_id,))
            
            rows = cur.fetchall()
            folders = []
            
            for row in rows:
                folders.append(FolderInDB(
                    id=row[0],
                    user_id=row[1],
                    name=row[2],
                    parent_folder_id=row[3],
                    path=row[4],
                    created_at=row[5],
                    updated_at=row[6]
                ))
            
            return folders
            
        except Exception as e:
            logger.error(f"Error getting folders: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_folder_tree(user_id: int) -> List[Dict[str, Any]]:
    """
    Get nested folder structure with files for a user.
    
    Args:
        user_id: User ID
        
    Returns:
        List[Dict]: Tree structure with folders and files
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Get all folders
            cur.execute("""
                SELECT id, user_id, name, parent_folder_id, path, created_at, updated_at
                FROM folders
                WHERE user_id = %s
                ORDER BY path, name
            """, (user_id,))
            
            folders = {}
            root_folders = []
            
            for row in cur.fetchall():
                folder = {
                    'id': row[0],
                    'user_id': row[1],
                    'name': row[2],
                    'parent_folder_id': row[3],
                    'path': row[4],
                    'created_at': row[5].isoformat() if row[5] else None,
                    'updated_at': row[6].isoformat() if row[6] else None,
                    'children': [],
                    'files': []
                }
                folders[row[0]] = folder
            
            # Get all files in folders
            cur.execute("""
                SELECT id, folder_id, filename, s3_key, file_type, file_format, 
                       size_bytes, checksum, uploaded_at, created_at
                FROM files
                WHERE folder_id IS NOT NULL AND folder_id IN (
                    SELECT id FROM folders WHERE user_id = %s
                )
                ORDER BY filename
            """, (user_id,))
            
            for row in cur.fetchall():
                file_data = {
                    'id': row[0],
                    'filename': row[2],
                    's3_key': row[3],
                    'file_type': row[4],
                    'file_format': row[5],
                    'size_bytes': row[6],
                    'checksum': row[7],
                    'uploaded_at': row[8].isoformat() if row[8] else None,
                    'created_at': row[9].isoformat() if row[9] else None
                }
                
                folder_id = row[1]
                if folder_id in folders:
                    folders[folder_id]['files'].append(file_data)
            
            # Build tree structure
            for folder_id, folder in folders.items():
                parent_id = folder['parent_folder_id']
                if parent_id is None:
                    root_folders.append(folder)
                elif parent_id in folders:
                    folders[parent_id]['children'].append(folder)
            
            return root_folders
            
        except Exception as e:
            logger.error(f"Error getting folder tree: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def update_folder(folder_id: int, user_id: int, folder_data: FolderUpdate) -> Optional[FolderInDB]:
    """
    Update a folder (rename or move).
    
    Args:
        folder_id: Folder ID
        user_id: User ID for verification
        folder_data: Folder update data
        
    Returns:
        FolderInDB: Updated folder, None if not found
        
    Raises:
        ValueError: If parent folder doesn't exist or creates circular reference
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify folder exists and belongs to user
            folder = get_folder_by_id(folder_id, user_id)
            if not folder:
                return None
            
            # Check for circular reference if moving
            if folder_data.parent_folder_id is not None:
                if folder_data.parent_folder_id == folder_id:
                    raise ValueError("Cannot move folder into itself")
                
                # Check if new parent is a descendant (would create cycle)
                cur.execute("""
                    WITH RECURSIVE descendants AS (
                        SELECT id, parent_folder_id FROM folders WHERE id = %s
                        UNION ALL
                        SELECT f.id, f.parent_folder_id 
                        FROM folders f
                        INNER JOIN descendants d ON f.parent_folder_id = d.id
                    )
                    SELECT id FROM descendants WHERE id = %s
                """, (folder_data.parent_folder_id, folder_id))
                
                if cur.fetchone():
                    raise ValueError("Cannot move folder into its own descendant")
                
                # Verify new parent exists and belongs to user
                cur.execute("SELECT id, user_id FROM folders WHERE id = %s", (folder_data.parent_folder_id,))
                parent_row = cur.fetchone()
                
                if not parent_row:
                    raise ValueError(f"Parent folder with id {folder_data.parent_folder_id} not found")
                
                if parent_row[1] != user_id:
                    raise ValueError("Parent folder belongs to a different user")
            
            # Check for duplicate name if renaming or moving
            new_name = folder_data.name if folder_data.name is not None else folder.name
            new_parent_id = folder_data.parent_folder_id if folder_data.parent_folder_id is not None else folder.parent_folder_id
            
            if new_parent_id:
                cur.execute("""
                    SELECT id FROM folders 
                    WHERE user_id = %s AND parent_folder_id = %s AND name = %s AND id != %s
                """, (user_id, new_parent_id, new_name, folder_id))
            else:
                cur.execute("""
                    SELECT id FROM folders 
                    WHERE user_id = %s AND parent_folder_id IS NULL AND name = %s AND id != %s
                """, (user_id, new_name, folder_id))
            
            if cur.fetchone():
                raise ValueError(f"Folder with name '{new_name}' already exists in this location")
            
            # Update folder
            update_fields = []
            params = []
            
            if folder_data.name is not None:
                update_fields.append("name = %s")
                params.append(folder_data.name)
            
            if folder_data.parent_folder_id is not None:
                update_fields.append("parent_folder_id = %s")
                params.append(folder_data.parent_folder_id)
            
            if update_fields:
                update_fields.append("updated_at = NOW()")
                params.append(folder_id)
                
                cur.execute(f"""
                    UPDATE folders 
                    SET {', '.join(update_fields)}
                    WHERE id = %s AND user_id = %s
                    RETURNING id, user_id, name, parent_folder_id, path, created_at, updated_at
                """, params + [user_id])
                
                row = cur.fetchone()
                
                if row:
                    # Recalculate path for this folder and all descendants
                    path = calculate_folder_path(folder_id)
                    cur.execute("UPDATE folders SET path = %s WHERE id = %s", (path, folder_id))
                    
                    # Recalculate paths for all descendants (simpler approach)
                    cur.execute("""
                        WITH RECURSIVE descendants AS (
                            SELECT id FROM folders WHERE id = %s
                            UNION ALL
                            SELECT f.id 
                            FROM folders f
                            INNER JOIN descendants d ON f.parent_folder_id = d.id
                        )
                        SELECT id FROM descendants
                    """, (folder_id,))
                    
                    descendant_ids = [row[0] for row in cur.fetchall()]
                    for desc_id in descendant_ids:
                        desc_path = calculate_folder_path(desc_id)
                        cur.execute("UPDATE folders SET path = %s WHERE id = %s", (desc_path, desc_id))
                    
                    conn.commit()
                    
                    return FolderInDB(
                        id=row[0],
                        user_id=row[1],
                        name=row[2],
                        parent_folder_id=row[3],
                        path=path,
                        created_at=row[5],
                        updated_at=row[6]
                    )
            
            return folder
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating folder: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def delete_folder(folder_id: int, user_id: int) -> bool:
    """
    Delete a folder and all its contents (cascade delete).
    
    This function:
    1. Recursively deletes all child folders (cascade)
    2. Deletes all files in the folder and its children
    3. Deletes the folder itself
    
    Args:
        folder_id: Folder ID
        user_id: User ID for verification
        
    Returns:
        bool: True if deleted, False if not found
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify folder exists and belongs to user
            folder = get_folder_by_id(folder_id, user_id)
            if not folder:
                return False
            
            # Get all descendant folder IDs (including self) using recursive CTE
            cur.execute("""
                WITH RECURSIVE folder_tree AS (
                    SELECT id FROM folders WHERE id = %s AND user_id = %s
                    UNION ALL
                    SELECT f.id FROM folders f
                    INNER JOIN folder_tree ft ON f.parent_folder_id = ft.id
                    WHERE f.user_id = %s
                )
                SELECT id FROM folder_tree
            """, (folder_id, user_id, user_id))
            
            folder_ids = [row[0] for row in cur.fetchall()]
            
            if not folder_ids:
                return False
            
            # Delete all files in these folders
            # First, get S3 keys for files that need to be deleted from MinIO
            cur.execute("""
                SELECT id, s3_key FROM files
                WHERE folder_id = ANY(%s)
            """, (folder_ids,))
            
            files_to_delete = cur.fetchall()
            
            # Import here to avoid circular dependency
            from backend.api.services.minio_client import get_minio_client
            from backend.api.services.user_service import get_user_by_id
            
            # Delete files from MinIO
            if files_to_delete:
                minio_client = get_minio_client()
                user = get_user_by_id(user_id)
                
                if not user:
                    logger.error(f"User {user_id} not found, cannot delete files from MinIO")
                    raise ValueError(f"User {user_id} not found")
                
                for file_id, s3_key in files_to_delete:
                    try:
                        minio_client.delete_file(
                            user_id=user_id,
                            s3_key=s3_key,
                            username=user.username
                        )
                    except Exception as e:
                        logger.warning(f"Failed to delete file {s3_key} from MinIO: {e}")
                        # Continue deleting other files even if one fails
            
            # Delete files from database
            cur.execute("""
                DELETE FROM files
                WHERE folder_id = ANY(%s)
            """, (folder_ids,))
            
            # Delete all folders (cascade will handle children via parent_folder_id constraint)
            # But we'll delete them explicitly in reverse order to be safe
            cur.execute("""
                DELETE FROM folders
                WHERE id = ANY(%s) AND user_id = %s
            """, (folder_ids, user_id))
            
            deleted = cur.rowcount > 0
            
            conn.commit()
            return deleted
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting folder: {e}", exc_info=True)
            raise
        finally:
            cur.close()

