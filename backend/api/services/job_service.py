"""
Job service for database operations.

This module provides database operations for job management.
"""

import json
from threading import Thread
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from backend.api.database.db_init import get_db_connection
from backend.api.models.job_model import JobInDB, JobCreate, JobUpdate, JobResponse, JobStatus, CloudProvider
from backend.api.services.output_retention_service import purge_expired_finished_job_outputs_for_user
from backend.api.services.user_limit_service import TERMINAL_JOB_STATUSES
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_index, tool_produces_requirement

logger = get_logger(__name__)

JOB_SELECT_COLUMNS = """
    id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id,
    assembler, data_types, cloud_provider, execution_preferences, vm_name,
    created_at, updated_at,
    estimated_price_usd, max_charge_usd, actual_price_charged_usd,
    balance_reserved_at, balance_charged_at
"""


def _row_to_job(row) -> JobInDB:
    data_types = row[8] if row[8] else None
    if isinstance(data_types, str):
        data_types = json.loads(data_types)

    execution_preferences = row[10] if row[10] else None
    if isinstance(execution_preferences, str):
        execution_preferences = json.loads(execution_preferences)

    cloud_provider_value = None
    if row[9]:
        try:
            cloud_provider_value = CloudProvider(row[9])
        except (ValueError, AttributeError):
            logger.warning(f"Invalid cloud_provider value: {row[9]}")
            cloud_provider_value = None

    return JobInDB(
        id=row[0],
        user_id=row[1],
        name=row[2],
        status=JobStatus(row[3]),
        workflow_id=row[4],
        pipeline_config_id=row[5],
        pipeline_id=row[6],
        assembler=row[7] if row[7] else None,
        data_types=data_types,
        cloud_provider=cloud_provider_value,
        execution_preferences=execution_preferences,
        vm_name=row[11],
        created_at=row[12],
        updated_at=row[13],
        estimated_price_usd=float(row[14] or 0),
        max_charge_usd=float(row[15] or 0),
        actual_price_charged_usd=float(row[16]) if row[16] is not None else None,
        balance_reserved_at=row[17],
        balance_charged_at=row[18],
    )


def _get_requirement_source_override(
    execution_preferences: Optional[Dict[str, Any]],
    tool_id: str,
    requirement_type: str,
) -> Optional[str]:
    normalized_tool_id = str(tool_id or "").strip().upper()
    normalized_requirement = str(requirement_type or "").strip().lower()
    if not normalized_tool_id or not normalized_requirement or not isinstance(execution_preferences, dict):
        return None

    for item in execution_preferences.get("input_source_overrides") or []:
        if not isinstance(item, dict):
            continue
        item_tool_id = str(item.get("tool_id") or "").strip().upper()
        item_requirement = str(item.get("requirement_type") or "").strip().lower()
        source = str(item.get("source") or "").strip().lower()
        if item_tool_id == normalized_tool_id and item_requirement == normalized_requirement and source in {"external", "upstream"}:
            return source
    return None


