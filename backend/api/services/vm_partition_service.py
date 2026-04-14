"""
VM partition configuration helpers.

Loads VM definitions from a root-level JSON config so job creation and runtime
resource partitioning share the same source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VM_PARTITION_CONFIG_PATH = PROJECT_ROOT / "vm_partitions.json"


@dataclass(frozen=True)
class VMPartition:
    name: str
    display_name: str
    max_pods: int


DEFAULT_VM_PARTITIONS: List[VMPartition] = [
    VMPartition(name="vm1", display_name="VM1", max_pods=1),
    VMPartition(name="vm2", display_name="VM2", max_pods=2),
    VMPartition(name="vm3", display_name="VM3", max_pods=3),
]


def _normalize_vm_partition(raw: object) -> Optional[VMPartition]:
    if not isinstance(raw, dict):
        return None

    name = str(raw.get("name") or "").strip()
    display_name = str(raw.get("display_name") or name.upper()).strip()
    max_pods_raw = raw.get("max_pods")

    try:
        max_pods = max(1, int(max_pods_raw))
    except (TypeError, ValueError):
        return None

    if not name:
        return None

    return VMPartition(name=name, display_name=display_name or name.upper(), max_pods=max_pods)


def get_vm_partitions() -> List[VMPartition]:
    if not VM_PARTITION_CONFIG_PATH.exists():
        return list(DEFAULT_VM_PARTITIONS)

    try:
        payload = json.loads(VM_PARTITION_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to read VM partition config {VM_PARTITION_CONFIG_PATH}: {exc}")
        return list(DEFAULT_VM_PARTITIONS)

    raw_vms = payload.get("vms") if isinstance(payload, dict) else None
    if not isinstance(raw_vms, list):
        logger.warning(f"VM partition config {VM_PARTITION_CONFIG_PATH} is missing a valid 'vms' list")
        return list(DEFAULT_VM_PARTITIONS)

    partitions: List[VMPartition] = []
    for raw_vm in raw_vms:
        vm_partition = _normalize_vm_partition(raw_vm)
        if vm_partition:
            partitions.append(vm_partition)

    if len(partitions) != 3:
        logger.warning(
            f"VM partition config {VM_PARTITION_CONFIG_PATH} must define exactly 3 valid VMs; "
            f"found {len(partitions)}. Falling back to defaults."
        )
        return list(DEFAULT_VM_PARTITIONS)

    return partitions


def get_vm_partition(vm_name: Optional[str]) -> Optional[VMPartition]:
    if not vm_name:
        return None

    for partition in get_vm_partitions():
        if partition.name == vm_name:
            return partition

    return None
