"""
Intent-driven pipeline recommendation service.

This service converts user intentions plus available input file summaries into
ranked pipeline options. The registry is intentionally declarative so new tools
and future intentions can be added without rewriting the planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Set

from tool_registry import get_tool_by_id, get_tool_index_by_id


INTENT_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "read_quality",
        "label": "Check read quality",
        "description": "Assess the quality of FASTQ reads.",
        "requires": {"fastq": 1},
        "adds_tools": ["FASTQC"],
        "tags": ["qc", "reads"],
    },
    {
        "id": "genomic_properties_from_reads",
        "label": "Estimate genomic properties from reads",
        "description": "Use read k-mer profiles to estimate genome characteristics.",
        "requires": {"fastq": 1},
        "adds_tools": ["GENOMESCOPE2"],
        "tags": ["qc", "kmer", "reads"],
    },
    {
        "id": "assembly_from_short_reads",
        "label": "Assemble genome from short reads",
        "description": "Build an assembly from paired short-read FASTQ files.",
        "requires": {"fastq": 2},
        "adds_tools": ["SPADES"],
        "tags": ["assembly", "short-read"],
    },
    {
        "id": "assembly_quality_against_reference",
        "label": "Assess assembly quality against a reference",
        "description": "Compare an assembly against a reference FASTA.",
        "requires": {"fasta": 1},
        "adds_tools": ["QUAST"],
        "depends_on_any": ["SPADES"],
        "tags": ["qc", "assembly", "reference"],
    },
]


PIPELINE_STRATEGIES: List[Dict[str, Any]] = [
    {
        "id": "comprehensive",
        "title": "Comprehensive Analysis",
        "description": "Includes all tools needed to satisfy the selected intentions.",
        "include_all_intents": True,
        "priority": 100,
        "tags": ["comprehensive"],
    },
    {
        "id": "assembly_focused",
        "title": "Assembly-Focused Pipeline",
        "description": "Prioritizes assembly and downstream assembly evaluation.",
        "intent_subset": ["assembly_from_short_reads", "assembly_quality_against_reference"],
        "priority": 80,
        "tags": ["assembly-focused"],
    },
    {
        "id": "read_qc_focused",
        "title": "Read QC Pipeline",
        "description": "Focuses on read quality and genomic property estimation.",
        "intent_subset": ["read_quality", "genomic_properties_from_reads"],
        "priority": 70,
        "tags": ["reads", "qc"],
    },
]


@dataclass(frozen=True)
class DetectedInputs:
    fastq_count: int
    fasta_count: int

    @property
    def has_paired_fastq(self) -> bool:
        return self.fastq_count >= 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fastq_count": self.fastq_count,
            "fasta_count": self.fasta_count,
            "has_fastq": self.fastq_count > 0,
            "has_paired_fastq": self.has_paired_fastq,
            "has_fasta": self.fasta_count > 0,
        }


def get_recommendation_intents() -> List[Dict[str, Any]]:
    return [
        {
            "id": intent["id"],
            "label": intent["label"],
            "description": intent["description"],
            "tags": list(intent.get("tags", [])),
        }
        for intent in INTENT_REGISTRY
    ]


def _normalize_file_format(file_entry: Dict[str, Any]) -> str:
    file_format = str(file_entry.get("file_format") or "").strip().lower().lstrip(".")
    filename = str(file_entry.get("filename") or "").strip().lower()

    if file_format:
        return file_format
    if filename.endswith((".fastq", ".fastq.gz", ".fq", ".fq.gz")):
        return "fastq"
    if filename.endswith((".fasta", ".fasta.gz", ".fa", ".fa.gz", ".fna", ".fna.gz")):
        return "fasta"
    return ""


def detect_input_capabilities(file_entries: List[Dict[str, Any]]) -> DetectedInputs:
    fastq_count = 0
    fasta_count = 0
    for file_entry in file_entries:
        normalized = _normalize_file_format(file_entry)
        if normalized == "fastq":
            fastq_count += 1
        elif normalized == "fasta":
            fasta_count += 1
    return DetectedInputs(fastq_count=fastq_count, fasta_count=fasta_count)


def _get_intent(intent_id: str) -> Dict[str, Any] | None:
    for intent in INTENT_REGISTRY:
        if intent["id"] == intent_id:
            return intent
    return None


def _collect_missing_inputs(intent: Dict[str, Any], detected: DetectedInputs, selected_tools: Set[str]) -> List[str]:
    missing: List[str] = []
    requires = intent.get("requires", {})
    if requires.get("fastq", 0) > detected.fastq_count:
        needed = int(requires["fastq"])
        if needed >= 2:
            missing.append("paired FASTQ reads")
        else:
            missing.append("FASTQ reads")

    if requires.get("fasta", 0) > detected.fasta_count:
        missing.append("FASTA reference")

    depends_on_any = intent.get("depends_on_any", [])
    if depends_on_any and not any(tool_id in selected_tools for tool_id in depends_on_any):
        dependency_labels = [get_tool_by_id(tool_id).get("name", tool_id) for tool_id in depends_on_any if get_tool_by_id(tool_id)]
        missing.append(f"upstream tool dependency ({', '.join(dependency_labels) or 'previous tool output'})")

    return missing


def _build_option(strategy: Dict[str, Any], selected_intent_ids: List[str], detected: DetectedInputs) -> Dict[str, Any] | None:
    if strategy.get("include_all_intents"):
        candidate_intent_ids = list(selected_intent_ids)
    else:
        allowed_subset = set(strategy.get("intent_subset", []))
        candidate_intent_ids = [intent_id for intent_id in selected_intent_ids if intent_id in allowed_subset]

    if not candidate_intent_ids:
        return None

    if set(candidate_intent_ids) != set(selected_intent_ids):
        return None

    selected_tools: List[str] = []
    rationale: List[str] = []
    missing_inputs: List[str] = []
    assumptions: List[str] = []

    for intent_id in candidate_intent_ids:
        intent = _get_intent(intent_id)
        if not intent:
            continue

        for tool_id in intent.get("adds_tools", []):
            if tool_id not in selected_tools:
                selected_tools.append(tool_id)

        rationale.append(intent["label"])

    selected_tool_set = set(selected_tools)
    for intent_id in candidate_intent_ids:
        intent = _get_intent(intent_id)
        if not intent:
            continue
        missing_inputs.extend(_collect_missing_inputs(intent, detected, selected_tool_set))

    if "QUAST" in selected_tool_set and "SPADES" in selected_tool_set:
        assumptions.append("QUAST assembly input will be satisfied by SPAdes output when connected in the selected workflow.")

    deduped_missing = list(dict.fromkeys(missing_inputs))
    tool_indices = [get_tool_index_by_id(tool_id) for tool_id in selected_tools]
    tool_indices = [index for index in tool_indices if isinstance(index, int)]
    tool_names = [get_tool_by_id(tool_id).get("name", tool_id) for tool_id in selected_tools if get_tool_by_id(tool_id)]

    score = strategy.get("priority", 0) - (len(deduped_missing) * 10)
    return {
        "id": strategy["id"],
        "title": strategy["title"],
        "summary": strategy["description"],
        "intent_ids": candidate_intent_ids,
        "tool_ids": selected_tools,
        "tool_indices": tool_indices,
        "tool_names": tool_names,
        "missing_inputs": deduped_missing,
        "assumptions": assumptions,
        "rationale": rationale,
        "tags": list(strategy.get("tags", [])),
        "score": score,
    }


def recommend_pipelines(intent_ids: List[str], file_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    detected = detect_input_capabilities(file_entries)
    normalized_intents = [intent_id for intent_id in intent_ids if _get_intent(intent_id)]

    unique_options: Dict[tuple[Any, ...], Dict[str, Any]] = {}
    for strategy in PIPELINE_STRATEGIES:
        option = _build_option(strategy, normalized_intents, detected)
        if option:
            dedupe_key = (
                tuple(option["tool_ids"]),
                tuple(option["intent_ids"]),
                tuple(option["missing_inputs"]),
                tuple(option["assumptions"]),
            )
            existing_option = unique_options.get(dedupe_key)
            if not existing_option or option["score"] > existing_option["score"]:
                unique_options[dedupe_key] = option

    options = list(unique_options.values())

    options.sort(key=lambda option: (-option["score"], len(option["missing_inputs"]), len(option["tool_ids"])))

    return {
        "intents": get_recommendation_intents(),
        "detected_inputs": detected.to_dict(),
        "pipeline_options": options,
    }
