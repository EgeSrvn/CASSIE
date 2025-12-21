"""
Pipeline converter service.

Converts visual pipeline (nodes/edges) to tool_indices for Nextflow execution.
"""

import logging
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict, deque

from backend.api.models.pipeline_model import PipelineInDB
from emulation.nextflow_manager import AVAILABLE_TOOLS

logger = logging.getLogger(__name__)


# Mapping from node labels (as they appear in ReactFlow) to tool IDs
NODE_LABEL_TO_TOOL_ID = {
    "Read Quality (FastQC)": "FASTQC",
    "Genomic Property Estimation (GenomeScope2)": "GENOMESCOPE2",
    "Assembly (Spades)": "SPADES",
    "Quality Assessment for Assembly (QUAST)": "QUAST",
    # Also support shorter names
    "FastQC": "FASTQC",
    "GenomeScope2": "GENOMESCOPE2",
    "SPAdes": "SPADES",
    "Spades": "SPADES",
    "QUAST": "QUAST",
    "Quast": "QUAST",
}


def get_tool_index_by_id(tool_id: str) -> Optional[int]:
    """
    Get the index of a tool in AVAILABLE_TOOLS by its ID.
    
    Args:
        tool_id: Tool ID (e.g., "FASTQC", "SPADES")
        
    Returns:
        Optional[int]: Tool index if found, None otherwise
    """
    for idx, tool in enumerate(AVAILABLE_TOOLS):
        if tool["id"] == tool_id:
            return idx
    return None


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
            node_label = node_data.get("label") if isinstance(node_data, dict) else str(node_data)
        else:
            # Assume object with attributes
            node_id = getattr(node, "id", None) or getattr(node, "nodeId", None)
            node_type = getattr(node, "type", None) or getattr(node, "nodeType", None)
            node_data = getattr(node, "data", node)
            node_label = getattr(node_data, "label", None) if hasattr(node_data, "label") else str(node_data)
        
        # Only include tool nodes (not input/output nodes)
        if node_type in ("tool", "process") or (node_type not in ("input", "inputNode", "start", "end", "output")):
            if node_id:
                tool_nodes[node_id] = {
                    "id": node_id,
                    "type": node_type,
                    "label": node_label,
                    "data": node_data
                }
    
    return tool_nodes


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


def convert_pipeline_to_tool_indices(pipeline: PipelineInDB) -> List[int]:
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
        
        # Topological sort to determine execution order
        ordered_node_ids = topological_sort_tools(tool_nodes, edges)
        
        # Map node labels to tool IDs, then to tool indices
        tool_indices = []
        unmapped_nodes = []
        
        for node_id in ordered_node_ids:
            node = tool_nodes[node_id]
            node_label = node.get("label", "")
            
            # Try to map label to tool ID
            tool_id = None
            for label_pattern, tool_id_candidate in NODE_LABEL_TO_TOOL_ID.items():
                if label_pattern.lower() in node_label.lower():
                    tool_id = tool_id_candidate
                    break
            
            if not tool_id:
                # Try direct match on node label
                tool_id = NODE_LABEL_TO_TOOL_ID.get(node_label)
            
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

