"""
Deterministic runtime estimation helpers for CASSIE jobs.

The estimator is intentionally transparent and configurable. It combines:
- per-tool baseline runtime weights
- a small fixed orchestration overhead
- a VM partition speed multiplier
- size-aware scaling from selected inputs
- optional pipeline DAG critical-path analysis for saved pipelines
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.api.services.vm_partition_service import get_vm_partition
from backend.api.services.vm_partition_service import get_vm_partitions
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_id, get_tool_by_index, get_tool_id_from_label, tool_produces_requirement

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ESTIMATOR_CONFIG_PATH = PROJECT_ROOT / "config" / "runtime_estimator_profiles.json"
SPECS_CONFIG_PATH = PROJECT_ROOT / "config" / "specs.json"

DEFAULT_TOOL_BASE_MINUTES: Dict[str, float] = {
    "FASTQC": 0.083,
    "SPADES": 140.0,
    "QUAST": 22.0,
    "GENOMESCOPE2": 26.0,
    "METASPADES": 170.0,
    "HIFIASM": 230.0,
    "VERKKO": 300.0,
    "LIFTOFF": 42.0,
    "CAT": 95.0,
    "BUSCO": 36.0,
    "MERYL": 28.0,
    "MERQURY": 70.0,
}

DEFAULT_VM_SPEED_MULTIPLIERS: Dict[str, float] = {
    "vm1": 1.0,
    "vm2": 1.35,
    "vm3": 1.8,
}

DEFAULT_VM_PRICE_PER_MINUTE: Dict[str, float] = {
    "vm1": 0.08,
    "vm2": 0.14,
    "vm3": 0.24,
}

DEFAULT_TOOL_REFERENCE_INPUT_MIB: Dict[str, float] = {
    "FASTQC": 2048.0,
    "SPADES": 12000.0,
    "QUAST": 512.0,
    "GENOMESCOPE2": 6000.0,
    "METASPADES": 15000.0,
    "HIFIASM": 22000.0,
    "VERKKO": 26000.0,
    "LIFTOFF": 800.0,
    "CAT": 3000.0,
    "BUSCO": 800.0,
    "MERYL": 2500.0,
    "MERQURY": 1600.0,
}

DEFAULT_TOOL_SIZE_EXPONENT: Dict[str, float] = {
    "FASTQC": 0.45,
    "SPADES": 0.62,
    "QUAST": 0.35,
    "GENOMESCOPE2": 0.56,
    "METASPADES": 0.64,
    "HIFIASM": 0.58,
    "VERKKO": 0.6,
    "LIFTOFF": 0.42,
    "CAT": 0.48,
    "BUSCO": 0.38,
    "MERYL": 0.44,
    "MERQURY": 0.46,
}

DEFAULT_TOOL_OUTPUT_SIZE_MULTIPLIER: Dict[str, float] = {
    "FASTQC": 0.02,
    "SPADES": 0.12,
    "QUAST": 0.01,
    "GENOMESCOPE2": 0.005,
    "METASPADES": 0.15,
    "HIFIASM": 0.18,
    "VERKKO": 0.2,
    "LIFTOFF": 0.02,
    "CAT": 0.04,
    "BUSCO": 0.01,
    "MERYL": 0.65,
    "MERQURY": 0.03,
}

# S3-to-pod bandwidth used to estimate the input-file copy that each tool performs
# at container startup before any computation begins.
DEFAULT_POD_COPY_BANDWIDTH_MIB_PER_SEC: float = 34.0


@dataclass(frozen=True)
class RuntimeEstimate:
    model_type: str
    vm_name: str
    vm_display_name: str
    partition_factor: float
    vm_price_per_minute: float
    total_input_size_mib: float
    estimated_runtime_seconds: int
    estimated_runtime_minutes: int
    estimated_runtime_hours: float
    estimated_price_usd: float
    fixed_overhead_minutes: float
    execution_shape: str
    tool_breakdown: List[Dict[str, Any]]
    assumptions: List[str]


@dataclass(frozen=True)
class RuntimeInputAssignment:
    tool_id: str
    requirement_type: str
    total_input_size_mib: float
    compressed_input_size_mib: float = 0.0
    file_formats: Optional[List[str]] = None
    input_filenames: Optional[List[str]] = None


def _load_runtime_config() -> Dict[str, Any]:
    if not RUNTIME_ESTIMATOR_CONFIG_PATH.exists():
        return {}

    try:
        payload = json.loads(RUNTIME_ESTIMATOR_CONFIG_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.warning(f"Failed to read runtime estimator config {RUNTIME_ESTIMATOR_CONFIG_PATH}: {exc}")
        return {}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _debug_local_llm_prompts_enabled() -> bool:
    return _env_bool("CASSIE_DEBUG_LOCAL_LLM_PROMPTS", False)


def _debug_local_llm_exchange(label: str, question: Dict[str, Any], answer: Any = None) -> None:
    if not _debug_local_llm_prompts_enabled():
        return
    print(f"[CASSIE LOCAL LLM DEBUG] {label} question:")
    print(json.dumps(question, indent=2, ensure_ascii=False))
    if answer is not None:
        print(f"[CASSIE LOCAL LLM DEBUG] {label} answer:")
        print(answer if isinstance(answer, str) else json.dumps(answer, indent=2, ensure_ascii=False))


def _load_specs_config() -> Dict[str, Any]:
    if not SPECS_CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(SPECS_CONFIG_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.warning(f"Failed to read machine specs config {SPECS_CONFIG_PATH}: {exc}")
        return {}


def _env_int(name: str) -> int:
    try:
        return int(str(os.getenv(name) or "").strip())
    except (TypeError, ValueError):
        return 0


def _cluster_capacity_from_env() -> Dict[str, int]:
    return {
        "cpu_millis": _env_int("CASSIE_CLUSTER_CPU_MILLIS") or 7000,
        "memory_mib": _env_int("CASSIE_CLUSTER_MEMORY_MIB") or 106496,
        "storage_mib": _env_int("CASSIE_CLUSTER_STORAGE_MIB") or 245760,
        "storage_reserve_mib": _env_int("CASSIE_CLUSTER_STORAGE_RESERVE_MIB") or 8192,
    }


def _partition_resource_context(vm_name: Optional[str]) -> Dict[str, Any]:
    partitions = get_vm_partitions()
    selected_partition = get_vm_partition(vm_name) or (partitions[0] if partitions else None)
    vm_count = max(1, len(partitions))
    partition_count = max(1, selected_partition.max_jobs if selected_partition else 1)
    cluster = _cluster_capacity_from_env()
    usable_storage_mib = max(0, cluster["storage_mib"] - min(cluster["storage_mib"], cluster["storage_reserve_mib"]))
    vm_cpu_millis = max(1, cluster["cpu_millis"] // vm_count)
    vm_memory_mib = max(1, cluster["memory_mib"] // vm_count)
    vm_storage_mib = usable_storage_mib // vm_count if usable_storage_mib > 0 else 0
    return {
        "selected_vm": {
            "name": selected_partition.name if selected_partition else (vm_name or "vm1"),
            "display_name": selected_partition.display_name if selected_partition else (vm_name or "VM1"),
            "max_concurrent_jobs": partition_count,
        },
        "vm_partition_config": [
            {
                "name": partition.name,
                "display_name": partition.display_name,
                "max_concurrent_jobs": partition.max_jobs,
            }
            for partition in partitions
        ],
        "cluster_capacity": cluster,
        "per_vm_slice": {
            "cpu_cores": round(vm_cpu_millis / 1000.0, 3),
            "memory_gib": round(vm_memory_mib / 1024.0, 3),
            "storage_gib": round(vm_storage_mib / 1024.0, 3) if vm_storage_mib else 0,
        },
        "per_job_partition": {
            "cpu_cores": round((vm_cpu_millis // partition_count) / 1000.0, 3),
            "memory_gib": round((vm_memory_mib // partition_count) / 1024.0, 3),
            "storage_gib": round((vm_storage_mib // partition_count) / 1024.0, 3) if vm_storage_mib else 0,
        },
    }


def _local_llm_chat_url() -> str:
    base_url = (
        os.getenv("CASSIE_LOCAL_LLM_BASE_URL")
        or os.getenv("LOCAL_LLM_BASE_URL")
        or os.getenv("LOCAL_LLM_URL")
        or ""
    ).strip()
    if not base_url:
        return ""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _tool_base_minutes(tool_id: str) -> float:
    config = _load_runtime_config()
    configured = config.get("tool_base_minutes", {})
    if isinstance(configured, dict):
        raw = configured.get(tool_id)
        if raw is not None:
            try:
                return max(0.001, float(raw))
            except (TypeError, ValueError):
                pass

    return DEFAULT_TOOL_BASE_MINUTES.get(tool_id, 30.0)


def _tool_reference_input_mib(tool_id: str) -> float:
    config = _load_runtime_config()
    configured = config.get("tool_reference_input_mib", {})
    if isinstance(configured, dict):
        raw = configured.get(tool_id)
        if raw is not None:
            try:
                return max(1.0, float(raw))
            except (TypeError, ValueError):
                pass
    return DEFAULT_TOOL_REFERENCE_INPUT_MIB.get(tool_id, 1024.0)


def _tool_size_exponent(tool_id: str) -> float:
    config = _load_runtime_config()
    configured = config.get("tool_size_exponent", {})
    if isinstance(configured, dict):
        raw = configured.get(tool_id)
        if raw is not None:
            try:
                return max(0.05, float(raw))
            except (TypeError, ValueError):
                pass
    return DEFAULT_TOOL_SIZE_EXPONENT.get(tool_id, 0.4)


def _tool_output_size_multiplier(tool_id: str) -> float:
    config = _load_runtime_config()
    configured = config.get("tool_output_size_multiplier", {})
    if isinstance(configured, dict):
        raw = configured.get(tool_id)
        if raw is not None:
            try:
                return max(0.001, float(raw))
            except (TypeError, ValueError):
                pass
    return DEFAULT_TOOL_OUTPUT_SIZE_MULTIPLIER.get(tool_id, 0.08)


def _pod_copy_bandwidth_mib_per_sec() -> float:
    config = _load_runtime_config()
    raw = config.get("pod_input_copy_bandwidth_mib_per_sec")
    try:
        if raw is not None:
            return max(1.0, float(raw))
    except (TypeError, ValueError):
        pass
    return DEFAULT_POD_COPY_BANDWIDTH_MIB_PER_SEC


def _upload_overhead_minutes(input_size_mib: float) -> float:
    """Time to copy input_size_mib from S3 into the tool pod before execution starts."""
    bandwidth = _pod_copy_bandwidth_mib_per_sec()
    size = max(0.0, float(input_size_mib or 0.0))
    return size / (bandwidth * 60.0)


def _compression_penalty_factor(
    compressed_input_size_mib: float,
    total_input_size_mib: float,
    file_formats: Optional[List[str]] = None,
) -> float:
    total_size = max(float(total_input_size_mib or 0.0), 0.0)
    if total_size <= 0:
        return 1.0

    compressed_size = max(min(float(compressed_input_size_mib or 0.0), total_size), 0.0)
    compressed_ratio = compressed_size / total_size
    if compressed_ratio <= 0:
        return 1.0

    normalized_formats = [str(file_format or '').lower() for file_format in (file_formats or [])]
    stronger_penalty = any(
        marker in file_format
        for file_format in normalized_formats
        for marker in ('fastq.gz', 'fq.gz', 'fasta.gz', 'fa.gz', 'fna.gz')
    )
    base_penalty = 0.22 if stronger_penalty else 0.14
    return min(1.35, 1.0 + (compressed_ratio * base_penalty))


def _fixed_overhead_minutes() -> float:
    config = _load_runtime_config()
    raw = config.get("fixed_overhead_minutes")
    try:
        if raw is not None:
            return max(0.0, float(raw))
    except (TypeError, ValueError):
                pass
    return 10.0


def _effective_fixed_overhead_minutes(
    *,
    tool_count: int,
    total_input_size_mib: float,
    execution_shape: str,
) -> float:
    base_overhead = _fixed_overhead_minutes()
    normalized_tool_count = max(int(tool_count or 0), 0)
    normalized_input_size = max(float(total_input_size_mib or 0.0), 0.0)

    if normalized_tool_count <= 1 and normalized_input_size <= 2048:
        return min(base_overhead, 2.0)
    if normalized_tool_count <= 2 and normalized_input_size <= 4096:
        return min(base_overhead, 4.0)
    if execution_shape == "pipeline-critical-path" and normalized_tool_count >= 4:
        return base_overhead
    if normalized_input_size <= 8192:
        return min(base_overhead, 6.0)
    return base_overhead


def _vm_speed_multiplier(vm_name: Optional[str]) -> tuple[str, str, float]:
    partition = get_vm_partition(vm_name)
    normalized_name = partition.name if partition else (vm_name or "vm1")
    display_name = partition.display_name if partition else normalized_name.upper()

    config = _load_runtime_config()
    configured = config.get("vm_speed_multipliers", {})
    if isinstance(configured, dict):
        raw = configured.get(normalized_name)
        if raw is not None:
            try:
                return normalized_name, display_name, max(0.25, float(raw))
            except (TypeError, ValueError):
                pass

    if normalized_name in DEFAULT_VM_SPEED_MULTIPLIERS:
        return normalized_name, display_name, DEFAULT_VM_SPEED_MULTIPLIERS[normalized_name]

    if partition:
        return normalized_name, display_name, max(1.0, 0.75 + (partition.max_jobs * 0.35))

    return normalized_name, display_name, 1.0


def _vm_price_per_minute(vm_name: Optional[str]) -> float:
    partition = get_vm_partition(vm_name)
    normalized_name = partition.name if partition else (vm_name or "vm1")

    config = _load_runtime_config()
    configured = config.get("vm_price_per_minute", {})
    if isinstance(configured, dict):
        raw = configured.get(normalized_name)
        if raw is not None:
            try:
                return max(0.0, float(raw))
            except (TypeError, ValueError):
                pass

    return DEFAULT_VM_PRICE_PER_MINUTE.get(normalized_name, 0.1)


def get_vm_price_per_minute(vm_name: Optional[str]) -> float:
    """Return the configured per-minute price for a VM profile."""
    return _vm_price_per_minute(vm_name)


def format_runtime_minutes(total_minutes: int) -> str:
    minutes = max(0, int(total_minutes or 0))
    days = minutes // 1440
    remainder = minutes % 1440
    hours = remainder // 60
    remaining_minutes = remainder % 60
    parts: List[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if remaining_minutes or not parts:
        parts.append(f"{remaining_minutes}m")
    return " ".join(parts)


def _size_factor(tool_id: str, input_size_mib: float) -> float:
    reference_input_mib = _tool_reference_input_mib(tool_id)
    exponent = _tool_size_exponent(tool_id)
    normalized_size = max(1.0, float(input_size_mib or reference_input_mib))
    factor = (normalized_size / reference_input_mib) ** exponent
    return max(0.35, min(12.0, factor))


def _build_tool_breakdown(
    tool_ids: List[str],
    partition_factor: float,
    input_size_by_tool: Optional[Dict[str, float]] = None,
    penalty_summary_by_tool: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    breakdown: List[Dict[str, Any]] = []
    for tool_id in tool_ids:
        tool = get_tool_by_id(tool_id)
        base_minutes = _tool_base_minutes(tool_id)
        input_size_mib = (input_size_by_tool or {}).get(tool_id, _tool_reference_input_mib(tool_id))
        size_factor = _size_factor(tool_id, input_size_mib)
        penalty_summary = (penalty_summary_by_tool or {}).get(tool_id, {})
        compression_factor = float(penalty_summary.get("compression_factor", 1.0) or 1.0)
        upload_overhead = _upload_overhead_minutes(input_size_mib)
        adjusted_minutes = round(
            base_minutes * partition_factor * size_factor * compression_factor + upload_overhead,
            1,
        )
        breakdown.append(
            {
                "tool_id": tool_id,
                "tool_name": tool.get("name") if tool else tool_id,
                "base_minutes": round(base_minutes, 1),
                "input_size_mib": round(input_size_mib, 2),
                "input_size_bytes": int(round(input_size_mib * 1024 * 1024)),
                "input_suffixes": sorted(penalty_summary.get("file_formats", [])),
                "size_factor": round(size_factor, 3),
                "compression_factor": round(compression_factor, 3),
                "upload_overhead_minutes": round(upload_overhead, 2),
                "adjusted_minutes": adjusted_minutes,
            }
        )
    return breakdown


def _group_input_assignments(assignments: Optional[List[RuntimeInputAssignment]]) -> Dict[str, Dict[str, float]]:
    grouped: Dict[str, Dict[str, float]] = {}
    for assignment in assignments or []:
        tool_key = str(assignment.tool_id)
        requirement_key = str(assignment.requirement_type)
        grouped.setdefault(tool_key, {})
        grouped[tool_key][requirement_key] = grouped[tool_key].get(requirement_key, 0.0) + max(0.0, float(assignment.total_input_size_mib))
    return grouped


def _summarize_assignment_penalties(assignments: Optional[List[RuntimeInputAssignment]]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for assignment in assignments or []:
        tool_key = str(assignment.tool_id)
        current = summary.setdefault(
            tool_key,
            {
                "total_input_size_mib": 0.0,
                "compressed_input_size_mib": 0.0,
                "file_formats": set(),
            },
        )
        current["total_input_size_mib"] += max(0.0, float(assignment.total_input_size_mib or 0.0))
        current["compressed_input_size_mib"] += max(0.0, float(assignment.compressed_input_size_mib or 0.0))
        for file_format in assignment.file_formats or []:
            normalized = str(file_format or "").strip().lower()
            if normalized:
                current["file_formats"].add(normalized)

    for current in summary.values():
        current["compression_factor"] = _compression_penalty_factor(
            current["compressed_input_size_mib"],
            current["total_input_size_mib"],
            sorted(current["file_formats"]),
        )
        current["file_formats"] = sorted(current["file_formats"])
    return summary


def _filename_suffixes(filename: str) -> List[str]:
    normalized = str(filename or "").strip().lower()
    if not normalized:
        return []
    suffixes: List[str] = []
    parts = normalized.split(".")
    if len(parts) > 1:
        suffixes.append(parts[-1])
        for depth in range(2, min(4, len(parts)) + 1):
            suffixes.append(".".join(parts[-depth:]))
    return sorted(set(suffixes))


def _assignment_llm_inputs(assignments: Optional[List[RuntimeInputAssignment]]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for assignment in assignments or []:
        filenames = [str(name or "").strip() for name in (assignment.input_filenames or []) if str(name or "").strip()]
        suffixes = set()
        for filename in filenames:
            suffixes.update(_filename_suffixes(filename))
        for file_format in assignment.file_formats or []:
            normalized = str(file_format or "").strip().lower().lstrip(".")
            if normalized:
                suffixes.add(normalized)
        entries.append(
            {
                "tool_id": str(assignment.tool_id or "").upper(),
                "requirement_type": str(assignment.requirement_type or ""),
                "total_input_size_mib": round(max(0.0, float(assignment.total_input_size_mib or 0.0)), 2),
                "compressed_input_size_mib": round(max(0.0, float(assignment.compressed_input_size_mib or 0.0)), 2),
                "file_formats_and_suffixes": sorted(suffixes),
                "filenames": filenames[:20],
            }
        )
    return entries


def _pipeline_prompt_payload(nodes: Optional[List[Dict[str, Any]]], edges: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    if not nodes:
        return {}
    compact_nodes = []
    for node in nodes:
        node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
        label = node_data.get("label") or node.get("label") or node.get("id")
        compact_nodes.append(
            {
                "id": str(node.get("id") or ""),
                "type": str(node.get("type") or ""),
                "label": str(label or ""),
                "tool_id": str(node_data.get("toolId") or node_data.get("tool_id") or node.get("toolId") or node.get("tool_id") or ""),
            }
        )
    compact_edges = [
        {
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
        }
        for edge in (edges or [])
    ]
    return {"nodes": compact_nodes, "edges": compact_edges}


def _extract_llm_minutes(text: str) -> Optional[int]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    json_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    candidates = [cleaned]
    if json_match:
        candidates.insert(0, json_match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            for key in ("estimated_minutes", "minutes", "runtime_minutes", "estimated_runtime_minutes"):
                if key in parsed:
                    try:
                        return max(1, int(round(float(parsed[key]))))
                    except (TypeError, ValueError):
                        continue
    number_match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if number_match:
        try:
            return max(1, int(round(float(number_match.group(1)))))
        except (TypeError, ValueError):
            return None
    return None


def _call_local_llm_for_runtime_minutes(payload: Dict[str, Any]) -> Optional[int]:
    chat_url = _local_llm_chat_url()
    if not chat_url:
        raise RuntimeError("CASSIE_LOCAL_LLM_BASE_URL is not configured")
    model = (
        os.getenv("CASSIE_LOCAL_LLM_MODEL")
        or os.getenv("LOCAL_LLM_MODEL")
        or "qwen2.5:7b-instruct"
    )
    timeout = float(os.getenv("CASSIE_LOCAL_LLM_TIMEOUT_SECONDS") or "25")
    system_prompt = (
        "You estimate bioinformatics job wall-clock runtime for CASSIE. "
        "Return only JSON like {\"estimated_minutes\": 123}. "
        "Do not include explanations. "
        "Estimate total end-to-end elapsed minutes for one submitted job. "
        "Do not assume any parallel execution between tools, branches, stages, or jobs; treat pipeline steps as sequential unless a single tool internally uses the listed per-job resources. "
        "Use file suffixes including .gz/.zip, input sizes, VM partition resources, and machine specs."
    )
    prompt_debug_payload = {
        "chat_url": chat_url,
        "model": model,
        "system_prompt": system_prompt,
        "user_prompt": payload,
        "temperature": 0.0,
        "max_tokens": 80,
    }
    _debug_local_llm_exchange("runtime-estimate", prompt_debug_payload)
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
            ],
            "temperature": 0.0,
            "max_tokens": 80,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        chat_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    if not choices:
        return None
    content = choices[0].get("message", {}).get("content", "") if isinstance(choices[0], dict) else ""
    _debug_local_llm_exchange("runtime-estimate", prompt_debug_payload, content)
    return _extract_llm_minutes(content)


def _maybe_apply_local_llm_runtime_estimate(
    deterministic_estimate: RuntimeEstimate,
    *,
    tool_ids: List[str],
    vm_name: Optional[str],
    input_assignments: Optional[List[RuntimeInputAssignment]],
    pipeline_nodes: Optional[List[Dict[str, Any]]] = None,
    pipeline_edges: Optional[List[Dict[str, Any]]] = None,
) -> RuntimeEstimate:
    if not _env_bool("CASSIE_USE_LOCAL_LLM_RUNTIME_ESTIMATOR", False):
        return deterministic_estimate

    payload = {
        "task": "estimate_runtime_minutes",
        "tools": [
            {
                "tool_id": tool_id,
                "tool_name": (get_tool_by_id(tool_id) or {}).get("name", tool_id),
                "description": (get_tool_by_id(tool_id) or {}).get("description", ""),
            }
            for tool_id in tool_ids
        ],
        "pipeline": _pipeline_prompt_payload(pipeline_nodes, pipeline_edges),
        "inputs": _assignment_llm_inputs(input_assignments),
        "vm_resources": _partition_resource_context(vm_name),
        "machine_specs": _load_specs_config(),
        "rules": [
            "Return only JSON with estimated_minutes.",
            "Estimate total elapsed minutes for one job.",
            "Do not assume parallel execution between tools, pipeline branches, or jobs.",
            "Use the selected VM per-job partition resources, not whole-machine resources, as the job limit.",
        ],
    }
    try:
        llm_minutes = _call_local_llm_for_runtime_minutes(payload)
        if not llm_minutes:
            raise RuntimeError("Local LLM did not return a parseable minute value")
    except Exception as exc:
        logger.warning(f"Local LLM runtime estimator failed; using deterministic estimate: {exc}")
        return RuntimeEstimate(
            **{
                **deterministic_estimate.__dict__,
                "assumptions": [
                    *deterministic_estimate.assumptions,
                    f"Local LLM runtime estimator was enabled but unavailable or unparseable, so deterministic estimate was used: {exc}",
                ],
            }
        )

    estimated_price_usd = round(llm_minutes * deterministic_estimate.vm_price_per_minute, 2)
    return RuntimeEstimate(
        model_type="local-llm-runtime",
        vm_name=deterministic_estimate.vm_name,
        vm_display_name=deterministic_estimate.vm_display_name,
        partition_factor=deterministic_estimate.partition_factor,
        vm_price_per_minute=deterministic_estimate.vm_price_per_minute,
        total_input_size_mib=deterministic_estimate.total_input_size_mib,
        estimated_runtime_seconds=llm_minutes * 60,
        estimated_runtime_minutes=llm_minutes,
        estimated_runtime_hours=round(llm_minutes / 60.0, 2),
        estimated_price_usd=estimated_price_usd,
        fixed_overhead_minutes=0.0,
        execution_shape="local-llm-sequential-runtime",
        tool_breakdown=deterministic_estimate.tool_breakdown,
        assumptions=[
            "Uses the configured local Ollama/OpenAI-compatible LLM for total runtime minutes.",
            "The LLM prompt includes mapped filenames, file suffixes including compressed extensions, pipeline graph, VM partition limits, and config/specs.json machine specs.",
            "The LLM is instructed not to assume parallel execution between tools, branches, stages, or jobs.",
        ],
    )


def _estimate_tool_input_sizes_for_sequence(
    tool_ids: List[str],
    explicit_assignments: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    output_sizes_by_tool: Dict[str, float] = {}
    effective_input_by_tool: Dict[str, float] = {}

    for tool_id in tool_ids:
        tool = get_tool_by_id(tool_id) or {}
        requirements = list(tool.get("input_requirements", []))
        explicit_size = sum(explicit_assignments.get(tool_id, {}).values())
        inherited_size = 0.0

        for requirement in requirements:
            requirement_type = str(requirement.get("type") or "")
            if explicit_assignments.get(tool_id, {}).get(requirement_type):
                continue

            for producer_tool_id, producer_output_size in output_sizes_by_tool.items():
                if tool_produces_requirement(producer_tool_id, requirement_type):
                    inherited_size += producer_output_size

        effective_input_size = max(explicit_size + inherited_size, _tool_reference_input_mib(tool_id))
        effective_input_by_tool[tool_id] = effective_input_size
        output_sizes_by_tool[tool_id] = max(1.0, effective_input_size * _tool_output_size_multiplier(tool_id))

    return effective_input_by_tool


def _total_explicit_input_size_mib(grouped_assignments: Dict[str, Dict[str, float]]) -> float:
    return round(
        sum(
            size
            for requirement_sizes in grouped_assignments.values()
            for size in requirement_sizes.values()
        ),
        2,
    )


def _topological_layers(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], weighted_node_minutes: Dict[str, float]) -> tuple[float, int]:
    incoming_count: Dict[str, int] = {str(node.get("id")): 0 for node in nodes}
    outgoing: Dict[str, List[str]] = {str(node.get("id")): [] for node in nodes}

    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source in outgoing and target in incoming_count:
            outgoing[source].append(target)
            incoming_count[target] += 1

    queue = [node_id for node_id, count in incoming_count.items() if count == 0]
    longest_path_minutes: Dict[str, float] = {node_id: weighted_node_minutes.get(node_id, 0.0) for node_id in incoming_count}
    visited_count = 0

    while queue:
        current = queue.pop(0)
        visited_count += 1
        current_minutes = longest_path_minutes.get(current, weighted_node_minutes.get(current, 0.0))
        for next_node in outgoing.get(current, []):
            next_minutes = current_minutes + weighted_node_minutes.get(next_node, 0.0)
            if next_minutes > longest_path_minutes.get(next_node, 0.0):
                longest_path_minutes[next_node] = next_minutes
            incoming_count[next_node] -= 1
            if incoming_count[next_node] == 0:
                queue.append(next_node)

    if visited_count != len(nodes):
        total = sum(weighted_node_minutes.values())
        return total, 1

    sinks = [node_id for node_id, children in outgoing.items() if len(children) == 0]
    critical_path = max((longest_path_minutes.get(node_id, 0.0) for node_id in sinks), default=0.0)
    branch_factor = max(1, len([node for node in outgoing.values() if len(node) > 1]) + 1)
    return critical_path, branch_factor


def estimate_runtime_for_tool_indices(
    tool_indices: List[int],
    vm_name: Optional[str],
    input_assignments: Optional[List[RuntimeInputAssignment]] = None,
) -> RuntimeEstimate:
    tool_ids: List[str] = []
    for index in tool_indices:
        tool = get_tool_by_index(index)
        if tool:
            tool_ids.append(str(tool["id"]))

    resolved_vm_name, display_name, partition_factor = _vm_speed_multiplier(vm_name)
    vm_price_per_minute = _vm_price_per_minute(resolved_vm_name)
    grouped_assignments = _group_input_assignments(input_assignments)
    penalty_summary_by_tool = _summarize_assignment_penalties(input_assignments)
    effective_input_sizes = _estimate_tool_input_sizes_for_sequence(tool_ids, grouped_assignments)
    breakdown = _build_tool_breakdown(
        tool_ids,
        partition_factor,
        effective_input_sizes,
        penalty_summary_by_tool,
    )
    total_input_size_mib = _total_explicit_input_size_mib(grouped_assignments)
    fixed_overhead = _effective_fixed_overhead_minutes(
        tool_count=len(tool_ids),
        total_input_size_mib=total_input_size_mib,
        execution_shape="sequential-tools",
    )
    sequential_minutes = sum(item["adjusted_minutes"] for item in breakdown)
    estimated_minutes = max(1, round(sequential_minutes + fixed_overhead))
    estimated_price_usd = round(estimated_minutes * vm_price_per_minute, 2)

    estimate = RuntimeEstimate(
        model_type="deterministic-heuristic",
        vm_name=resolved_vm_name,
        vm_display_name=display_name,
        partition_factor=partition_factor,
        vm_price_per_minute=vm_price_per_minute,
        total_input_size_mib=total_input_size_mib,
        estimated_runtime_seconds=estimated_minutes * 60,
        estimated_runtime_minutes=estimated_minutes,
        estimated_runtime_hours=round(estimated_minutes / 60.0, 2),
        estimated_price_usd=estimated_price_usd,
        fixed_overhead_minutes=fixed_overhead,
        execution_shape="sequential-tools",
        tool_breakdown=breakdown,
        assumptions=[
            "Uses tool-specific baseline runtimes from config/runtime_estimator_profiles.json.",
            "Applies a VM partition multiplier so higher-density partitions predict slower per-job runtimes.",
            "Uses a reduced orchestration overhead for lighter single-tool and small-input jobs.",
            "Scales each tool using total mapped input sizes; downstream intermediate inputs are inferred from upstream output-size multipliers.",
            "Adds a bounded runtime penalty when mapped inputs are compressed file types such as .gz or .zip.",
            "Adds a per-tool pod input-copy overhead based on input size and the configured S3-to-pod bandwidth (pod_input_copy_bandwidth_mib_per_sec).",
        ],
    )
    return _maybe_apply_local_llm_runtime_estimate(
        estimate,
        tool_ids=tool_ids,
        vm_name=resolved_vm_name,
        input_assignments=input_assignments,
    )


def estimate_runtime_for_pipeline_graph(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    vm_name: Optional[str],
    input_assignments: Optional[List[RuntimeInputAssignment]] = None,
) -> RuntimeEstimate:
    from backend.api.services.pipeline_converter import resolve_node_tool_id

    resolved_vm_name, display_name, partition_factor = _vm_speed_multiplier(vm_name)
    vm_price_per_minute = _vm_price_per_minute(resolved_vm_name)
    tool_ids: List[str] = []
    weighted_node_minutes: Dict[str, float] = {}
    output_sizes_by_node: Dict[str, float] = {}
    input_sizes_by_node: Dict[str, float] = {}
    grouped_assignments = _group_input_assignments(input_assignments)
    penalty_summary_by_tool = _summarize_assignment_penalties(input_assignments)

    incoming_edges: Dict[str, List[str]] = {}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target:
            incoming_edges.setdefault(target, []).append(source)

    for node in nodes:
        if str(node.get("type") or "").strip().lower() != "tool":
            continue
        node_id = str(node.get("id") or "")
        tool_id = resolve_node_tool_id(node)
        if not tool_id:
            continue
        tool_ids.append(tool_id)
        explicit_size = sum(grouped_assignments.get(tool_id, {}).values())
        inherited_size = 0.0
        for upstream_node_id in incoming_edges.get(node_id, []):
            inherited_size += output_sizes_by_node.get(upstream_node_id, 0.0)

        effective_input_size = max(explicit_size + inherited_size, _tool_reference_input_mib(tool_id))
        input_sizes_by_node[node_id] = effective_input_size
        compression_factor = float(penalty_summary_by_tool.get(tool_id, {}).get("compression_factor", 1.0) or 1.0)
        weighted_node_minutes[node_id] = (
            _tool_base_minutes(tool_id)
            * partition_factor
            * _size_factor(tool_id, effective_input_size)
            * compression_factor
            + _upload_overhead_minutes(effective_input_size)
        )
        output_sizes_by_node[node_id] = max(1.0, effective_input_size * _tool_output_size_multiplier(tool_id))

    breakdown = _build_tool_breakdown(
        tool_ids,
        partition_factor,
        {tool_id: sum(grouped_assignments.get(tool_id, {}).values()) or _tool_reference_input_mib(tool_id) for tool_id in tool_ids},
        penalty_summary_by_tool,
    )

    total_input_size_mib = _total_explicit_input_size_mib(grouped_assignments)
    fixed_overhead = _effective_fixed_overhead_minutes(
        tool_count=len(tool_ids),
        total_input_size_mib=total_input_size_mib,
        execution_shape="pipeline-critical-path",
    )
    critical_path_minutes, branch_factor = _topological_layers(nodes, edges, weighted_node_minutes)
    orchestration_penalty = max(0.0, (branch_factor - 1) * 4.0)
    estimated_minutes = max(1, round(critical_path_minutes + fixed_overhead + orchestration_penalty))
    estimated_price_usd = round(estimated_minutes * vm_price_per_minute, 2)

    estimate = RuntimeEstimate(
        model_type="deterministic-dag-heuristic",
        vm_name=resolved_vm_name,
        vm_display_name=display_name,
        partition_factor=partition_factor,
        vm_price_per_minute=vm_price_per_minute,
        total_input_size_mib=total_input_size_mib,
        estimated_runtime_seconds=estimated_minutes * 60,
        estimated_runtime_minutes=estimated_minutes,
        estimated_runtime_hours=round(estimated_minutes / 60.0, 2),
        estimated_price_usd=estimated_price_usd,
        fixed_overhead_minutes=fixed_overhead,
        execution_shape="pipeline-critical-path",
        tool_breakdown=breakdown,
        assumptions=[
            "Uses tool baseline runtimes and estimates total runtime from the pipeline DAG critical path.",
            "Adds a small orchestration penalty when the graph branches into parallel stages.",
            "Uses a reduced orchestration overhead for lighter jobs before branch penalties are applied.",
            "Mapped input sizes are propagated through downstream intermediate tools using per-tool output size multipliers.",
            "Adds a bounded runtime penalty when mapped inputs are compressed file types such as .gz or .zip.",
            "Adds a per-tool pod input-copy overhead based on input size and the configured S3-to-pod bandwidth (pod_input_copy_bandwidth_mib_per_sec).",
        ],
    )
    return _maybe_apply_local_llm_runtime_estimate(
        estimate,
        tool_ids=tool_ids,
        vm_name=resolved_vm_name,
        input_assignments=input_assignments,
        pipeline_nodes=nodes,
        pipeline_edges=edges,
    )
