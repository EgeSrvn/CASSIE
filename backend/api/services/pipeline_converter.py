"""
Pipeline converter service.

Converts visual pipeline (nodes/edges) to tool_indices for Nextflow execution.
"""

import logging
from typing import List, Dict, Any, Optional
from collections import defaultdict, deque

from backend.api.models.pipeline_model import PipelineInDB
from tool_registry import get_tool_id_from_label, get_tool_index_by_id

logger = logging.getLogger(__name__)

NON_TOOL_NODE_TYPES = {
    "input",
    "inputnode",
    "start",
    "end",
    "output",
    "result",
    "fastqinput",
    "fastainput",
    "checkpoint",
}

STAGE_NODE_TYPES = {"tool", "checkpoint"}
RESULT_NODE_TYPES = {"result", "end"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _resolve_node_data(node: Any) -> Dict[str, Any]:
    if isinstance(node, dict):
        node_data = node.get("data")
        return node_data if isinstance(node_data, dict) else node
    raw_data = getattr(node, "data", None)
    if isinstance(raw_data, dict):
        return raw_data
    return {}


def resolve_node_label(node: Any) -> str:
    node_data = _resolve_node_data(node)
    if node_data:
        return _normalize_text(node_data.get("label"))
    if isinstance(node, dict):
        return _normalize_text(node.get("label"))
    return _normalize_text(getattr(node, "label", ""))


def resolve_node_tool_id(node: Any) -> Optional[str]:
    node_data = _resolve_node_data(node)
    explicit_tool_id = _normalize_text(node_data.get("toolId") or node_data.get("tool_id"))
    if explicit_tool_id:
        return explicit_tool_id.upper()

    if isinstance(node, dict):
        fallback_tool_id = _normalize_text(node.get("toolId") or node.get("tool_id"))
        if fallback_tool_id:
            return fallback_tool_id.upper()

    label = resolve_node_label(node)
    mapped_tool_id = get_tool_id_from_label(label)
    return mapped_tool_id.upper() if mapped_tool_id else None


def extract_tool_nodes(nodes: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Extract tool nodes from ReactFlow nodes structure.
    
    Args:
        nodes: ReactFlow nodes (can be dict with "nodes" key or list)
        
    Returns:
        Dict[str, Dict]: Map of node ID to node data for tool nodes only
    """
    # Handle different node structures
    if isinstance(nodes, dict):
        if "nodes" in nodes:
            node_list = nodes["nodes"]
        elif "data" in nodes:
            node_list = nodes["data"]
        else:
            # Assume it's a dict mapping node IDs to node data
            node_list = list(nodes.values())
    elif isinstance(nodes, list):
        node_list = nodes
    else:
        logger.warning(f"Unexpected nodes structure: {type(nodes)}")
        return {}
    
    tool_nodes = {}
    for node in node_list:
        # Handle both dict and object-like structures
        if isinstance(node, dict):
            node_id = node.get("id") or node.get("nodeId")
            node_type = node.get("type") or node.get("nodeType")
            node_data = node.get("data") or node
            node_label = resolve_node_label(node)
        else:
            # Assume object with attributes
            node_id = getattr(node, "id", None) or getattr(node, "nodeId", None)
            node_type = getattr(node, "type", None) or getattr(node, "nodeType", None)
            node_data = getattr(node, "data", node)
            node_label = resolve_node_label(node)
        
        # Only include tool nodes (not input/output nodes)
        normalized_type = str(node_type or "").strip().lower()
        if normalized_type in ("tool", "process") or normalized_type not in NON_TOOL_NODE_TYPES:
            if node_id:
                tool_nodes[node_id] = {
                    "id": node_id,
                    "type": node_type,
                    "label": node_label,
                    "data": node_data
                }
    
    return tool_nodes


def extract_stage_nodes(nodes: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Extract runnable stage nodes from ReactFlow nodes structure.

    This includes tool nodes plus checkpoint nodes, while excluding
    input/result/helper nodes.
    """
    if isinstance(nodes, dict):
        if "nodes" in nodes:
            node_list = nodes["nodes"]
        elif "data" in nodes:
            node_list = nodes["data"]
        else:
            node_list = list(nodes.values())
    elif isinstance(nodes, list):
        node_list = nodes
    else:
        logger.warning(f"Unexpected nodes structure: {type(nodes)}")
        return {}

    stage_nodes = {}
    for node in node_list:
        if isinstance(node, dict):
            node_id = node.get("id") or node.get("nodeId")
            node_type = str(node.get("type") or node.get("nodeType") or "").strip().lower()
            node_data = node.get("data") or node
            node_label = resolve_node_label(node)
        else:
            node_id = getattr(node, "id", None) or getattr(node, "nodeId", None)
            node_type = str(getattr(node, "type", None) or getattr(node, "nodeType", None) or "").strip().lower()
            node_data = getattr(node, "data", node)
            node_label = resolve_node_label(node)

        if node_id and node_type in STAGE_NODE_TYPES:
            stage_nodes[str(node_id)] = {
                "id": str(node_id),
                "type": node_type,
                "label": node_label,
                "data": node_data,
            }

    return stage_nodes


def build_stage_result_label_map(nodes: Any, edges: Any) -> Dict[str, List[str]]:
    node_list: List[Dict[str, Any]]
    if isinstance(nodes, dict):
        if "nodes" in nodes:
            node_list = [node for node in nodes["nodes"] if isinstance(node, dict)]
        elif "data" in nodes:
            node_list = [node for node in nodes["data"] if isinstance(node, dict)]
        else:
            node_list = [node for node in nodes.values() if isinstance(node, dict)]
    elif isinstance(nodes, list):
        node_list = [node for node in nodes if isinstance(node, dict)]
    else:
        return {}

    result_labels_by_node_id = {
        str(node.get("id") or ""): resolve_node_label(node) or "Result Block"
        for node in node_list
        if str(node.get("type") or node.get("nodeType") or "").strip().lower() in RESULT_NODE_TYPES
        and str(node.get("id") or "").strip()
    }
    if not result_labels_by_node_id:
        return {}

    result_map: Dict[str, List[str]] = {}
    for edge in extract_edges(edges):
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        result_label = result_labels_by_node_id.get(target)
        if not source or not result_label:
            continue
        stage_result_labels = result_map.setdefault(source, [])
        if result_label not in stage_result_labels:
            stage_result_labels.append(result_label)
    return result_map


def extract_edges(edges: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract edges from ReactFlow edges structure.
    
    Args:
        edges: ReactFlow edges (can be dict with "edges" key or list)
        
    Returns:
        List[Dict]: List of edges with source and target
    """
    # Handle different edge structures
    if isinstance(edges, dict):
        if "edges" in edges:
            edge_list = edges["edges"]
        elif "data" in edges:
            edge_list = edges["data"]
        else:
            edge_list = list(edges.values())
    elif isinstance(edges, list):
        edge_list = edges
    else:
        logger.warning(f"Unexpected edges structure: {type(edges)}")
        return []
    
    extracted_edges = []
    for edge in edge_list:
        if isinstance(edge, dict):
            source = edge.get("source") or edge.get("from")
            target = edge.get("target") or edge.get("to")
        else:
            source = getattr(edge, "source", None) or getattr(edge, "from", None)
            target = getattr(edge, "target", None) or getattr(edge, "to", None)
        
        if source and target:
            extracted_edges.append({"source": str(source), "target": str(target)})
    
    return extracted_edges


def topological_sort_tools(tool_nodes: Dict[str, Dict[str, Any]], edges: List[Dict[str, str]]) -> List[str]:
    """
    Perform topological sort on tool nodes based on edges to determine execution order.
    
    Args:
        tool_nodes: Map of node ID to node data
        edges: List of edges with source and target
        
    Returns:
        List[str]: Ordered list of node IDs
    """
    # Build graph: node_id -> set of nodes that come after it
    graph = defaultdict(set)
    in_degree = defaultdict(int)
    node_ids = set(tool_nodes.keys())
    
    # Initialize in-degree for all nodes
    for node_id in node_ids:
        in_degree[node_id] = 0
    
    # Build graph from edges (only include edges between tool nodes)
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        
        # Only process edges between tool nodes
        if source in node_ids and target in node_ids:
            if target not in graph[source]:
                graph[source].add(target)
                in_degree[target] += 1
    
    # Kahn's algorithm for topological sort
    queue = deque([node_id for node_id in node_ids if in_degree[node_id] == 0])
    result = []
    
    while queue:
        node_id = queue.popleft()
        result.append(node_id)
        
        for neighbor in graph[node_id]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    # Add any remaining nodes (disconnected components)
    remaining = node_ids - set(result)
    result.extend(remaining)
    
    return result


def compute_tool_priority_levels(
    tool_nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, str]],
) -> Dict[str, int]:
    """Compute longest-path priority level for each tool node."""
    node_ids = set(tool_nodes.keys())
    dependencies = {node_id: set() for node_id in node_ids}
    dependents = {node_id: set() for node_id in node_ids}

    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if source in node_ids and target in node_ids:
            dependencies[target].add(source)
            dependents[source].add(target)

    in_degree = {node_id: len(dependencies[node_id]) for node_id in node_ids}
    levels = {node_id: 0 for node_id in node_ids}
    queue = deque(sorted([node_id for node_id, degree in in_degree.items() if degree == 0]))

    while queue:
        node_id = queue.popleft()
        current_level = levels.get(node_id, 0)
        for dependent in sorted(dependents.get(node_id, set())):
            levels[dependent] = max(levels.get(dependent, 0), current_level + 1)
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    return levels


def sort_tool_nodes_by_priority(
    tool_nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, str]],
    priority_overrides: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    Return tool node ids ordered by dependency level and user-defined within-level order.
    """
    if not tool_nodes:
        return []

    ordered_node_ids = topological_sort_tools(tool_nodes, edges)
    topological_position = {node_id: index for index, node_id in enumerate(ordered_node_ids)}
    levels = compute_tool_priority_levels(tool_nodes, edges)

    override_index_by_priority: Dict[int, Dict[str, int]] = {}
    for group in priority_overrides or []:
        if not isinstance(group, dict):
            continue
        try:
            priority_value = int(group.get("priority"))
        except (TypeError, ValueError):
            continue
        ordered_ids = group.get("ordered_node_ids") or []
        if not isinstance(ordered_ids, list):
            continue
        override_index_by_priority[priority_value] = {
            str(node_id): index
            for index, node_id in enumerate(ordered_ids)
            if str(node_id).strip()
        }

    def _saved_priority_order(node_id: str) -> int:
        node_data = tool_nodes.get(node_id, {}).get("data") or {}
        raw_value = node_data.get("priorityOrder")
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return 10_000

    def _sort_key(node_id: str) -> tuple:
        level = int(levels.get(node_id, 0))
        override_index = override_index_by_priority.get(level, {}).get(node_id, 10_000)
        return (
            level,
            override_index,
            _saved_priority_order(node_id),
            topological_position.get(node_id, 10_000),
            str(tool_nodes.get(node_id, {}).get("label") or ""),
            node_id,
        )

    return sorted(tool_nodes.keys(), key=_sort_key)


def convert_pipeline_to_tool_indices(
    pipeline: PipelineInDB,
    priority_overrides: Optional[List[Dict[str, Any]]] = None,
) -> List[int]:
    """
    Convert pipeline nodes/edges to tool_indices for Nextflow execution.
    
    Args:
        pipeline: Pipeline with nodes and edges
        
    Returns:
        List[int]: Ordered list of tool indices
        
    Raises:
        ValueError: If pipeline structure is invalid or tools cannot be mapped
    """
    try:
        # Extract tool nodes
        tool_nodes = extract_tool_nodes(pipeline.nodes)
        
        if not tool_nodes:
            raise ValueError("Pipeline contains no tool nodes")
        
        # Extract edges
        edges = extract_edges(pipeline.edges)
        
        # Determine execution order using the same priority-aware sort used at runtime.
        ordered_node_ids = sort_tool_nodes_by_priority(
            tool_nodes,
            edges,
            priority_overrides=priority_overrides,
        )
        
        # Map node tool identifiers to tool indices
        tool_indices = []
        unmapped_nodes = []
        
        for node_id in ordered_node_ids:
            node = tool_nodes[node_id]
            node_label = resolve_node_label(node)
            tool_id = resolve_node_tool_id(node)
            if not tool_id:
                unmapped_nodes.append(node_label)
                continue
            
            # Get tool index
            tool_index = get_tool_index_by_id(tool_id)
            if tool_index is None:
                unmapped_nodes.append(f"{node_label} (ID: {tool_id})")
                continue
            
            # Avoid duplicates (keep first occurrence)
            if tool_index not in tool_indices:
                tool_indices.append(tool_index)
        
        if unmapped_nodes:
            logger.warning(f"Could not map some nodes to tools: {unmapped_nodes}")
            if not tool_indices:
                raise ValueError(f"Could not map any nodes to tools. Unmapped: {unmapped_nodes}")
        
        if not tool_indices:
            raise ValueError("No valid tools found in pipeline")
        
        logger.info(f"Converted pipeline {pipeline.id} to tool_indices: {tool_indices}")
        return tool_indices
        
    except Exception as e:
        logger.error(f"Error converting pipeline {pipeline.id} to tool_indices: {e}", exc_info=True)
        raise ValueError(f"Failed to convert pipeline to tool indices: {str(e)}")
