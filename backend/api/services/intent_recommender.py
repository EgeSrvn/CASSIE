"""
Intent-driven pipeline recommendation service.

This service converts user intentions plus available input file summaries into
ranked pipeline options. The registry is intentionally declarative so new tools
and future intentions can be added without rewriting the planner.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Set

from tool_registry import get_tool_by_id, get_tool_index_by_id, get_tool_registry


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
        "id": "metagenome_assembly",
        "label": "Assemble a metagenome",
        "description": "Assemble mixed microbial community reads with a metagenomics-aware assembler.",
        "requires": {"fastq": 2},
        "adds_tools": ["METASPADES"],
        "tags": ["assembly", "metagenomics", "short-read"],
    },
    {
        "id": "long_read_hifi_assembly",
        "label": "Assemble HiFi long reads",
        "description": "Build a genome assembly from HiFi long-read FASTQ or FASTA inputs.",
        "requires": {"sequence": 1},
        "adds_tools": ["HIFIASM"],
        "tags": ["assembly", "long-read", "hifi"],
    },
    {
        "id": "telomere_to_telomere_assembly",
        "label": "Create a T2T-style long-read assembly",
        "description": "Use Verkko for high-contiguity long-read assembly workflows.",
        "requires": {"sequence": 1},
        "adds_tools": ["VERKKO"],
        "tags": ["assembly", "long-read", "t2t"],
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
    {
        "id": "assembly_completeness",
        "label": "Check assembly completeness",
        "description": "Assess genome or assembly completeness using conserved orthologs.",
        "requires": {"fasta": 1},
        "adds_tools": ["BUSCO"],
        "tags": ["qc", "assembly", "completeness"],
    },
    {
        "id": "assembly_kmer_quality",
        "label": "Evaluate assembly with read k-mers",
        "description": "Estimate assembly consensus quality and completeness with a read k-mer database.",
        "requires": {"fasta": 1, "meryl": 1},
        "adds_tools": ["MERQURY"],
        "tags": ["qc", "assembly", "kmer"],
    },
    {
        "id": "annotation_liftover",
        "label": "Lift annotations to a new assembly",
        "description": "Transfer reference annotations onto a target assembly.",
        "requires": {"fasta": 2, "annotation": 1},
        "adds_tools": ["LIFTOFF"],
        "tags": ["annotation", "comparative-genomics"],
    },
    {
        "id": "comparative_annotation",
        "label": "Run comparative annotation",
        "description": "Use a HAL alignment and reference annotation for Comparative Annotation Toolkit analysis.",
        "requires": {"hal": 1, "annotation": 1, "txt": 1},
        "adds_tools": ["CAT"],
        "tags": ["annotation", "comparative-genomics", "hal"],
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
        "intent_subset": [
            "assembly_from_short_reads",
            "metagenome_assembly",
            "long_read_hifi_assembly",
            "telomere_to_telomere_assembly",
            "assembly_quality_against_reference",
            "assembly_completeness",
            "assembly_kmer_quality",
        ],
        "priority": 80,
        "tags": ["assembly-focused"],
    },
    {
        "id": "metagenomics_focused",
        "title": "Metagenomics Pipeline",
        "description": "Uses metagenome-aware assembly and optional downstream assembly checks.",
        "intent_subset": ["metagenome_assembly", "read_quality", "assembly_completeness", "assembly_kmer_quality"],
        "priority": 78,
        "tags": ["metagenomics", "assembly"],
    },
    {
        "id": "long_read_focused",
        "title": "Long-Read Assembly Pipeline",
        "description": "Builds a long-read assembly and can add assembly completeness or k-mer quality checks.",
        "intent_subset": [
            "long_read_hifi_assembly",
            "telomere_to_telomere_assembly",
            "assembly_completeness",
            "assembly_kmer_quality",
        ],
        "priority": 76,
        "tags": ["long-read", "assembly"],
    },
    {
        "id": "annotation_focused",
        "title": "Annotation Pipeline",
        "description": "Focuses on annotation transfer or comparative annotation workflows.",
        "intent_subset": ["annotation_liftover", "comparative_annotation"],
        "priority": 74,
        "tags": ["annotation"],
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
    annotation_count: int
    hal_count: int
    meryl_count: int
    txt_count: int

    @property
    def has_paired_fastq(self) -> bool:
        return self.fastq_count >= 2

    @property
    def sequence_count(self) -> int:
        return self.fastq_count + self.fasta_count

    def count_for(self, requirement_type: str) -> int:
        if requirement_type == "fastq":
            return self.fastq_count
        if requirement_type == "fasta":
            return self.fasta_count
        if requirement_type == "sequence":
            return self.sequence_count
        if requirement_type == "annotation":
            return self.annotation_count
        if requirement_type == "hal":
            return self.hal_count
        if requirement_type == "meryl":
            return self.meryl_count
        if requirement_type == "txt":
            return self.txt_count
        return 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fastq_count": self.fastq_count,
            "fasta_count": self.fasta_count,
            "annotation_count": self.annotation_count,
            "hal_count": self.hal_count,
            "meryl_count": self.meryl_count,
            "txt_count": self.txt_count,
            "has_fastq": self.fastq_count > 0,
            "has_paired_fastq": self.has_paired_fastq,
            "has_fasta": self.fasta_count > 0,
            "has_sequence": self.sequence_count > 0,
            "has_annotation": self.annotation_count > 0,
            "has_hal": self.hal_count > 0,
            "has_meryl": self.meryl_count > 0,
            "has_txt": self.txt_count > 0,
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

    if file_format in {"fastq", "fq"}:
        return "fastq"
    if file_format in {"fasta", "fa", "fna"}:
        return "fasta"
    if file_format in {"gff", "gff3", "gtf"}:
        return "annotation"
    if file_format == "hal":
        return "hal"
    if file_format in {"meryl", "meryl.tar", "meryl.tar.gz", "meryl.tgz"}:
        return "meryl"
    if file_format == "txt":
        return "txt"
    if filename.endswith((".fastq", ".fastq.gz", ".fq", ".fq.gz")):
        return "fastq"
    if filename.endswith((".fasta", ".fasta.gz", ".fa", ".fa.gz", ".fna", ".fna.gz")):
        return "fasta"
    if filename.endswith((".gff", ".gff3", ".gtf")):
        return "annotation"
    if filename.endswith(".hal"):
        return "hal"
    if filename.endswith((".meryl", ".meryl.tar", ".meryl.tar.gz", ".meryl.tgz")):
        return "meryl"
    if filename.endswith(".txt"):
        return "txt"
    return ""


def detect_input_capabilities(file_entries: List[Dict[str, Any]]) -> DetectedInputs:
    fastq_count = 0
    fasta_count = 0
    annotation_count = 0
    hal_count = 0
    meryl_count = 0
    txt_count = 0
    for file_entry in file_entries:
        normalized = _normalize_file_format(file_entry)
        if normalized == "fastq":
            fastq_count += 1
        elif normalized == "fasta":
            fasta_count += 1
        elif normalized in {"gff", "gff3", "gtf", "annotation"}:
            annotation_count += 1
        elif normalized == "hal":
            hal_count += 1
        elif normalized == "meryl":
            meryl_count += 1
        elif normalized == "txt":
            txt_count += 1
    return DetectedInputs(
        fastq_count=fastq_count,
        fasta_count=fasta_count,
        annotation_count=annotation_count,
        hal_count=hal_count,
        meryl_count=meryl_count,
        txt_count=txt_count,
    )


def _missing_input_label(requirement_type: str, needed: int) -> str:
    if requirement_type == "fastq":
        return "paired FASTQ reads" if needed >= 2 else "FASTQ reads"
    if requirement_type == "fasta":
        return "FASTA files" if needed >= 2 else "FASTA file"
    if requirement_type == "sequence":
        return "FASTQ or FASTA reads"
    if requirement_type == "annotation":
        return "GFF/GTF annotation"
    if requirement_type == "hal":
        return "HAL alignment"
    if requirement_type == "meryl":
        return "Meryl read k-mer database"
    if requirement_type == "txt":
        return "TXT file with the reference genome name"
    return requirement_type


def _get_intent(intent_id: str) -> Dict[str, Any] | None:
    for intent in INTENT_REGISTRY:
        if intent["id"] == intent_id:
            return intent
    return None


def _collect_missing_inputs(intent: Dict[str, Any], detected: DetectedInputs, selected_tools: Set[str]) -> List[str]:
    missing: List[str] = []
    requires = intent.get("requires", {})
    for requirement_type, needed in requires.items():
        required_count = int(needed)
        if required_count > detected.count_for(requirement_type):
            missing.append(_missing_input_label(requirement_type, required_count))

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
    if "BUSCO" in selected_tool_set and selected_tool_set.intersection({"SPADES", "METASPADES", "HIFIASM", "VERKKO"}):
        assumptions.append("BUSCO assembly input can use the upstream assembly output in the selected workflow.")
    if "MERQURY" in selected_tool_set and selected_tool_set.intersection({"SPADES", "METASPADES", "HIFIASM", "VERKKO"}):
        assumptions.append("Merqury assembly input can use the upstream assembly output; the read k-mer database still needs to be available in Storage.")
    if "LIFTOFF" in selected_tool_set and selected_tool_set.intersection({"SPADES", "METASPADES", "HIFIASM", "VERKKO"}):
        assumptions.append("Liftoff target genome can use the upstream assembly output when connected in the selected workflow.")

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


def _tool_prompt_payload() -> List[Dict[str, str]]:
    tools: List[Dict[str, str]] = []
    for tool in get_tool_registry():
        tools.append({
            "id": str(tool.get("id", "")),
            "name": str(tool.get("name", "")),
            "type": str(tool.get("type", "")),
            "description": str(tool.get("description", "")),
        })
    return tools


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _debug_local_llm_prompts_enabled() -> bool:
    return (os.getenv("CASSIE_DEBUG_LOCAL_LLM_PROMPTS") or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _debug_local_llm_exchange(label: str, question: Dict[str, Any], answer: Any = None) -> None:
    if not _debug_local_llm_prompts_enabled():
        return
    print(f"[CASSIE LOCAL LLM DEBUG] {label} question:")
    print(json.dumps(question, indent=2, ensure_ascii=False))
    if answer is not None:
        print(f"[CASSIE LOCAL LLM DEBUG] {label} answer:")
        print(answer if isinstance(answer, str) else json.dumps(answer, indent=2, ensure_ascii=False))


def _call_local_llm_for_tools(user_request: str, file_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    chat_url = _local_llm_chat_url()
    if not chat_url:
        return {}

    model = (
        os.getenv("CASSIE_LOCAL_LLM_MODEL")
        or os.getenv("LOCAL_LLM_MODEL")
        or "local-model"
    )
    timeout = float(os.getenv("CASSIE_LOCAL_LLM_TIMEOUT_SECONDS") or "25")
    files_summary = [
        {
            "filename": str(file_entry.get("filename") or ""),
            "file_format": str(file_entry.get("file_format") or ""),
        }
        for file_entry in file_entries
    ]
    system_prompt = (
        "You select bioinformatics tools for CASSIE. "
        "Return only compact JSON with tool_ids and explanation. "
        "The explanation must be one short sentence. "
        "Choose only tool ids from the available tools."
    )
    user_prompt = json.dumps({
        "user_request": user_request,
        "available_files": files_summary,
        "available_tools": _tool_prompt_payload(),
        "response_schema": {
            "tool_ids": ["FASTQC"],
            "explanation": "Short reason for the selected tools.",
        },
    })
    prompt_debug_payload = {
        "chat_url": chat_url,
        "model": model,
        "system_prompt": system_prompt,
        "user_prompt": json.loads(user_prompt),
        "temperature": 0.3,
        "max_tokens": 350,
    }
    _debug_local_llm_exchange("tool-recommendation", prompt_debug_payload)

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 350,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(chat_url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {}

    content = ""
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict):
                content = str(message.get("content") or "")
            else:
                content = str(first_choice.get("text") or "")

    _debug_local_llm_exchange("tool-recommendation", prompt_debug_payload, content)
    return _extract_json_object(content)


def _normalize_llm_tool_ids(raw_tool_ids: Any) -> List[str]:
    if not isinstance(raw_tool_ids, list):
        return []

    registry = get_tool_registry()
    tools_by_id = {str(tool.get("id", "")).upper(): tool for tool in registry}
    ids_by_name = {str(tool.get("name", "")).strip().lower(): str(tool.get("id", "")).upper() for tool in registry}
    selected_tool_ids: List[str] = []

    for raw_tool_id in raw_tool_ids:
        candidate = str(raw_tool_id or "").strip()
        if not candidate:
            continue
        normalized = candidate.upper()
        if normalized in tools_by_id:
            tool_id = normalized
        else:
            tool_id = ids_by_name.get(candidate.lower(), "")
        if tool_id and tool_id not in selected_tool_ids:
            selected_tool_ids.append(tool_id)

    return selected_tool_ids


def _intent_ids_from_text(user_request: str, detected: DetectedInputs) -> List[str]:
    text = user_request.lower()
    matched: List[str] = []

    keyword_intents = [
        ("read_quality", ["quality", "qc", "fastqc", "read check"]),
        ("genomic_properties_from_reads", ["genomescope", "genome size", "heterozygosity", "kmer", "k-mer"]),
        ("metagenome_assembly", ["metagenome", "metagenomic", "microbiome", "mixed community"]),
        ("telomere_to_telomere_assembly", ["t2t", "telomere", "verkko"]),
        ("long_read_hifi_assembly", ["hifi", "long read", "long-read", "hifiasm", "pacbio"]),
        ("assembly_from_short_reads", ["assemble", "assembly", "spades", "short read", "short-read"]),
        ("assembly_quality_against_reference", ["quast", "reference quality", "compare assembly"]),
        ("assembly_completeness", ["busco", "completeness", "ortholog"]),
        ("assembly_kmer_quality", ["merqury", "meryl", "consensus quality"]),
        ("annotation_liftover", ["liftoff", "lift annotation", "transfer annotation", "annotation lift"]),
        ("comparative_annotation", ["comparative annotation", "cat", "hal alignment", "hal"]),
    ]

    for intent_id, keywords in keyword_intents:
        if any(keyword in text for keyword in keywords) and intent_id not in matched:
            matched.append(intent_id)

    if not matched:
        if detected.fastq_count > 0:
            matched.append("read_quality")
        elif detected.fasta_count > 0:
            matched.append("assembly_completeness")

    return matched


def _build_llm_option(selected_tool_ids: List[str], explanation: str, source: str) -> Dict[str, Any] | None:
    tool_indices = [get_tool_index_by_id(tool_id) for tool_id in selected_tool_ids]
    tool_indices = [index for index in tool_indices if isinstance(index, int)]
    if not tool_indices:
        return None

    tool_names = [
        get_tool_by_id(tool_id).get("name", tool_id)
        for tool_id in selected_tool_ids
        if get_tool_by_id(tool_id)
    ]
    short_explanation = (explanation or "Selected tools that best match your request.").strip()
    if len(short_explanation) > 180:
        short_explanation = f"{short_explanation[:177].rstrip()}..."

    return {
        "id": f"{source}_request",
        "title": "Suggested From Your Request",
        "summary": short_explanation,
        "intent_ids": [],
        "tool_ids": selected_tool_ids,
        "tool_indices": tool_indices,
        "tool_names": tool_names,
        "missing_inputs": [],
        "assumptions": [],
        "rationale": [short_explanation],
        "tags": [source, "experimental"],
        "score": 95 if source == "local_llm" else 60,
    }


def recommend_pipeline_from_request(user_request: str, file_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    detected = detect_input_capabilities(file_entries)
    llm_payload = _call_local_llm_for_tools(user_request, file_entries)
    selected_tool_ids = _normalize_llm_tool_ids(llm_payload.get("tool_ids"))
    explanation = str(llm_payload.get("explanation") or "").strip()
    option = _build_llm_option(selected_tool_ids, explanation, "local_llm")

    if option:
        return {
            "intents": get_recommendation_intents(),
            "detected_inputs": detected.to_dict(),
            "pipeline_options": [option],
            "source": "local_llm",
        }

    fallback_intents = _intent_ids_from_text(user_request, detected)
    fallback_data = recommend_pipelines(fallback_intents, file_entries)
    fallback_options = fallback_data.get("pipeline_options", [])
    fallback_explanation = "Matched your request to the closest built-in pipeline intentions."
    for fallback_option in fallback_options:
        fallback_option["summary"] = fallback_explanation
        fallback_option["rationale"] = [fallback_explanation]
        fallback_option["tags"] = list(dict.fromkeys([*fallback_option.get("tags", []), "heuristic", "experimental"]))

    fallback_data["source"] = "heuristic"
    return fallback_data