def _build_pipeline_stage_snapshot(
    pipeline_id: int,
    user_id: int,
    execution_preferences: Optional[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    from backend.api.services.pipeline_service import get_pipeline_by_id
    from backend.api.services.pipeline_converter import (
        build_stage_result_label_map,
        extract_edges,
        extract_stage_nodes,
        resolve_node_label,
        resolve_node_tool_id,
        sort_tool_nodes_by_priority,
    )
    from tool_registry import get_tool_by_id

    pipeline = get_pipeline_by_id(pipeline_id, user_id)
    if not pipeline:
        return None

    stage_nodes = extract_stage_nodes(pipeline.nodes)
    if not stage_nodes:
        return None

    edges = extract_edges(pipeline.edges)
    result_labels_by_stage = build_stage_result_label_map(pipeline.nodes, pipeline.edges)
    dependency_map: Dict[str, List[str]] = {node_id: [] for node_id in stage_nodes}
    for edge in edges:
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if source in stage_nodes and target in stage_nodes and source not in dependency_map[target]:
            dependency_map[target].append(source)

    priority_overrides = []
    if isinstance(execution_preferences, dict):
        priority_overrides = execution_preferences.get("pipeline_priority_groups") or []

    ordered_node_ids = sort_tool_nodes_by_priority(
        stage_nodes,
        edges,
        priority_overrides=priority_overrides,
    )

    snapshot: List[Dict[str, Any]] = []
    stage_number = 1
    for node_id in ordered_node_ids:
        node = stage_nodes.get(node_id)
        if not node:
            continue

        node_type = str(node.get("type") or "").strip().lower()
        if node_type == "checkpoint":
            snapshot.append(
                {
                    "stage_id": str(node_id),
                    "stage_number": stage_number,
                    "stage_kind": "checkpoint",
                    "tool_id": "CHECKPOINT",
                    "tool_name": str(node.get("label") or "Checkpoint"),
                    "stage_label": resolve_node_label(node) or str(node.get("label") or "Checkpoint"),
                    "dependency_stage_ids": list(dependency_map.get(node_id, [])),
                    "input_requirements": [],
                    "produces": [],
                    "result_labels": list(result_labels_by_stage.get(str(node_id), [])),
                }
            )
            stage_number += 1
            continue

        tool_id = resolve_node_tool_id(node)
        tool = get_tool_by_id(tool_id) if tool_id else None
        if not tool:
            continue

        snapshot.append(
            {
                "stage_id": str(node_id),
                "stage_number": stage_number,
                "stage_kind": "tool",
                "tool_id": str(tool.get("id") or ""),
                "tool_name": str(tool.get("name") or tool.get("id") or ""),
                "stage_label": resolve_node_label(node) or str(tool.get("name") or tool.get("id") or ""),
                "dependency_stage_ids": list(dependency_map.get(node_id, [])),
                "input_requirements": list(tool.get("input_requirements") or []),
                "produces": list(tool.get("produces") or []),
                "result_labels": list(result_labels_by_stage.get(str(node_id), [])),
            }
        )
        stage_number += 1

    return snapshot or None


def _build_workflow_stage_snapshot(
    workflow_id: int,
    user_id: int,
    execution_preferences: Optional[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    from backend.api.services.workflow_service import get_workflow_by_id
    from tool_registry import get_tool_by_id

    workflow = get_workflow_by_id(workflow_id, user_id=user_id)
    if not workflow:
        return None

    manual_override_positions: Dict[str, int] = {}
    if isinstance(execution_preferences, dict):
        for group in execution_preferences.get("manual_priority_groups") or []:
            if not isinstance(group, dict):
                continue
            ordered_tool_ids = group.get("ordered_tool_ids") or []
            if not isinstance(ordered_tool_ids, list):
                continue
            for index, tool_id in enumerate(ordered_tool_ids):
                normalized_tool_id = str(tool_id).strip().upper()
                if normalized_tool_id and normalized_tool_id not in manual_override_positions:
                    manual_override_positions[normalized_tool_id] = index

    specs: List[Dict[str, Any]] = []
    for stage_number, step in enumerate(workflow.get("workflow_steps", []) or [], start=1):
        tool_id = str(step.get("tool") or "").strip().upper()
        tool = get_tool_by_id(tool_id) if tool_id else None
        if not tool:
            continue
        stage_id = str(step.get("stage_id") or step.get("id") or f"step-{stage_number}")
        dependency_ids = [str(dep).strip() for dep in (step.get("dependency_ids") or []) if str(dep).strip()]
        if not dependency_ids:
            for previous_spec in specs:
                previous_tool_id = str(previous_spec.get("tool_id") or "").strip().upper()
                if not previous_tool_id:
                    continue
                if any(
                    _get_requirement_source_override(
                        execution_preferences,
                        str(tool.get("id") or ""),
                        str(requirement.get("type") or ""),
                    ) != "external"
                    and
                    tool_produces_requirement(previous_tool_id, str(requirement.get("type") or "").strip().lower())
                    for requirement in (tool.get("input_requirements") or [])
                ):
                    previous_stage_id = str(previous_spec.get("stage_id") or "").strip()
                    if previous_stage_id and previous_stage_id not in dependency_ids:
                        dependency_ids.append(previous_stage_id)
        specs.append(
            {
                "stage_id": stage_id,
                "stage_number": stage_number,
                "stage_kind": "tool",
                "tool_id": str(tool.get("id") or ""),
                "tool_name": str(tool.get("name") or tool.get("id") or ""),
                "dependency_stage_ids": dependency_ids,
                "input_requirements": list(tool.get("input_requirements") or []),
                "produces": list(tool.get("produces") or []),
                "priority_order": manual_override_positions.get(tool_id, stage_number - 1),
            }
        )

    specs.sort(key=lambda spec: (int(spec.get("priority_order") or 0), int(spec.get("stage_number") or 0)))
    for stage_number, spec in enumerate(specs, start=1):
        spec["stage_number"] = stage_number
        spec.pop("priority_order", None)

    return specs or None


def _merge_visualization_snapshot(
    execution_preferences: Optional[Dict[str, Any]],
    stage_snapshot: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if not stage_snapshot:
        return execution_preferences

    merged = dict(execution_preferences or {})
    merged["visualization_snapshot"] = {
        "stages": stage_snapshot,
    }
    return merged


def create_job(user_id: int, job_data: JobCreate) -> JobInDB:
    """
    Create a new job in the database.
    
    Args:
        user_id: ID of the user creating the job
        job_data: Job creation data
        
    Returns:
        JobInDB: Created job with database fields
        
    Raises:
        ValueError: If workflow_id doesn't exist or tool_indices are invalid
    """
    # Handle pipeline_id: convert to tool_indices
    logger.info(f"[JOB SERVICE] Creating job with pipeline_id={job_data.pipeline_id}, tool_indices={job_data.tool_indices}")
    tool_indices = job_data.tool_indices

    def selected_tool_ids(indices: Optional[List[int]]) -> set[str]:
        resolved_ids = set()
        for index in indices or []:
            tool = get_tool_by_index(index)
            if tool:
                resolved_ids.add(tool["id"])
        return resolved_ids

    def preferred_tool_indices_from_preferences(indices: Optional[List[int]]) -> Optional[List[int]]:
        if not indices or not isinstance(job_data.execution_preferences, dict):
            return None

        manual_groups = job_data.execution_preferences.get("manual_priority_groups")
        if not isinstance(manual_groups, list):
            return None

        by_tool_id = {}
        for index in indices:
            tool = get_tool_by_index(index)
            if tool:
                by_tool_id[str(tool["id"]).upper()] = index

        preferred: List[int] = []
        seen: set[int] = set()
        for group in manual_groups:
            if not isinstance(group, dict):
                continue
            ordered_tool_ids = group.get("ordered_tool_ids") or []
            if not isinstance(ordered_tool_ids, list):
                continue
            for tool_id in ordered_tool_ids:
                tool_index = by_tool_id.get(str(tool_id).strip().upper())
                if tool_index is None or tool_index in seen:
                    continue
                preferred.append(tool_index)
                seen.add(tool_index)

        return preferred or None

    if job_data.pipeline_id:
        if tool_indices:
            raise ValueError("Cannot specify both pipeline_id and tool_indices. Use one or the other.")
        
        # Load pipeline and convert to tool_indices
        from backend.api.services.pipeline_service import get_pipeline_by_id
        from backend.api.services.pipeline_converter import convert_pipeline_to_tool_indices
        
        pipeline = get_pipeline_by_id(job_data.pipeline_id, user_id)
        if not pipeline:
            raise ValueError(f"Pipeline {job_data.pipeline_id} not found or does not belong to user")
        
        try:
            priority_overrides = []
            if isinstance(job_data.execution_preferences, dict):
                priority_overrides = job_data.execution_preferences.get("pipeline_priority_groups") or []
            tool_indices = convert_pipeline_to_tool_indices(
                pipeline,
                priority_overrides=priority_overrides,
            )
            logger.info(f"Converted pipeline {job_data.pipeline_id} to tool_indices: {tool_indices}")
        except Exception as e:
            raise ValueError(f"Failed to convert pipeline to tool indices: {str(e)}")
    
    # If tool_indices provided (either directly or from pipeline), create workflow dynamically
    workflow_id = job_data.workflow_id
    if tool_indices:
        # Check input files to determine capabilities
        has_reference = False
        has_assembly = False
        has_paired_end = False
        fastq_count = 0
        fasta_count = 0
        
        selected_input_file_ids = list(job_data.input_file_ids or []) + list(getattr(job_data, "staged_input_file_ids", None) or [])
        if selected_input_file_ids:
            from backend.api.services.storage_service import get_file_by_id
            for file_id in selected_input_file_ids:
                try:
                    file_record = get_file_by_id(file_id, user_id=user_id)
                    if file_record:
                        filename_lower = file_record.filename.lower()
                        if filename_lower.endswith(('.fasta', '.fa', '.fna')):
                            fasta_count += 1
                            logger.info(f"Detected FASTA file: {file_record.filename}")
                        elif filename_lower.endswith(('.fastq', '.fq')):
                            fastq_count += 1
                except Exception as e:
                    logger.warning(f"Could not check file {file_id}: {e}")
        
        # If there are 2 FASTA files, one is assembly and one is reference (for QUAST)
        # If there's 1 FASTA file and QUAST is selected, assume it's a reference (assembly comes from SPAdes)
        # If there's 1 FASTA file and QUAST is selected but SPAdes is NOT, we need to detect which it is
        # For now, if 2 FASTA files: both assembly and reference are present
        if fasta_count >= 2:
            has_reference = True
            has_assembly = True
            logger.info(f"Detected {fasta_count} FASTA files: assuming 1 assembly + 1 reference for QUAST")
        elif fasta_count == 1:
            # Check if SPAdes is in tool_indices - if not, the FASTA might be an assembly
            has_spades = False
            if tool_indices:
                has_spades = "SPADES" in selected_tool_ids(tool_indices)
            
            if has_spades:
                # SPAdes will generate assembly, so this FASTA is the reference
                has_reference = True
                logger.info(f"Detected reference genome file (SPAdes will generate assembly)")
            else:
                # No SPAdes, so this FASTA could be an assembly, but we still need a reference
                # For QUAST to work without SPAdes, we need 2 FASTA files (1 assembly + 1 reference)
                # So if only 1 FASTA and no SPAdes, we can't determine if it's assembly or reference
                # We'll assume it's a reference for now, but QUAST will still require SPAdes or another assembly
                has_reference = True
                logger.info(f"Detected 1 FASTA file (no SPAdes selected): assuming reference. QUAST requires 2 FASTA files (assembly + reference) when SPAdes is not selected.")
        
        # SPAdes requires paired-end reads (2 FASTQ files)
        has_paired_end = fastq_count >= 2
        if fastq_count == 1:
            logger.info(f"Detected single-end reads (1 FASTQ file). SPAdes will be filtered out if selected.")
        elif fastq_count >= 2:
            logger.info(f"Detected paired-end reads ({fastq_count} FASTQ files). SPAdes can run.")
        
        # Check if SPAdes is in tool_indices (to determine if FASTA is assembly or reference)
        has_spades = False
        if tool_indices:
            has_spades = "SPADES" in selected_tool_ids(tool_indices)
        
        from backend.api.services.workflow_service import create_workflow_from_tools
        workflow_id = create_workflow_from_tools(
            tool_indices=tool_indices,
            user_id=user_id,
            workflow_name=f"{job_data.name} Workflow",  # Use job name to make workflow name unique per job
            has_reference_file=has_reference,
            has_paired_end_reads=has_paired_end,
            has_assembly_file=has_assembly,
            preferred_tool_order=preferred_tool_indices_from_preferences(tool_indices),
            input_source_overrides=(job_data.execution_preferences or {}).get("input_source_overrides") if isinstance(job_data.execution_preferences, dict) else None,
        )
        logger.info(f"Created workflow {workflow_id} dynamically from tool indices: {tool_indices} (has_reference: {has_reference}, has_assembly: {has_assembly}, has_paired_end: {has_paired_end})")
    elif not workflow_id:
        raise ValueError("Either workflow_id or tool_indices must be provided")

    if job_data.pipeline_id:
        job_data.execution_preferences = _merge_visualization_snapshot(
            job_data.execution_preferences,
            _build_pipeline_stage_snapshot(
                job_data.pipeline_id,
                user_id,
                job_data.execution_preferences,
            ),
        )
    else:
        job_data.execution_preferences = _merge_visualization_snapshot(
            job_data.execution_preferences,
            _build_workflow_stage_snapshot(
                workflow_id,
                user_id,
                job_data.execution_preferences,
            ),
        )
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify workflow exists
            cur.execute("SELECT id FROM workflows WHERE id = %s", (workflow_id,))
            if not cur.fetchone():
                raise ValueError(f"Workflow with id {workflow_id} not found")
            
            # Verify pipeline_config exists if provided
            if job_data.pipeline_config_id:
                cur.execute("SELECT id FROM pipeline_configs WHERE id = %s", (job_data.pipeline_config_id,))
                if not cur.fetchone():
                    raise ValueError(f"Pipeline config with id {job_data.pipeline_config_id} not found")
            
            # Convert JSON-capable fields to JSONB
            data_types_json = json.dumps(job_data.data_types) if job_data.data_types else None
            execution_preferences_json = json.dumps(job_data.execution_preferences) if job_data.execution_preferences else None
            estimated_price_usd = max(float(job_data.estimated_price_usd or 0), 0.0)
            max_charge_usd = round(estimated_price_usd * 1.5, 2)
            
            # Insert job
            logger.info(f"[JOB SERVICE] Inserting job with pipeline_id={job_data.pipeline_id}, workflow_id={workflow_id}")
            cur.execute(f"""
                INSERT INTO jobs (
                    user_id, name, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types,
                    cloud_provider, execution_preferences, vm_name, status, estimated_price_usd, max_charge_usd
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {JOB_SELECT_COLUMNS}
            """, (
                user_id,
                job_data.name,
                workflow_id,  # Use dynamically created or provided workflow_id
                job_data.pipeline_config_id,
                job_data.pipeline_id,  # Preserve pipeline_id even when converting to tool_indices
                job_data.assembler,
                data_types_json,
                job_data.cloud_provider.value if job_data.cloud_provider else None,
                execution_preferences_json,
                job_data.vm_name,
                JobStatus.PENDING.value,
                estimated_price_usd,
                max_charge_usd,
            ))
            
            row = cur.fetchone()
            conn.commit()
            return _row_to_job(row)
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating job: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_job_by_id(job_id: int, user_id: Optional[int] = None) -> Optional[JobInDB]:
    """
    Get a job by ID, optionally filtered by user_id.
    
    Args:
        job_id: Job ID to search for
        user_id: Optional user ID to verify ownership
        
    Returns:
        JobInDB: Job if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if user_id:
                cur.execute(f"""
                    SELECT {JOB_SELECT_COLUMNS}
                    FROM jobs
                    WHERE id = %s AND user_id = %s
                """, (job_id, user_id))
            else:
                cur.execute(f"""
                    SELECT {JOB_SELECT_COLUMNS}
                    FROM jobs
                    WHERE id = %s
                """, (job_id,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return _row_to_job(row)
        finally:
            cur.close()


def get_jobs_by_user(user_id: int, status: Optional[JobStatus] = None, limit: int = 100, offset: int = 0) -> List[JobInDB]:
    """
    Get all jobs for a user, optionally filtered by status.
    
    Args:
        user_id: User ID to filter by
        status: Optional status filter
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip
        
    Returns:
        List[JobInDB]: List of jobs
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if status:
                cur.execute(f"""
                    SELECT {JOB_SELECT_COLUMNS}
                    FROM jobs
                    WHERE user_id = %s AND status = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (user_id, status.value, limit, offset))
            else:
                cur.execute(f"""
                    SELECT {JOB_SELECT_COLUMNS}
                    FROM jobs
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (user_id, limit, offset))
            
            rows = cur.fetchall()
            return [_row_to_job(row) for row in rows]
        finally:
            cur.close()


def update_job(job_id: int, user_id: int, job_update: JobUpdate) -> Optional[JobInDB]:
    """
    Update a job.
    
    Args:
        job_id: Job ID to update
        user_id: User ID to verify ownership
        job_update: Job update data
        
    Returns:
        JobInDB: Updated job if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            existing_job = get_job_by_id(job_id, user_id)
            previous_status = existing_job.status if existing_job else None

            # Build update query dynamically based on provided fields
            updates = []
            values = []
            
            if job_update.name is not None:
                updates.append("name = %s")
                values.append(job_update.name)
            
            if job_update.status is not None:
                updates.append("status = %s")
                values.append(job_update.status.value)
            
            if job_update.assembler is not None:
                updates.append("assembler = %s")
                values.append(job_update.assembler)
            
            if job_update.data_types is not None:
                updates.append("data_types = %s")
                values.append(json.dumps(job_update.data_types))
            
            if job_update.cloud_provider is not None:
                updates.append("cloud_provider = %s")
                values.append(job_update.cloud_provider.value)

            if job_update.execution_preferences is not None:
                updates.append("execution_preferences = %s")
                values.append(json.dumps(job_update.execution_preferences))
            
            if job_update.vm_name is not None:
                updates.append("vm_name = %s")
                values.append(job_update.vm_name)
            
            if not updates:
                # No updates provided, just return the existing job
                return get_job_by_id(job_id, user_id)
            
            # Add updated_at
            updates.append("updated_at = CURRENT_TIMESTAMP")
            
            # Add WHERE clause
            values.extend([job_id, user_id])
            
            query = f"""
                UPDATE jobs
                SET {', '.join(updates)}
                WHERE id = %s AND user_id = %s
                RETURNING {JOB_SELECT_COLUMNS}
            """
            
            cur.execute(query, values)
            row = cur.fetchone()
            
            if not row:
                return None
            
            conn.commit()
            
            updated_job = _row_to_job(row)

            if (
                previous_status != JobStatus.COMPLETED
                and updated_job.status == JobStatus.COMPLETED
            ):
                try:
                    from backend.api.services.user_notification_service import send_job_completed_notification

                    send_job_completed_notification(user_id, job_id=updated_job.id, job_name=updated_job.name)
                except Exception as notification_error:
                    logger.warning(f"Failed to send job completion notification for job {updated_job.id}: {notification_error}", exc_info=True)

            if (
                previous_status != updated_job.status
                and updated_job.status.value in TERMINAL_JOB_STATUSES
            ):
                Thread(
                    target=purge_expired_finished_job_outputs_for_user,
                    args=(user_id,),
                    daemon=True,
                ).start()

            return updated_job
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating job: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def prepare_job_for_retry(job_id: int, user_id: int, job_update: Optional[JobUpdate] = None) -> Optional[JobInDB]:
    """Move a failed/cancelled job back to pending and clear one-run billing fields."""
    job_update = job_update or JobUpdate()

    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            existing_job = get_job_by_id(job_id, user_id)
            if not existing_job:
                return None

            if existing_job.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                raise ValueError(
                    f"Only failed or cancelled jobs can be prepared for retry. Current status: {existing_job.status.value}"
                )

            updates = ["status = %s", "actual_price_charged_usd = NULL", "balance_reserved_at = NULL", "balance_charged_at = NULL"]
            values: List[Any] = [JobStatus.PENDING.value]

            if job_update.name is not None:
                updates.append("name = %s")
                values.append(job_update.name)

            if job_update.assembler is not None:
                updates.append("assembler = %s")
                values.append(job_update.assembler)

            if job_update.data_types is not None:
                updates.append("data_types = %s")
                values.append(json.dumps(job_update.data_types))

            if job_update.cloud_provider is not None:
                updates.append("cloud_provider = %s")
                values.append(job_update.cloud_provider.value)

            if job_update.execution_preferences is not None:
                updates.append("execution_preferences = %s")
                values.append(json.dumps(job_update.execution_preferences))

            if job_update.vm_name is not None:
                updates.append("vm_name = %s")
                values.append(job_update.vm_name)

            updates.append("updated_at = CURRENT_TIMESTAMP")
            values.extend([job_id, user_id])

            cur.execute(
                f"""
                UPDATE jobs
                SET {', '.join(updates)}
                WHERE id = %s AND user_id = %s
                RETURNING {JOB_SELECT_COLUMNS}
                """,
                values,
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_job(row) if row else None
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def delete_job(job_id: int, user_id: int) -> bool:
    """
    Delete a job.
    
    Args:
        job_id: Job ID to delete
        user_id: User ID to verify ownership
        
    Returns:
        bool: True if job was deleted, False if not found or not accessible
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("DELETE FROM jobs WHERE id = %s AND user_id = %s", (job_id, user_id))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting job: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def count_jobs_by_user(user_id: int, status: Optional[JobStatus] = None) -> int:
    """
    Count jobs for a user, optionally filtered by status.
    
    Args:
        user_id: User ID to filter by
        status: Optional status filter
        
    Returns:
        int: Number of jobs
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if status:
                cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id = %s AND status = %s", (user_id, status.value))
            else:
                cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id = %s", (user_id,))
            
            return cur.fetchone()[0]
        finally:
            cur.close()
