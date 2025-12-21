"""
Pipeline service for managing user-created visual pipelines.

This module provides CRUD operations for pipelines stored in the database.
Pipelines are visual representations (nodes/edges) created using ReactFlow.
"""

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from backend.api.database.db_init import get_db_connection
from backend.api.models.pipeline_model import (
    PipelineCreate,
    PipelineUpdate,
    PipelineInDB
)

logger = logging.getLogger(__name__)


def _parse_jsonb_field(value: Any) -> List[Dict[str, Any]]:
    """
    Parse a JSONB field from database (could be list, dict, string, or None).
    Always returns a list for ReactFlow compatibility.
    
    Args:
        value: Raw value from database
        
    Returns:
        List[Dict[str, Any]]: Parsed list of nodes/edges
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else [parsed] if parsed else []
    if isinstance(value, dict):
        # Legacy format - convert to list
        return [value]
    return []


def create_pipeline(user_id: int, pipeline_data: PipelineCreate) -> PipelineInDB:
    """
    Create a new pipeline for a user.
    
    Args:
        user_id: ID of the user creating the pipeline
        pipeline_data: Pipeline creation data (name, description, nodes, edges)
        
    Returns:
        PipelineInDB: Created pipeline
        
    Raises:
        ValueError: If pipeline data is invalid
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Convert nodes and edges to JSON strings for JSONB storage
            # They are lists of dicts from ReactFlow
            nodes_json = json.dumps(pipeline_data.nodes) if pipeline_data.nodes else json.dumps([])
            edges_json = json.dumps(pipeline_data.edges) if pipeline_data.edges else json.dumps([])
            
            # Insert pipeline (is_shared defaults to false)
            cur.execute("""
                INSERT INTO pipelines (user_id, name, description, nodes, edges, saved_at, is_shared)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW(), false)
                RETURNING id, user_id, name, description, nodes, edges, saved_at, is_shared
            """, (
                user_id,
                pipeline_data.name,
                pipeline_data.description,
                nodes_json,
                edges_json
            ))
            
            row = cur.fetchone()
            conn.commit()
            
            pipeline = PipelineInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                description=row[3],
                nodes=_parse_jsonb_field(row[4]),
                edges=_parse_jsonb_field(row[5]),
                saved_at=row[6],
                is_shared=row[7] if len(row) > 7 else False
            )
            
            logger.info(f"Created pipeline {pipeline.id} for user {user_id}")
            return pipeline
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating pipeline: {e}", exc_info=True)
            raise ValueError(f"Failed to create pipeline: {str(e)}")
        finally:
            cur.close()


def get_pipeline_by_id(pipeline_id: int, user_id: int) -> Optional[PipelineInDB]:
    """
    Get a pipeline by ID, ensuring it belongs to the user or is shared.
    
    Args:
        pipeline_id: ID of the pipeline
        user_id: ID of the user (for authorization)
        
    Returns:
        Optional[PipelineInDB]: Pipeline if found and belongs to user or is shared, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, user_id, name, description, nodes, edges, saved_at, is_shared
                FROM pipelines
                WHERE id = %s AND (user_id = %s OR is_shared = true)
            """, (pipeline_id, user_id))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return PipelineInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                description=row[3],
                nodes=_parse_jsonb_field(row[4]),
                edges=_parse_jsonb_field(row[5]),
                saved_at=row[6],
                is_shared=row[7] if len(row) > 7 else False
            )
            
        except Exception as e:
            logger.error(f"Error getting pipeline {pipeline_id}: {e}", exc_info=True)
            return None
        finally:
            cur.close()


def get_pipeline_by_id_public(pipeline_id: int) -> Optional[PipelineInDB]:
    """
    Get a shared pipeline by ID (public access, no authentication required).
    
    Args:
        pipeline_id: ID of the pipeline
        
    Returns:
        Optional[PipelineInDB]: Pipeline if found and is shared, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, user_id, name, description, nodes, edges, saved_at, is_shared
                FROM pipelines
                WHERE id = %s AND is_shared = true
            """, (pipeline_id,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return PipelineInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                description=row[3],
                nodes=_parse_jsonb_field(row[4]),
                edges=_parse_jsonb_field(row[5]),
                saved_at=row[6],
                is_shared=row[7] if len(row) > 7 else False
            )
            
        except Exception as e:
            logger.error(f"Error getting shared pipeline {pipeline_id}: {e}", exc_info=True)
            return None
        finally:
            cur.close()


def get_pipelines_by_user(user_id: int) -> List[PipelineInDB]:
    """
    Get all pipelines for a user.
    
    Args:
        user_id: ID of the user
        
    Returns:
        List[PipelineInDB]: List of pipelines
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, user_id, name, description, nodes, edges, saved_at, is_shared
                FROM pipelines
                WHERE user_id = %s
                ORDER BY saved_at DESC
            """, (user_id,))
            
            pipelines = []
            for row in cur.fetchall():
                pipelines.append(PipelineInDB(
                    id=row[0],
                    user_id=row[1],
                    name=row[2],
                    description=row[3],
                    nodes=_parse_jsonb_field(row[4]),
                    edges=_parse_jsonb_field(row[5]),
                    saved_at=row[6],
                    is_shared=row[7] if len(row) > 7 else False
                ))
            
            return pipelines
            
        except Exception as e:
            logger.error(f"Error getting pipelines for user {user_id}: {e}", exc_info=True)
            return []
        finally:
            cur.close()


