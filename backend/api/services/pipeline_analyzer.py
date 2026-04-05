"""
Pipeline analyzer service.

Analyzes pipeline graphs to determine input requirements for job creation.
"""

import logging
from typing import List, Dict, Any

from backend.api.models.pipeline_model import PipelineInDB
from tool_registry import get_tool_id_from_label, get_tool_requirements

logger = logging.getLogger(__name__)


def extract_input_nodes(pipeline: PipelineInDB) -> List[Dict[str, Any]]:
    """
    Extract input nodes from pipeline graph.
    
    Args:
        pipeline: Pipeline with nodes and edges
        
    Returns:
        List[Dict]: List of input node information
    """
    # Handle different node structures
    if isinstance(pipeline.nodes, dict):
        if "nodes" in pipeline.nodes:
            node_list = pipeline.nodes["nodes"]
        else:
            node_list = list(pipeline.nodes.values())
    elif isinstance(pipeline.nodes, list):
        node_list = pipeline.nodes
    else:
        return []
    
    input_nodes = []
    for node in node_list:
        if isinstance(node, dict):
            node_type = node.get("type") or node.get("nodeType")
            node_data = node.get("data") or node
            node_label = node_data.get("label") if isinstance(node_data, dict) else str(node_data)
        else:
            node_type = getattr(node, "type", None)
            node_data = getattr(node, "data", node)
            node_label = getattr(node_data, "label", None) if hasattr(node_data, "label") else str(node_data)
        
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
    # Extract tool nodes
    if isinstance(pipeline.nodes, dict):
        if "nodes" in pipeline.nodes:
            node_list = pipeline.nodes["nodes"]
        else:
            node_list = list(pipeline.nodes.values())
    elif isinstance(pipeline.nodes, list):
        node_list = pipeline.nodes
    else:
        node_list = []
    
    # Find tools in pipeline
    tools_in_pipeline = set()
    for node in node_list:
        if isinstance(node, dict):
            node_type = node.get("type") or node.get("nodeType")
            node_data = node.get("data") or node
            node_label = node_data.get("label") if isinstance(node_data, dict) else str(node_data)
        else:
            node_type = getattr(node, "type", None)
            node_data = getattr(node, "data", node)
            node_label = getattr(node_data, "label", None) if hasattr(node_data, "label") else str(node_data)
        
        if node_type == "tool":
            tool_id = get_tool_id_from_label(node_label)
            if tool_id:
                tools_in_pipeline.add(tool_id)
    
    # Determine input requirements based on tools
    input_requirements = []
    required_types = set()
    
    # Check for SPAdes (needs R1 and R2)
    if "SPADES" in tools_in_pipeline:
        input_requirements.extend(get_tool_requirements("SPADES"))
        required_types.update(["forward_reads", "reverse_reads"])
    
    # Check for QUAST (needs assembly and reference)
    if "QUAST" in tools_in_pipeline:
        # If SPAdes is also present, assembly comes from SPAdes output
        if "SPADES" not in tools_in_pipeline:
            input_requirements.extend(get_tool_requirements("QUAST"))
            required_types.update(["assembly", "reference"])
        else:
            # Only need reference, assembly comes from SPAdes
            quast_requirements = get_tool_requirements("QUAST")
            if len(quast_requirements) > 1:
                input_requirements.append(quast_requirements[1])  # reference only
            required_types.add("reference")
    
    # Check for FastQC or GenomeScope2 (need reads)
    if "FASTQC" in tools_in_pipeline or "GENOMESCOPE2" in tools_in_pipeline:
        # If SPAdes is present, reads are already covered
        if "SPADES" not in tools_in_pipeline:
            # Add generic reads requirement
            if "reads" not in required_types:
                fastqc_requirements = get_tool_requirements("FASTQC")
                if fastqc_requirements:
                    input_requirements.append(fastqc_requirements[0])
                required_types.add("reads")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_requirements = []
    for req in input_requirements:
        req_key = (req["type"], req["label"])
        if req_key not in seen:
            seen.add(req_key)
            unique_requirements.append(req)
    
    return {
        "input_requirements": unique_requirements,
        "tools": list(tools_in_pipeline),
        "has_spades": "SPADES" in tools_in_pipeline,
        "has_quast": "QUAST" in tools_in_pipeline,
        "has_fastqc": "FASTQC" in tools_in_pipeline,
        "has_genomescope2": "GENOMESCOPE2" in tools_in_pipeline,
    }
