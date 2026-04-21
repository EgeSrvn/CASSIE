"""Machine hardware helpers used for FLOPS estimation."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MACHINE_SPECS_CONFIG_PATH = PROJECT_ROOT / "config" / "specs.json"

DEFAULT_SPECS_METRICS: Dict[str, Any] = {
    "CPU": "Intel Core i7-10750H",
    "Architecture": "Comet Lake (10th Gen)",
    "Cores": 6,
    "Threads": 12,
    "Base Clock": "2.60 GHz",
    "Max Turbo": "Up to 5.00 GHz",
    "SIMD Support": "AVX2,FMA,SSE",
    "FP64 Peak @ Base Clock": "~250 GFLOP/s",
    "FP64 Peak @ Turbo (idealized)": "~480 GFLOP/s",
    "FP32 Peak @ Base Clock": "~500 GFLOP/s",
    "FP32 Peak @ Turbo (idealized)": "~960 GFLOP/s",
    "Typical Real Scalar Code": "~5-50 GFLOP/s",
    "Typical Optimized Multithreaded Code": "~50-150 GFLOP/s",
    "Highly Optimized BLAS / GEMM": "~150-300+ GFLOP/s",
    "Memory Installed": "4 GB",
}


@dataclass(frozen=True)
class MachineSpecs:
    cpu: str
    architecture: str
    cores: int
    threads: int
    base_clock_ghz: float
    max_turbo_ghz: float
    simd_support: Tuple[str, ...]
    fp64_peak_gflops_base: float
    fp64_peak_gflops_turbo: float
    fp32_peak_gflops_base: float
    fp32_peak_gflops_turbo: float
    memory_installed_gb: float
    source: str

    @property
    def fp64_flops_per_core_second(self) -> float:
        if self.cores <= 0:
            return 0.0
        return max(0.0, self.fp64_peak_gflops_base / self.cores) * 1_000_000_000.0

    @property
    def simd_summary(self) -> str:
        return ", ".join(self.simd_support) if self.simd_support else "scalar"


def _first_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _parse_metric_map(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        metrics = payload.get("metrics")
        if isinstance(metrics, list):
            normalized: Dict[str, Any] = {}
            for item in metrics:
                if not isinstance(item, dict):
                    continue
                metric = str(item.get("metric") or "").strip()
                if metric:
                    normalized[metric] = item.get("value")
            return normalized
        return {str(key): value for key, value in payload.items()}
    return {}


def _read_config_metrics() -> Dict[str, Any]:
    if not MACHINE_SPECS_CONFIG_PATH.exists():
        return dict(DEFAULT_SPECS_METRICS)

    try:
        payload = json.loads(MACHINE_SPECS_CONFIG_PATH.read_text(encoding="utf-8"))
        parsed = _parse_metric_map(payload)
        return parsed or dict(DEFAULT_SPECS_METRICS)
    except Exception as exc:
        logger.warning("Failed to read machine specs config %s: %s", MACHINE_SPECS_CONFIG_PATH, exc)
        return dict(DEFAULT_SPECS_METRICS)


def _read_proc_cpuinfo() -> Dict[str, str]:
    cpuinfo_path = Path("/proc/cpuinfo")
    if not cpuinfo_path.exists():
        return {}

    info: Dict[str, str] = {}
    try:
        for line in cpuinfo_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "model name" and "model_name" not in info:
                info["model_name"] = value
            elif key == "flags" and "flags" not in info:
                info["flags"] = value
            elif key == "cpu cores" and "cpu_cores" not in info:
                info["cpu_cores"] = value
            elif key == "siblings" and "siblings" not in info:
                info["siblings"] = value
    except Exception as exc:
        logger.debug("Failed to read /proc/cpuinfo: %s", exc)
    return info


def _read_meminfo_total_gb() -> Optional[float]:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return None

    try:
        for line in meminfo_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.startswith("MemTotal:"):
                continue
            parts = line.split()
            if len(parts) < 2:
                return None
            kib = float(parts[1])
            return kib / (1024.0 * 1024.0)
    except Exception as exc:
        logger.debug("Failed to read /proc/meminfo: %s", exc)
    return None


def _read_lscpu_fields() -> Dict[str, str]:
    commands = (["lscpu", "-J"], ["lscpu"])
    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            continue

        if command[-1] == "-J":
            try:
                payload = json.loads(result.stdout)
                entries = payload.get("lscpu") if isinstance(payload, dict) else None
                if isinstance(entries, list):
                    parsed: Dict[str, str] = {}
                    for item in entries:
                        if not isinstance(item, dict):
                            continue
                        field = str(item.get("field") or "").rstrip(":").strip()
                        data = str(item.get("data") or "").strip()
                        if field:
                            parsed[field] = data
                    if parsed:
                        return parsed
            except Exception:
                continue
        else:
            parsed = {}
            for line in result.stdout.splitlines():
                if ":" not in line:
                    continue
                field, data = line.split(":", 1)
                field = field.strip()
                data = data.strip()
                if field:
                    parsed[field] = data
            if parsed:
                return parsed

    return {}


def _parse_simd_support(value: Any) -> Tuple[str, ...]:
    if not value:
        return tuple()

    raw = str(value).replace(",", " ").lower()
    tokens = set(token.strip() for token in raw.split() if token.strip())
    simd: list[str] = []
    if "avx512f" in tokens or "avx512" in tokens:
        simd.append("AVX512")
    elif "avx2" in tokens:
        simd.append("AVX2")
    elif "avx" in tokens:
        simd.append("AVX")

    if "fma" in tokens or "fma3" in tokens or "fma4" in tokens:
        simd.append("FMA")

    if any(token.startswith("sse") for token in tokens):
        simd.append("SSE")

    return tuple(simd)


def _extract_clock_from_model_name(model_name: str) -> Optional[float]:
    match = re.search(r"@\s*([0-9]+(?:\.[0-9]+)?)\s*GHz", model_name, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _vector_lane_count(simd_support: Iterable[str], *, precision: str) -> int:
    simd = {item.upper() for item in simd_support}
    if "AVX512" in simd:
        return 8 if precision == "fp64" else 16
    if "AVX2" in simd or "AVX" in simd:
        return 4 if precision == "fp64" else 8
    if "SSE" in simd:
        return 2 if precision == "fp64" else 4
    return 1


def _flops_per_cycle_per_core(simd_support: Iterable[str], *, precision: str) -> float:
    simd = {item.upper() for item in simd_support}
    lanes = _vector_lane_count(simd, precision=precision)
    instruction_factor = 2.0 if "FMA" in simd else 1.0
    execution_units = 2.0
    return lanes * instruction_factor * execution_units


def _compute_peak_gflops(clock_ghz: float, cores: int, simd_support: Iterable[str], *, precision: str) -> float:
    if clock_ghz <= 0 or cores <= 0:
        return 0.0
    return clock_ghz * cores * _flops_per_cycle_per_core(simd_support, precision=precision)


def _detect_machine_metrics() -> Dict[str, Any]:
    lscpu_fields = _read_lscpu_fields()
    proc_cpuinfo = _read_proc_cpuinfo()

    model_name = (
        str(lscpu_fields.get("Model name") or "").strip()
        or str(proc_cpuinfo.get("model_name") or "").strip()
    )
    architecture = str(lscpu_fields.get("Architecture") or "").strip()

    thread_count = _first_number(lscpu_fields.get("CPU(s)"))
    core_count = None
    cores_per_socket = _first_number(lscpu_fields.get("Core(s) per socket"))
    socket_count = _first_number(lscpu_fields.get("Socket(s)"))
    threads_per_core = _first_number(lscpu_fields.get("Thread(s) per core"))

    if cores_per_socket and socket_count:
        core_count = int(cores_per_socket * socket_count)
    elif proc_cpuinfo.get("cpu_cores"):
        parsed_cores = _first_number(proc_cpuinfo.get("cpu_cores"))
        if parsed_cores:
            core_count = int(parsed_cores)
    elif thread_count and threads_per_core:
        core_count = int(thread_count / max(threads_per_core, 1))

    max_turbo_ghz = 0.0
    for key in ("CPU max MHz", "Max MHz"):
        value = _first_number(lscpu_fields.get(key))
        if value:
            max_turbo_ghz = value / 1000.0
            break

    base_clock_ghz = _extract_clock_from_model_name(model_name)
    min_mhz = _first_number(lscpu_fields.get("CPU min MHz") or lscpu_fields.get("Min MHz"))
    if not base_clock_ghz and min_mhz:
        base_clock_ghz = min_mhz / 1000.0

    flags = str(lscpu_fields.get("Flags") or proc_cpuinfo.get("flags") or "").strip()
    simd_support = _parse_simd_support(flags)
    memory_installed_gb = _read_meminfo_total_gb()

    detected: Dict[str, Any] = {}
    if model_name:
        detected["CPU"] = model_name
    if architecture:
        detected["Architecture"] = architecture
    if core_count and core_count > 0:
        detected["Cores"] = core_count
    if thread_count and thread_count > 0:
        detected["Threads"] = int(thread_count)
    if base_clock_ghz and base_clock_ghz > 0:
        detected["Base Clock"] = f"{base_clock_ghz:.2f} GHz"
    if max_turbo_ghz and max_turbo_ghz > 0:
        detected["Max Turbo"] = f"{max_turbo_ghz:.2f} GHz"
    if simd_support:
        detected["SIMD Support"] = ",".join(simd_support)
    if memory_installed_gb and memory_installed_gb > 0:
        detected["Memory Installed"] = f"{memory_installed_gb:.2f} GB"
    return detected


@lru_cache(maxsize=1)
def get_machine_specs() -> MachineSpecs:
    configured_metrics = _read_config_metrics()
    detected_metrics = _detect_machine_metrics()
    merged_metrics = dict(configured_metrics)
    merged_metrics.update(detected_metrics)

    cpu = str(merged_metrics.get("CPU") or "").strip()
    architecture = str(merged_metrics.get("Architecture") or "").strip()
    cores = max(1, int(_first_number(merged_metrics.get("Cores")) or 1))
    threads = max(cores, int(_first_number(merged_metrics.get("Threads")) or cores))
    base_clock_ghz = float(_first_number(merged_metrics.get("Base Clock")) or 0.0)
    max_turbo_ghz = float(_first_number(merged_metrics.get("Max Turbo")) or 0.0)
    simd_support = _parse_simd_support(merged_metrics.get("SIMD Support"))
    memory_installed_gb = float(_first_number(merged_metrics.get("Memory Installed")) or 0.0)

    fp64_peak_gflops_base = _compute_peak_gflops(base_clock_ghz, cores, simd_support, precision="fp64")
    fp64_peak_gflops_turbo = _compute_peak_gflops(max_turbo_ghz, cores, simd_support, precision="fp64")
    fp32_peak_gflops_base = _compute_peak_gflops(base_clock_ghz, cores, simd_support, precision="fp32")
    fp32_peak_gflops_turbo = _compute_peak_gflops(max_turbo_ghz, cores, simd_support, precision="fp32")

    if fp64_peak_gflops_base <= 0:
        fp64_peak_gflops_base = float(_first_number(configured_metrics.get("FP64 Peak @ Base Clock")) or 0.0)
    if fp64_peak_gflops_turbo <= 0:
        fp64_peak_gflops_turbo = float(_first_number(configured_metrics.get("FP64 Peak @ Turbo (idealized)")) or 0.0)
    if fp32_peak_gflops_base <= 0:
        fp32_peak_gflops_base = float(_first_number(configured_metrics.get("FP32 Peak @ Base Clock")) or 0.0)
    if fp32_peak_gflops_turbo <= 0:
        fp32_peak_gflops_turbo = float(_first_number(configured_metrics.get("FP32 Peak @ Turbo (idealized)")) or 0.0)

    source = "machine+config" if detected_metrics else "config"
    return MachineSpecs(
        cpu=cpu,
        architecture=architecture,
        cores=cores,
        threads=threads,
        base_clock_ghz=base_clock_ghz,
        max_turbo_ghz=max_turbo_ghz,
        simd_support=simd_support,
        fp64_peak_gflops_base=fp64_peak_gflops_base,
        fp64_peak_gflops_turbo=fp64_peak_gflops_turbo,
        fp32_peak_gflops_base=fp32_peak_gflops_base,
        fp32_peak_gflops_turbo=fp32_peak_gflops_turbo,
        memory_installed_gb=memory_installed_gb,
        source=source,
    )