def update_pipeline(pipeline_id: int, user_id: int, update_data: PipelineUpdate) -> Optional[PipelineInDB]:
    """
    Update a pipeline.
    
    Args:
        pipeline_id: ID of the pipeline to update
        user_id: ID of the user (for authorization)
        update_data: Update data (only provided fields will be updated)
        
    Returns:
        Optional[PipelineInDB]: Updated pipeline if found, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Build update query dynamically based on provided fields
            updates = []
            params = []
            
            if update_data.name is not None:
                updates.append("name = %s")
                params.append(update_data.name)
            
            if update_data.description is not None:
                updates.append("description = %s")
                params.append(update_data.description)
            
            if update_data.nodes is not None:
                updates.append("nodes = %s::jsonb")
                nodes_json = json.dumps(update_data.nodes) if update_data.nodes else json.dumps([])
                params.append(nodes_json)
            
            if update_data.edges is not None:
                updates.append("edges = %s::jsonb")
                edges_json = json.dumps(update_data.edges) if update_data.edges else json.dumps([])
                params.append(edges_json)
            
            if update_data.is_shared is not None:
                updates.append("is_shared = %s")
                params.append(update_data.is_shared)
            
            if not updates:
                # No updates provided, just return existing pipeline
                return get_pipeline_by_id(pipeline_id, user_id)
            
            # Add WHERE clause params
            params.extend([pipeline_id, user_id])
            
            query = f"""
                UPDATE pipelines
                SET {', '.join(updates)}
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, name, description, nodes, edges, saved_at, is_shared
            """
            
            cur.execute(query, params)
            row = cur.fetchone()
            
            if not row:
                conn.rollback()
                return None
            
            conn.commit()
            
            pipeline = PipelineInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                description=row[3],
                nodes=_parse_jsonb_field(row[4]),
                edges=_parse_jsonb_field(row[5]),
                saved_at=row[6],
                is_shared=row[7] if len(row) > 7 else False
            )
            
            logger.info(f"Updated pipeline {pipeline_id} for user {user_id}")
            return pipeline
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating pipeline {pipeline_id}: {e}", exc_info=True)
            return None
        finally:
            cur.close()


def delete_pipeline(pipeline_id: int, user_id: int) -> bool:
    """
    Delete a pipeline.
    
    Args:
        pipeline_id: ID of the pipeline to delete
        user_id: ID of the user (for authorization)
        
    Returns:
        bool: True if deleted, False if not found or unauthorized
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                DELETE FROM pipelines
                WHERE id = %s AND user_id = %s
            """, (pipeline_id, user_id))
            
            deleted = cur.rowcount > 0
            conn.commit()
            
            if deleted:
                logger.info(f"Deleted pipeline {pipeline_id} for user {user_id}")
            
            return deleted
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting pipeline {pipeline_id}: {e}", exc_info=True)
            return False
        finally:
            cur.close()


def get_shared_pipelines() -> List[PipelineInDB]:
    """
    Get all shared pipelines (available to everyone).
    
    Returns:
        List[PipelineInDB]: List of shared pipelines
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, user_id, name, description, nodes, edges, saved_at, is_shared
                FROM pipelines
                WHERE is_shared = true
                ORDER BY saved_at DESC
            """)
            
            pipelines = []
            for row in cur.fetchall():
                pipelines.append(PipelineInDB(
                    id=row[0],
                    user_id=row[1],
                    name=row[2],
                    description=row[3],
                    nodes=_parse_jsonb_field(row[4]),
                    edges=_parse_jsonb_field(row[5]),
                    saved_at=row[6],
                    is_shared=row[7] if len(row) > 7 else False
                ))
            
            return pipelines
            
        except Exception as e:
            logger.error(f"Error getting shared pipelines: {e}", exc_info=True)
            return []
        finally:
            cur.close()


def share_pipeline(pipeline_id: int, user_id: int) -> Optional[PipelineInDB]:
    """
    Share a pipeline with the community.
    
    Args:
        pipeline_id: ID of the pipeline to share
        user_id: ID of the user (for authorization)
        
    Returns:
        Optional[PipelineInDB]: Updated pipeline if found, None otherwise
    """
    return update_pipeline(pipeline_id, user_id, PipelineUpdate(is_shared=True))


def unshare_pipeline(pipeline_id: int, user_id: int) -> Optional[PipelineInDB]:
    """
    Unshare a pipeline (make it private).
    
    Args:
        pipeline_id: ID of the pipeline to unshare
        user_id: ID of the user (for authorization)
        
    Returns:
        Optional[PipelineInDB]: Updated pipeline if found, None otherwise
    """
    return update_pipeline(pipeline_id, user_id, PipelineUpdate(is_shared=False))
