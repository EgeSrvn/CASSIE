"""
Workflow service for creating workflows dynamically from tool selection.
"""

import json
from typing import Any, Dict, List, Optional

from backend.api.database.db_init import get_db_connection
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_index, tool_produces_requirement

logger = get_logger(__name__)


def order_tools_by_dependencies(
    tool_indices: List[int],
    has_reference_file: bool = False,
    has_paired_end_reads: bool = False,
    has_assembly_file: bool = False,
    preferred_tool_order: Optional[List[int]] = None,
) -> List[int]:
    """
    Order tools by inferred dependencies while preserving user order inside equal-priority sets.
    """
    if not tool_indices:
        return []

    tool_map: Dict[int, Dict[str, Any]] = {}
    tool_id_map: Dict[int, str] = {}
    for idx in tool_indices:
        tool = get_tool_by_index(idx)
        if tool:
            tool_map[idx] = tool
            tool_id_map[idx] = tool["id"]

    if not tool_map:
        return tool_indices

    dependencies: Dict[int, set[int]] = {idx: set() for idx in tool_map}
    dependents: Dict[int, set[int]] = {idx: set() for idx in tool_map}
    input_positions = {tool_index: position for position, tool_index in enumerate(tool_indices)}
    preferred_positions = {tool_index: position for position, tool_index in enumerate(preferred_tool_order or [])}

    for idx, tool in tool_map.items():
        for requirement in tool.get("input_requirements", []) or []:
            requirement_type = str(requirement.get("type") or "").strip().lower()
            if not requirement_type:
                continue
            for candidate_idx, candidate_tool in tool_map.items():
                if candidate_idx == idx:
                    continue
                if tool_produces_requirement(candidate_tool, requirement_type):
                    dependencies[idx].add(candidate_idx)
                    dependents[candidate_idx].add(idx)

    in_degree = {idx: len(dependencies[idx]) for idx in tool_map}
    ready = [idx for idx, degree in in_degree.items() if degree == 0]

    def sort_key(tool_index: int) -> tuple:
        return (
            preferred_positions.get(tool_index, 10_000),
            input_positions.get(tool_index, 10_000),
            tool_id_map.get(tool_index, ""),
            tool_index,
        )

    ready.sort(key=sort_key)
    ordered: List[int] = []

    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for dependent in sorted(dependents.get(current, set()), key=sort_key):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
        ready.sort(key=sort_key)

    remaining = [idx for idx in tool_indices if idx not in ordered]
    if remaining:
        logger.warning(
            "Dependency-aware tool ordering left unresolved tools; appending remaining items: %s",
            remaining,
        )
        ordered.extend(sorted(remaining, key=sort_key))

    return ordered


def create_workflow_from_tools(
    tool_indices: List[int],
    user_id: Optional[int] = None,
    workflow_name: Optional[str] = None,
    has_reference_file: bool = False,
    has_paired_end_reads: bool = False,
    has_assembly_file: bool = False,
    preferred_tool_order: Optional[List[int]] = None,
) -> int:
    """
    Create a workflow dynamically from selected tool indices.
    Tools are automatically ordered based on dependencies.
    """
    if not tool_indices:
        raise ValueError("At least one tool must be selected")

    ordered_indices = order_tools_by_dependencies(
        tool_indices,
        has_reference_file,
        has_paired_end_reads,
        has_assembly_file,
        preferred_tool_order=preferred_tool_order,
    )
    if not ordered_indices:
        raise ValueError("No valid tools remaining after dependency filtering")

    tool_indices = ordered_indices

    tool_names = []
    tool_descriptions = []
    for idx in tool_indices:
        tool = get_tool_by_index(idx)
        if not tool:
            raise ValueError(f"Invalid tool index: {idx}")
        tool_names.append(tool["name"].lower())
        tool_descriptions.append(tool["description"])

    if not workflow_name:
        if len(tool_names) == 1:
            workflow_name = f"{tool_names[0].title()} Analysis"
        else:
            workflow_name = f"{' + '.join([t.title() for t in tool_names])} Pipeline"

    description = f"Pipeline using: {', '.join(tool_descriptions)}"
    workflow_content = f"# Dynamically generated workflow\n# Tools: {', '.join(tool_names)}\n# This workflow is generated from tool selection"

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
            tools_used_json = json.dumps(tool_names)
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
                tools_used_json,
                json.dumps(workflow_steps),
                json.dumps({
                    "input": {
                        "type": "string",
                        "required": True,
                        "description": "Input file path"
                    }
                }),
                user_id,
                False,
                True,
                "valid"
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
    """
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
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

            tools_used = row[5] if row[5] else []
            workflow_steps = row[6] if row[6] else []
            parameters_schema = row[7] if row[7] else {}

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
                "validation_status": row[11],
            }

        except Exception as e:
            logger.error(f"Error getting workflow {workflow_id}: {e}", exc_info=True)
            raise
        finally:
            cur.close()
