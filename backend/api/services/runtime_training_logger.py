"""Append successful per-tool execution rows for runtime model training."""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from backend.api.services.machine_specs_service import get_machine_specs
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TRAINING_CSV_PATH = PROJECT_ROOT / "data" / "runtime_training" / "tool_runtime_training.csv"
DEFAULT_ESTIMATED_FLOPS_PER_CORE_SECOND = 4_000_000_000.0

CSV_COLUMNS = [
    "record_id",
    "recorded_at",
    "job_id",
    "execution_id",
    "user_id",
    "workflow_id",
    "pipeline_id",
    "vm_name",
    "stage_id",
    "stage_number",
    "tool_id",
    "tool_name",
    "input_size_bytes",
    "input_size_mib",
    "input_file_count",
    "input_types",
    "input_filenames",
    "output_count",
    "output_size_bytes",
    "runtime_seconds",
    "resource_profile",
    "threads",
    "cpu_limit_millis",
    "memory_limit_mib",
    "storage_limit_mib",
    "cpu_core_seconds",
    "allocated_cpu_core_seconds",
    "measured_cpu_core_seconds",
    "estimated_flops",
    "measured_flops",
    "flops_is_estimated",
    "flops_per_core_second",
    "flops_source",
    "flops_accuracy_note",
    "data_size_gb",
    "read_count_millions",
    "sample_count",
    "selected_tools",
    "input_formats",
    "pod_cpu_cores",
    "pod_memory_gb",
    "pod_ephemeral_storage_gb",
    "requested_threads",
    "cloud_provider",
    "instance_family",
]

_csv_lock = threading.Lock()


def _training_csv_path() -> Path:
    return Path(os.getenv("CASSIE_RUNTIME_TRAINING_CSV", str(DEFAULT_TRAINING_CSV_PATH)))


def _machine_flops_profile() -> tuple[float, str, str]:
    try:
        machine_specs = get_machine_specs()
        flops_per_core_second = machine_specs.fp64_flops_per_core_second
        if flops_per_core_second > 0:
            details = [
                machine_specs.cpu or "unknown CPU",
                f"{machine_specs.base_clock_ghz:.2f} GHz base" if machine_specs.base_clock_ghz > 0 else "",
                machine_specs.simd_summary,
            ]
            details_text = ", ".join(item for item in details if item)
            return (
                flops_per_core_second,
                f"machine_specs_{machine_specs.source}",
                "Estimated from measured container CPU seconds and machine-derived FP64 peak per-core throughput "
                f"({details_text}). It is not hardware-counter-measured FLOPs.",
            )
    except Exception as exc:
        logger.warning("Failed to derive FLOPS from machine specs: %s", exc)

    return (
        DEFAULT_ESTIMATED_FLOPS_PER_CORE_SECOND,
        "fallback_fixed_coefficient",
        "Estimated from measured container CPU seconds and a conservative fallback FLOPS-per-core coefficient. "
        "It is not hardware-counter-measured FLOPs.",
    )


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed_seconds(started_at: Any, completed_at: Any) -> float:
    started = _parse_timestamp(started_at)
    completed = _parse_timestamp(completed_at)
    if not started or not completed:
        return 0.0
    return max(0.0, (completed - started).total_seconds())


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _infer_input_types(artifacts: Iterable[Dict[str, Any]]) -> List[str]:
    types: set[str] = set()
    for artifact in artifacts:
        file_format = str(artifact.get("file_format") or "").strip().lower().lstrip(".")
        if file_format:
            types.add(file_format)

        filename = str(artifact.get("filename") or "").lower()
        if filename.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq")):
            types.add("fastq")
        elif filename.endswith((".fasta.gz", ".fa.gz", ".fna.gz", ".fasta", ".fa", ".fna")):
            types.add("fasta")
        elif filename.endswith((".gff3", ".gff", ".gtf")):
            types.add("annotation")
        elif filename.endswith(".hal"):
            types.add("hal")
        elif filename.endswith(".meryl") or ".meryl" in filename:
            types.add("meryl")
        elif filename.endswith((".txt", ".tsv", ".csv")):
            types.add("text")

    return sorted(types)


