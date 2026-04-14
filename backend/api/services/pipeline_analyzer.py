"""
Pipeline analyzer service.

Analyzes pipeline graphs to determine input requirements for job creation.
"""

import logging
from typing import List, Dict, Any

from backend.api.models.pipeline_model import PipelineInDB
from tool_registry import (
    get_tool_by_id,
    get_tool_id_from_label,
    get_tool_requirements,
    tool_produces_requirement,
)

logger = logging.getLogger(__name__)


def _get_node_list(nodes: Any) -> List[Dict[str, Any]]:
    if isinstance(nodes, dict):
        if "nodes" in nodes:
            raw_nodes = nodes["nodes"]
        else:
            raw_nodes = list(nodes.values())
    elif isinstance(nodes, list):
        raw_nodes = nodes
    else:
        return []

    normalized_nodes: List[Dict[str, Any]] = []
    for node in raw_nodes:
        if isinstance(node, dict):
            normalized_nodes.append(node)
    return normalized_nodes


def _get_edge_list(edges: Any) -> List[Dict[str, str]]:
    if isinstance(edges, dict):
        if "edges" in edges:
            raw_edges = edges["edges"]
        else:
            raw_edges = list(edges.values())
    elif isinstance(edges, list):
        raw_edges = edges
    else:
        return []

    normalized_edges: List[Dict[str, str]] = []
    for edge in raw_edges:
        if isinstance(edge, dict) and edge.get("source") and edge.get("target"):
            normalized_edges.append({
                "source": str(edge["source"]),
                "target": str(edge["target"]),
            })
    return normalized_edges


def _normalize_label(value: Any) -> str:
    return str(value or "").strip()


def _resolve_node_type(node: Dict[str, Any]) -> str:
    return str(node.get("type") or node.get("nodeType") or "").strip()


def _resolve_node_label(node: Dict[str, Any]) -> str:
    node_data = node.get("data") or node
    if isinstance(node_data, dict):
        return _normalize_label(node_data.get("label"))
    return _normalize_label(node_data)


def _classify_explicit_input(node: Dict[str, Any]) -> Dict[str, Any] | None:
    node_type = _resolve_node_type(node).lower()
    if node_type not in {"fastqinput", "fastainput", "input", "inputnode", "start"}:
        return None

    label = _resolve_node_label(node)
    description = node.get("data", {}).get("description") if isinstance(node.get("data"), dict) else None
    description_text = " ".join(description or []).lower()
    label_lower = label.lower()

    if node_type == "fastqinput" or "fastq" in label_lower or "fastq" in description_text:
        return {"type": "fastq_input", "formats": ["fastq"]}
    if node_type == "fastainput" or "fasta" in label_lower or "fasta" in description_text or "reference" in label_lower:
        return {"type": "fasta_input", "formats": ["fasta"]}
    if "gff" in label_lower or "gtf" in label_lower or "annotation" in label_lower:
        return {"type": "annotation_input", "formats": ["gff", "gff3", "gtf"]}
    if "hal" in label_lower:
        return {"type": "hal_input", "formats": ["hal"]}
    if "meryl" in label_lower:
        return {"type": "meryl_input", "formats": ["meryl"]}
    if "text" in label_lower or "txt" in label_lower or "name" in label_lower or "config" in label_lower:
        return {"type": "text_input", "formats": ["txt"]}
    return None


def extract_input_nodes(pipeline: PipelineInDB) -> List[Dict[str, Any]]:
    """
    Extract input nodes from pipeline graph.
    
    Args:
        pipeline: Pipeline with nodes and edges
        
    Returns:
        List[Dict]: List of input node information
    """
    node_list = _get_node_list(pipeline.nodes)
    
    input_nodes = []
    for node in node_list:
        node_type = _resolve_node_type(node)
        node_label = _resolve_node_label(node)
        
        if node_type in ("input", "inputNode", "start"):
            input_nodes.append({
                "id": node.get("id") if isinstance(node, dict) else getattr(node, "id", None),
                "label": node_label,
                "type": node_type
            })
    
    return input_nodes


