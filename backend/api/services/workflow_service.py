"""
Workflow service for creating workflows dynamically from tool selection.
"""

import json
from typing import List, Optional
from backend.api.database.db_init import get_db_connection
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_index

logger = get_logger(__name__)


def order_tools_by_dependencies(
    tool_indices: List[int],
    has_reference_file: bool = False,
    has_paired_end_reads: bool = False,
    has_assembly_file: bool = False,
) -> List[int]:
    """
    Automatically order tools based on their dependencies.

    IMPORTANT:
    - We are now *permissive*: we do NOT block tools based on input files.
    - If inputs are missing or incompatible, the Nextflow pipeline / tools
      themselves will fail at runtime.
    - The only thing this function does is:
        * keep the selected tools
        * order them: QC → SPAdes → QUAST → others
    """
    if not tool_indices:
        return []

    # Map tool indices to IDs
    tool_map = {}
    for idx in tool_indices:
        tool = get_tool_by_index(idx)
        if tool:
            tool_map[idx] = tool["id"]

    # If somehow none of the indices resolved to a known tool, just return original
    if not tool_map:
        return tool_indices

    # Categorize tools
    qc_ids = {"FASTQC", "GENOMESCOPE2"}
    qc_tools: List[int] = []
    spades_idx: Optional[int] = None
    quast_idx: Optional[int] = None
    others: List[int] = []

    for idx in tool_indices:
        tool_id = tool_map.get(idx)
        if tool_id in qc_ids:
            qc_tools.append(idx)
        elif tool_id == "SPADES":
            spades_idx = idx
        elif tool_id == "QUAST":
            quast_idx = idx
        else:
            others.append(idx)

    # Build ordered list: QC tools → SPAdes → QUAST → others
    ordered: List[int] = []
    ordered.extend(qc_tools)
    if spades_idx is not None:
        ordered.append(spades_idx)
    if quast_idx is not None:
        ordered.append(quast_idx)
    ordered.extend(others)

    # Safety: if something weird happens, fall back to original order
    if len(ordered) != len(tool_indices):
        logger.warning(
            f"Tool ordering mismatch, falling back to original: "
            f"{[tool_map.get(i) for i in tool_indices]} → "
            f"{[tool_map.get(i) for i in ordered]}"
        )
        return tool_indices

    return ordered


