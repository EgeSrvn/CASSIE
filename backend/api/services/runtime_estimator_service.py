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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from backend.api.services.vm_partition_service import get_vm_partition
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_id, get_tool_by_index, get_tool_id_from_label, tool_produces_requirement

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ESTIMATOR_CONFIG_PATH = PROJECT_ROOT / "runtime_estimator_profiles.json"
APP_CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULT_TOOL_BASE_MINUTES: Dict[str, float] = {
    "FASTQC": 8.0,
    "SPADES": 140.0,
    "QUAST": 22.0,
    "GENOMESCOPE2": 26.0,
    "METASPADES": 170.0,
    "HIFIASM": 230.0,
    "VERKKO": 300.0,
    "LIFTOFF": 42.0,
    "CAT": 95.0,
    "BUSCO": 36.0,
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
    "MERQURY": 0.03,
}


@dataclass(frozen=True)
class RuntimeEstimate:
    model_type: str
    vm_name: str
    vm_display_name: str
    partition_factor: float
    vm_price_per_minute: float
    total_input_size_mib: float
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


@dataclass(frozen=True)
class GeminiPredictionSettings:
    enabled: bool
    model: str
    api_key_env_var: str
    api_base_url: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: int


def _load_runtime_config() -> Dict[str, Any]:
    if not RUNTIME_ESTIMATOR_CONFIG_PATH.exists():
        return {}

    try:
        payload = json.loads(RUNTIME_ESTIMATOR_CONFIG_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.warning(f"Failed to read runtime estimator config {RUNTIME_ESTIMATOR_CONFIG_PATH}: {exc}")
        return {}


def _load_app_config() -> Dict[str, Any]:
    if not APP_CONFIG_PATH.exists():
        return {}

    try:
        payload = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.warning(f"Failed to read app config {APP_CONFIG_PATH}: {exc}")
        return {}


def _load_gemini_prediction_settings() -> GeminiPredictionSettings:
    config = _load_app_config()
    gemini_config = config.get("gemini_prediction", {})
    if not isinstance(gemini_config, dict):
        gemini_config = {}

    return GeminiPredictionSettings(
        enabled=bool(gemini_config.get("use_gemini_for_runtime_predictions", False)),
        model=str(gemini_config.get("model") or "gemini-2.5-flash"),
        api_key_env_var=str(gemini_config.get("api_key_env_var") or "GEMINI_API_KEY"),
        api_base_url=str(gemini_config.get("api_base_url") or "https://generativelanguage.googleapis.com"),
        temperature=max(0.0, float(gemini_config.get("temperature", 0.1) or 0.1)),
        max_output_tokens=max(256, int(gemini_config.get("max_output_tokens", 512) or 512)),
        timeout_seconds=max(5, int(gemini_config.get("timeout_seconds", 25) or 25)),
    )


def _tool_base_minutes(tool_id: str) -> float:
    config = _load_runtime_config()
    configured = config.get("tool_base_minutes", {})
    if isinstance(configured, dict):
        raw = configured.get(tool_id)
        if raw is not None:
            try:
                return max(1.0, float(raw))
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


def _fixed_overhead_minutes() -> float:
    config = _load_runtime_config()
    raw = config.get("fixed_overhead_minutes")
    try:
        if raw is not None:
            return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    return 10.0


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


def _size_factor(tool_id: str, input_size_mib: float) -> float:
    reference_input_mib = _tool_reference_input_mib(tool_id)
    exponent = _tool_size_exponent(tool_id)
    normalized_size = max(1.0, float(input_size_mib or reference_input_mib))
    factor = (normalized_size / reference_input_mib) ** exponent
    return max(0.35, min(4.5, factor))


def _build_tool_breakdown(
    tool_ids: List[str],
    partition_factor: float,
    input_size_by_tool: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    breakdown: List[Dict[str, Any]] = []
    for tool_id in tool_ids:
        tool = get_tool_by_id(tool_id)
        base_minutes = _tool_base_minutes(tool_id)
        input_size_mib = (input_size_by_tool or {}).get(tool_id, _tool_reference_input_mib(tool_id))
        size_factor = _size_factor(tool_id, input_size_mib)
        adjusted_minutes = round(base_minutes * partition_factor * size_factor, 1)
        breakdown.append(
            {
                "tool_id": tool_id,
                "tool_name": tool.get("name") if tool else tool_id,
                "base_minutes": round(base_minutes, 1),
                "input_size_mib": round(input_size_mib, 2),
                "size_factor": round(size_factor, 3),
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


def _build_gemini_runtime_prompt(
    *,
    execution_shape: str,
    vm_name: str,
    vm_display_name: str,
    partition_factor: float,
    fixed_overhead_minutes: float,
    tool_breakdown: List[Dict[str, Any]],
    total_input_size_mib: float,
    assumptions: List[str],
) -> str:
    payload = {
        "execution_shape": execution_shape,
        "vm_name": vm_name,
        "vm_display_name": vm_display_name,
        "partition_factor": partition_factor,
        "fixed_overhead_minutes": fixed_overhead_minutes,
        "total_input_size_mib": total_input_size_mib,
        "tool_breakdown": tool_breakdown,
        "assumptions": assumptions,
    }
    return (
        "You are estimating total runtime in minutes for a bioinformatics workflow. "
        "Use the provided tool breakdown, input sizes, and VM partition factor. "
        "Return ONLY one comma-separated line in this exact format: estimated_runtime_minutes,confidence,rationale. "
        "Rules: estimated_runtime_minutes must be an integer >= 1; confidence must be a decimal between 0 and 1; "
        "rationale must be plain text, under 16 words, and must not contain commas. Do not include markdown, labels, or extra lines.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _request_gemini_runtime_minutes(prompt: str) -> Optional[Dict[str, Any]]:
    settings = _load_gemini_prediction_settings()
    if not settings.enabled:
        return None

    api_key = os.getenv(settings.api_key_env_var, "").strip()
    if not api_key:
        logger.warning("Gemini runtime prediction enabled but %s is not set.", settings.api_key_env_var)
        return None

    endpoint = (
        f"{settings.api_base_url.rstrip('/')}/v1beta/models/{settings.model}:generateContent"
        f"?key={api_key}"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": settings.temperature,
            "maxOutputTokens": settings.max_output_tokens,
        },
    }

    request = urllib_request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=settings.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Gemini runtime prediction request failed: %s", exc)
        return None

    try:
        candidates = payload.get("candidates", [])
        first_candidate = candidates[0] if candidates else {}
        content = first_candidate.get("content", {}) if isinstance(first_candidate, dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text_payload = ""
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text_payload += str(part["text"])
        if not text_payload.strip():
            return None
        normalized_text = " ".join(str(text_payload).strip().splitlines()).strip()
        parts = [part.strip() for part in normalized_text.split(",", 2)]
        if len(parts) < 3:
            return None
        estimated_runtime_minutes = max(1, int(float(parts[0])))
        confidence = float(parts[1] or 0.0)
        rationale = parts[2].strip()
        return {
            "estimated_runtime_minutes": estimated_runtime_minutes,
            "confidence": max(0.0, min(confidence, 1.0)),
            "rationale": rationale,
        }
    except Exception as exc:
        logger.warning("Gemini runtime prediction payload could not be parsed: %s", exc)
        return None


def _apply_optional_gemini_runtime_prediction(estimate: RuntimeEstimate) -> RuntimeEstimate:
    settings = _load_gemini_prediction_settings()
    if not settings.enabled:
        return estimate

    prompt = _build_gemini_runtime_prompt(
        execution_shape=estimate.execution_shape,
        vm_name=estimate.vm_name,
        vm_display_name=estimate.vm_display_name,
        partition_factor=estimate.partition_factor,
        fixed_overhead_minutes=estimate.fixed_overhead_minutes,
        tool_breakdown=estimate.tool_breakdown,
        total_input_size_mib=estimate.total_input_size_mib,
        assumptions=estimate.assumptions,
    )
    gemini_result = _request_gemini_runtime_minutes(prompt)
    if not gemini_result:
        return estimate

    estimated_minutes = max(1, int(gemini_result["estimated_runtime_minutes"]))
    return RuntimeEstimate(
        model_type=f"{estimate.model_type}+gemini-runtime",
        vm_name=estimate.vm_name,
        vm_display_name=estimate.vm_display_name,
        partition_factor=estimate.partition_factor,
        vm_price_per_minute=estimate.vm_price_per_minute,
        total_input_size_mib=estimate.total_input_size_mib,
        estimated_runtime_minutes=estimated_minutes,
        estimated_runtime_hours=round(estimated_minutes / 60.0, 2),
        estimated_price_usd=round(estimated_minutes * estimate.vm_price_per_minute, 2),
        fixed_overhead_minutes=estimate.fixed_overhead_minutes,
        execution_shape=estimate.execution_shape,
        tool_breakdown=estimate.tool_breakdown,
        assumptions=[
            *estimate.assumptions,
            (
                "Final runtime minutes were refined with the optional Gemini predictor configured in config.json; "
                f"reported confidence={gemini_result['confidence']:.2f}."
            ),
            gemini_result["rationale"] or "Gemini supplied a runtime-only refinement.",
        ],
    )


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
    fixed_overhead = _fixed_overhead_minutes()
    grouped_assignments = _group_input_assignments(input_assignments)
    effective_input_sizes = _estimate_tool_input_sizes_for_sequence(tool_ids, grouped_assignments)
    breakdown = _build_tool_breakdown(tool_ids, partition_factor, effective_input_sizes)
    sequential_minutes = sum(item["adjusted_minutes"] for item in breakdown)
    estimated_minutes = max(1, round(sequential_minutes + fixed_overhead))
    total_input_size_mib = _total_explicit_input_size_mib(grouped_assignments)
    estimated_price_usd = round(estimated_minutes * vm_price_per_minute, 2)

    estimate = RuntimeEstimate(
        model_type="deterministic-heuristic",
        vm_name=resolved_vm_name,
        vm_display_name=display_name,
        partition_factor=partition_factor,
        vm_price_per_minute=vm_price_per_minute,
        total_input_size_mib=total_input_size_mib,
        estimated_runtime_minutes=estimated_minutes,
        estimated_runtime_hours=round(estimated_minutes / 60.0, 2),
        estimated_price_usd=estimated_price_usd,
        fixed_overhead_minutes=fixed_overhead,
        execution_shape="sequential-tools",
        tool_breakdown=breakdown,
        assumptions=[
            "Uses tool-specific baseline runtimes from runtime_estimator_profiles.json.",
            "Applies a VM partition multiplier so higher-density partitions predict slower per-job runtimes.",
            "Scales each tool using total mapped input sizes; downstream intermediate inputs are inferred from upstream output-size multipliers.",
        ],
    )
    return _apply_optional_gemini_runtime_prediction(estimate)


def estimate_runtime_for_pipeline_graph(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    vm_name: Optional[str],
    input_assignments: Optional[List[RuntimeInputAssignment]] = None,
) -> RuntimeEstimate:
    from backend.api.services.pipeline_converter import resolve_node_tool_id

    resolved_vm_name, display_name, partition_factor = _vm_speed_multiplier(vm_name)
    vm_price_per_minute = _vm_price_per_minute(resolved_vm_name)
    fixed_overhead = _fixed_overhead_minutes()

    tool_ids: List[str] = []
    weighted_node_minutes: Dict[str, float] = {}
    output_sizes_by_node: Dict[str, float] = {}
    input_sizes_by_node: Dict[str, float] = {}
    grouped_assignments = _group_input_assignments(input_assignments)

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
        weighted_node_minutes[node_id] = _tool_base_minutes(tool_id) * partition_factor * _size_factor(tool_id, effective_input_size)
        output_sizes_by_node[node_id] = max(1.0, effective_input_size * _tool_output_size_multiplier(tool_id))

    breakdown = _build_tool_breakdown(
        tool_ids,
        partition_factor,
        {tool_id: sum(grouped_assignments.get(tool_id, {}).values()) or _tool_reference_input_mib(tool_id) for tool_id in tool_ids},
    )

    critical_path_minutes, branch_factor = _topological_layers(nodes, edges, weighted_node_minutes)
    orchestration_penalty = max(0.0, (branch_factor - 1) * 4.0)
    estimated_minutes = max(1, round(critical_path_minutes + fixed_overhead + orchestration_penalty))
    total_input_size_mib = _total_explicit_input_size_mib(grouped_assignments)
    estimated_price_usd = round(estimated_minutes * vm_price_per_minute, 2)

    estimate = RuntimeEstimate(
        model_type="deterministic-dag-heuristic",
        vm_name=resolved_vm_name,
        vm_display_name=display_name,
        partition_factor=partition_factor,
        vm_price_per_minute=vm_price_per_minute,
        total_input_size_mib=total_input_size_mib,
        estimated_runtime_minutes=estimated_minutes,
        estimated_runtime_hours=round(estimated_minutes / 60.0, 2),
        estimated_price_usd=estimated_price_usd,
        fixed_overhead_minutes=fixed_overhead,
        execution_shape="pipeline-critical-path",
        tool_breakdown=breakdown,
        assumptions=[
            "Uses tool baseline runtimes and estimates total runtime from the pipeline DAG critical path.",
            "Adds a small orchestration penalty when the graph branches into parallel stages.",
            "Mapped input sizes are propagated through downstream intermediate tools using per-tool output size multipliers.",
        ],
    )
    return _apply_optional_gemini_runtime_prediction(estimate)