def analyze_pipeline_requirements(pipeline: PipelineInDB) -> Dict[str, Any]:
    """
    Analyze pipeline to determine input file requirements.
    
    Args:
        pipeline: Pipeline to analyze
        
    Returns:
        Dict with:
            - input_requirements: List of required inputs with types
            - tools: List of tools in the pipeline
            - has_spades: Whether SPAdes is in the pipeline
            - has_quast: Whether QUAST is in the pipeline
    """
    node_list = _get_node_list(pipeline.nodes)
    edge_list = _get_edge_list(pipeline.edges)
    nodes_by_id = {
        str(node.get("id")): node
        for node in node_list
        if isinstance(node, dict) and node.get("id") is not None
    }
    outgoing_edges: Dict[str, List[str]] = {}
    incoming_edges: Dict[str, List[str]] = {}
    for edge in edge_list:
        outgoing_edges.setdefault(edge["source"], []).append(edge["target"])
        incoming_edges.setdefault(edge["target"], []).append(edge["source"])
    
    # Find tools in pipeline
    tools_in_pipeline = set()
    ordered_tools_in_pipeline: List[str] = []
    tool_requirement_entries: List[Dict[str, Any]] = []
    for node in node_list:
        node_type = _resolve_node_type(node)
        node_label = _resolve_node_label(node)
        
        if node_type == "tool":
            tool_id = get_tool_id_from_label(node_label)
            if tool_id:
                tools_in_pipeline.add(tool_id)
                if tool_id not in ordered_tools_in_pipeline:
                    ordered_tools_in_pipeline.append(tool_id)

                node_id = str(node.get("id") or "")
                upstream_tool_ids = {
                    upstream_tool_id
                    for source_id in incoming_edges.get(node_id, [])
                    for upstream_node in [nodes_by_id.get(source_id)]
                    if upstream_node and _resolve_node_type(upstream_node).lower() == "tool"
                    for upstream_tool_id in [get_tool_id_from_label(_resolve_node_label(upstream_node))]
                    if upstream_tool_id
                }

                processed_requirements = []
                for req in get_tool_requirements(tool_id):
                    req_copy = dict(req)
                    producer_name = None
                    for upstream_tool_id in upstream_tool_ids:
                        if tool_produces_requirement(upstream_tool_id, str(req_copy.get("type") or "")):
                            upstream_tool = get_tool_by_id(upstream_tool_id)
                            producer_name = upstream_tool.get("name", upstream_tool_id) if upstream_tool else upstream_tool_id
                            break
                    req_copy["is_intermediate"] = producer_name is not None
                    if producer_name:
                        req_copy["source_tool"] = producer_name
                    processed_requirements.append(req_copy)

                node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
                tool_requirement_entries.append({
                    "tool_index": len(tool_requirement_entries),
                    "tool_id": tool_id,
                    "tool_name": node_label or tool_id,
                    "tool_type": node_data.get("toolType", node_type or "unknown"),
                    "description": node_data.get("description", ""),
                    "requirements": processed_requirements,
                })
    
    explicit_input_requirements = []
    for index, node in enumerate(node_list, start=1):
        if not isinstance(node, dict):
            continue

        classification = _classify_explicit_input(node)
        if not classification:
            continue

        node_id = str(node.get("id") or "")
        downstream_tool_labels: List[str] = []
        for target_id in outgoing_edges.get(node_id, []):
            target_node = nodes_by_id.get(target_id)
            if not target_node or _resolve_node_type(target_node).lower() != "tool":
                continue
            tool_id = get_tool_id_from_label(_resolve_node_label(target_node))
            tool = get_tool_by_id(tool_id) if tool_id else None
            if tool:
                downstream_tool_labels.append(tool["name"])

        explicit_input_requirements.append({
            "type": classification["type"],
            "label": _resolve_node_label(node) or f"{classification['formats'][0].upper()} Input {index}",
            "formats": classification["formats"],
            "used_by": downstream_tool_labels or ["Selected pipeline"],
        })

    if explicit_input_requirements:
        return {
            "input_requirements": explicit_input_requirements,
            "tools": ordered_tools_in_pipeline,
            "tool_requirements": tool_requirement_entries,
            "has_spades": "SPADES" in tools_in_pipeline,
            "has_quast": "QUAST" in tools_in_pipeline,
            "has_fastqc": "FASTQC" in tools_in_pipeline,
            "has_genomescope2": "GENOMESCOPE2" in tools_in_pipeline,
        }

    input_requirements = []
    seen_requirement_types: set[str] = set()
    producer_tool_ids = set(tools_in_pipeline)

    for tool_id in ordered_tools_in_pipeline:
        tool = get_tool_by_id(tool_id)
        tool_name = tool["name"] if tool else tool_id
        for req in get_tool_requirements(tool_id):
            req_type = str(req.get("type") or "").strip()
            if not req_type:
                continue

            if any(
                other_tool_id != tool_id and tool_produces_requirement(other_tool_id, req_type)
                for other_tool_id in producer_tool_ids
            ):
                continue

            req_copy = dict(req)
            req_copy["used_by"] = [tool_name]
            if req_type in seen_requirement_types:
                for existing in input_requirements:
                    if existing.get("type") == req_type and tool_name not in existing.get("used_by", []):
                        existing.setdefault("used_by", []).append(tool_name)
                continue

            input_requirements.append(req_copy)
            seen_requirement_types.add(req_type)

    seen = set()
    unique_requirements = []
    for req in input_requirements:
        req_key = (req["type"], req["label"])
        if req_key not in seen:
            seen.add(req_key)
            unique_requirements.append(dict(req))
    
    return {
        "input_requirements": unique_requirements,
        "tools": ordered_tools_in_pipeline,
        "tool_requirements": tool_requirement_entries,
        "has_spades": "SPADES" in tools_in_pipeline,
        "has_quast": "QUAST" in tools_in_pipeline,
        "has_fastqc": "FASTQC" in tools_in_pipeline,
        "has_genomescope2": "GENOMESCOPE2" in tools_in_pipeline,
    }