def create_workflow_from_tools(
    tool_indices: List[int],
    user_id: Optional[int] = None,
    workflow_name: Optional[str] = None,
    has_reference_file: bool = False,
    has_paired_end_reads: bool = False,
    has_assembly_file: bool = False
) -> int:
    """
    Create a workflow dynamically from selected tool indices.
    Tools are automatically ordered based on dependencies.
    
    Args:
        tool_indices: List of tool indices (e.g., [0] for FastQC)
        user_id: Optional user ID (for custom workflows)
        workflow_name: Optional custom workflow name
        has_reference_file: Whether a reference genome file is provided (for QUAST)
        has_paired_end_reads: Whether paired-end reads (2 FASTQ files) are provided (for SPAdes)
        has_assembly_file: Whether an assembly file (FASTA) is provided directly (for QUAST without SPAdes)
        
    Returns:
        int: Created workflow ID
        
    Raises:
        ValueError: If tool indices are invalid
    """
    if not tool_indices:
        raise ValueError("At least one tool must be selected")
    
    # Automatically order tools based on dependencies
    ordered_indices = order_tools_by_dependencies(tool_indices, has_reference_file, has_paired_end_reads, has_assembly_file)
    if not ordered_indices:
        raise ValueError("No valid tools remaining after dependency filtering")
    
    # Use ordered indices for workflow creation
    tool_indices = ordered_indices
    
    # Validate tool indices
    tool_names = []
    tool_descriptions = []
    for idx in tool_indices:
        tool = get_tool_by_index(idx)
        if not tool:
            raise ValueError(f"Invalid tool index: {idx}")
        tool_names.append(tool["name"].lower())
        tool_descriptions.append(tool["description"])
    
    # Generate workflow name if not provided
    if not workflow_name:
        if len(tool_names) == 1:
            workflow_name = f"{tool_names[0].title()} Analysis"
        else:
            workflow_name = f"{' + '.join([t.title() for t in tool_names])} Pipeline"
    
    # Generate workflow description
    description = f"Pipeline using: {', '.join(tool_descriptions)}"
    
    # Generate workflow content (placeholder - actual execution uses dynamic generation)
    workflow_content = f"# Dynamically generated workflow\n# Tools: {', '.join(tool_names)}\n# This workflow is generated from tool selection"
    
    # Create workflow steps
    workflow_steps = []
    for i, idx in enumerate(tool_indices):
        tool = get_tool_by_index(idx)
        if not tool:
            raise ValueError(f"Invalid tool index: {idx}")
        workflow_steps.append({
            "step": i + 1,
            "name": tool["name"],
            "tool": tool["id"],
            "type": tool["type"]
        })
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Always create a new workflow (don't reuse existing ones)
            tools_used_json = json.dumps(tool_names)
            
            # Use job name if provided to make workflow name unique
            # Otherwise use the generated workflow name
            final_workflow_name = workflow_name
            
            cur.execute("""
                INSERT INTO workflows (
                    name, description, workflow_type, workflow_content,
                    tools_used, workflow_steps, parameters_schema,
                    user_id, is_public, is_active, validation_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                final_workflow_name,
                description,
                "custom" if user_id else "predefined",
                workflow_content,
                tools_used_json,  # tools_used as JSONB
                json.dumps(workflow_steps),  # workflow_steps as JSONB
                json.dumps({
                    "input": {
                        "type": "string",
                        "required": True,
                        "description": "Input file path"
                    }
                }),  # parameters_schema as JSONB
                user_id,  # user_id
                False,  # is_public (custom workflows are private by default)
                True,  # is_active
                "valid"  # validation_status
            ))
            
            workflow_id = cur.fetchone()[0]
            conn.commit()
            
            logger.info(f"Created workflow {workflow_id} from tools: {tool_indices}")
            return workflow_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating workflow from tools: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_workflow_by_id(workflow_id: int, user_id: Optional[int] = None) -> Optional[dict]:
    """
    Get a workflow by ID.
    
    Args:
        workflow_id: Workflow ID
        user_id: Optional user ID to verify ownership (for custom workflows)
        
    Returns:
        dict: Workflow data with keys: id, name, tools_used, workflow_steps, etc.
        None: If workflow not found or user doesn't have access
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Build query with optional user_id check
            if user_id:
                cur.execute("""
                    SELECT id, name, description, workflow_type, workflow_content,
                           tools_used, workflow_steps, parameters_schema,
                           user_id, is_public, is_active, validation_status
                    FROM workflows
                    WHERE id = %s AND (user_id = %s OR is_public = true)
                """, (workflow_id, user_id))
            else:
                cur.execute("""
                    SELECT id, name, description, workflow_type, workflow_content,
                           tools_used, workflow_steps, parameters_schema,
                           user_id, is_public, is_active, validation_status
                    FROM workflows
                    WHERE id = %s
                """, (workflow_id,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            # Parse JSONB fields
            tools_used = row[5] if row[5] else []
            workflow_steps = row[6] if row[6] else []
            parameters_schema = row[7] if row[7] else {}
            
            # Convert JSONB to Python objects if they're strings
            if isinstance(tools_used, str):
                tools_used = json.loads(tools_used)
            if isinstance(workflow_steps, str):
                workflow_steps = json.loads(workflow_steps)
            if isinstance(parameters_schema, str):
                parameters_schema = json.loads(parameters_schema)
            
            return {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "workflow_type": row[3],
                "workflow_content": row[4],
                "tools_used": tools_used,
                "workflow_steps": workflow_steps,
                "parameters_schema": parameters_schema,
                "user_id": row[8],
                "is_public": row[9],
                "is_active": row[10],
                "validation_status": row[11]
            }
            
        except Exception as e:
            logger.error(f"Error getting workflow {workflow_id}: {e}", exc_info=True)
            return None
        finally:
            cur.close()