def _existing_record_ids(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()

    try:
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return {
                str(row.get("record_id") or "").strip()
                for row in reader
                if str(row.get("record_id") or "").strip()
            }
    except Exception as exc:
        logger.warning("Could not read existing runtime training CSV %s: %s", csv_path, exc)
        return set()


def _ensure_csv_schema(csv_path: Path) -> None:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return

    try:
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames == CSV_COLUMNS:
                return
            rows = list(reader)

        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

        logger.info("Migrated runtime training CSV schema at %s", csv_path)
    except Exception as exc:
        logger.warning("Could not migrate runtime training CSV schema %s: %s", csv_path, exc)


def _build_stage_row(
    *,
    job_id: int,
    execution_id: int,
    user_id: int,
    workflow_id: int,
    pipeline_id: Optional[int],
    vm_name: Optional[str],
    stage_spec: Dict[str, Any],
    stage_outputs: List[Dict[str, Any]],
    flops_per_core_second: float,
    flops_profile_source: str,
    flops_accuracy_note: str,
) -> Optional[Dict[str, Any]]:
    stage_info = stage_spec.get("stage_info") or {}
    if str(stage_spec.get("stage_kind") or "tool") != "tool":
        return None
    if str(stage_info.get("status") or "").lower() != "completed":
        return None

    stage_id = str(stage_spec.get("stage_id") or stage_info.get("stage_id") or "").strip()
    if not stage_id:
        return None

    tool = stage_spec.get("tool") or {}
    current_inputs = list(stage_spec.get("current_inputs") or [])
    input_size_bytes = sum(_safe_int(artifact.get("size_bytes")) for artifact in current_inputs)
    output_size_bytes = sum(_safe_int(artifact.get("size_bytes")) for artifact in stage_outputs)
    runtime_seconds = _elapsed_seconds(stage_info.get("started_at"), stage_info.get("completed_at"))
    cpu_limit_millis = _safe_int(stage_info.get("cpu_limit_millis"))
    if cpu_limit_millis <= 0:
        cpu_limit_millis = max(1, _safe_int(stage_info.get("threads"))) * 1000

    allocated_cpu_core_seconds = runtime_seconds * (cpu_limit_millis / 1000.0)
    measured_cpu_core_seconds = _safe_float(stage_info.get("measured_cpu_core_seconds"))
    cpu_core_seconds = measured_cpu_core_seconds if measured_cpu_core_seconds > 0 else allocated_cpu_core_seconds
    estimated_flops = cpu_core_seconds * flops_per_core_second if cpu_core_seconds > 0 else 0.0
    has_measured_cpu = measured_cpu_core_seconds > 0
    input_types = _infer_input_types(current_inputs)
    memory_limit_mib = _safe_int(stage_info.get("memory_limit_mib"))
    storage_limit_mib = _safe_int(stage_info.get("storage_limit_mib"))
    threads = _safe_int(stage_info.get("threads"))

    return {
        "record_id": f"{job_id}:{execution_id}:{stage_id}",
        "recorded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "job_id": job_id,
        "execution_id": execution_id,
        "user_id": user_id,
        "workflow_id": workflow_id,
        "pipeline_id": pipeline_id or "",
        "vm_name": vm_name or "",
        "stage_id": stage_id,
        "stage_number": _safe_int(stage_spec.get("stage_number") or stage_info.get("stage_number")),
        "tool_id": str(tool.get("id") or stage_info.get("tool_id") or "").strip(),
        "tool_name": str(tool.get("name") or stage_info.get("tool_name") or "").strip(),
        "input_size_bytes": input_size_bytes,
        "input_size_mib": round(input_size_bytes / (1024 * 1024), 6),
        "input_file_count": len(current_inputs),
        "input_types": ";".join(input_types),
        "input_filenames": ";".join(str(item.get("filename") or "") for item in current_inputs if item.get("filename")),
        "output_count": len(stage_outputs),
        "output_size_bytes": output_size_bytes,
        "runtime_seconds": round(runtime_seconds, 6),
        "resource_profile": stage_info.get("resource_profile") or "",
        "threads": threads,
        "cpu_limit_millis": cpu_limit_millis,
        "memory_limit_mib": memory_limit_mib,
        "storage_limit_mib": storage_limit_mib,
        "cpu_core_seconds": round(cpu_core_seconds, 6),
        "allocated_cpu_core_seconds": round(allocated_cpu_core_seconds, 6),
        "measured_cpu_core_seconds": round(measured_cpu_core_seconds, 6) if has_measured_cpu else "",
        "estimated_flops": round(estimated_flops, 6),
        "measured_flops": "",
        "flops_is_estimated": "true",
        "flops_per_core_second": flops_per_core_second,
        "flops_source": (
            f"{flops_profile_source}_and_measured_cgroup_cpu_seconds"
            if has_measured_cpu
            else f"{flops_profile_source}_and_cpu_limit_wall_time"
        ),
        "flops_accuracy_note": (
            flops_accuracy_note
            if has_measured_cpu
            else f"{flops_accuracy_note} Allocated CPU limit and wall time were used because measured container CPU seconds were unavailable."
        ),
        "data_size_gb": round(input_size_bytes / (1024 * 1024 * 1024), 9),
        "read_count_millions": "",
        "sample_count": len(current_inputs),
        "selected_tools": str(tool.get("id") or stage_info.get("tool_id") or "").strip(),
        "input_formats": ",".join(input_types),
        "pod_cpu_cores": round(cpu_limit_millis / 1000.0, 6),
        "pod_memory_gb": round(memory_limit_mib / 1024.0, 6),
        "pod_ephemeral_storage_gb": round(storage_limit_mib / 1024.0, 6),
        "requested_threads": threads,
        "cloud_provider": "local-kubernetes",
        "instance_family": vm_name or "unknown",
    }


def append_successful_tool_training_rows(
    *,
    job_id: int,
    execution_id: int,
    user_id: int,
    workflow_id: int,
    pipeline_id: Optional[int],
    vm_name: Optional[str],
    stage_specs: List[Dict[str, Any]],
    outputs_by_stage: Dict[str, List[Dict[str, Any]]],
) -> int:
    """Append one CSV row per completed tool stage."""
    flops_per_core_second, flops_profile_source, flops_accuracy_note = _machine_flops_profile()
    rows = []
    for stage_spec in stage_specs:
        stage_id = str(stage_spec.get("stage_id") or "").strip()
        row = _build_stage_row(
            job_id=job_id,
            execution_id=execution_id,
            user_id=user_id,
            workflow_id=workflow_id,
            pipeline_id=pipeline_id,
            vm_name=vm_name,
            stage_spec=stage_spec,
            stage_outputs=outputs_by_stage.get(stage_id) or [],
            flops_per_core_second=flops_per_core_second,
            flops_profile_source=flops_profile_source,
            flops_accuracy_note=flops_accuracy_note,
        )
        if row:
            rows.append(row)

    if not rows:
        return 0

    csv_path = _training_csv_path()
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with _csv_lock:
        _ensure_csv_schema(csv_path)
        existing_ids = _existing_record_ids(csv_path)
        new_rows = [row for row in rows if row["record_id"] not in existing_ids]
        if not new_rows:
            return 0

        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)

    logger.info("Appended %s runtime training row(s) to %s", len(new_rows), csv_path)
    return len(new_rows)
