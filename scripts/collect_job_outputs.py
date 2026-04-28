#!/usr/bin/env python3
"""
Manual script to collect output files from a completed job.

Usage:
    python scripts/collect_job_outputs.py <job_id> <user_id>
    
Example:
    python scripts/collect_job_outputs.py 1 1
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.api.services.emulator_pipeline_runner import get_emulator_pipeline_runner
from emulation.tenant_commands import get_tenant_container
from backend.api.services.job_execution_service import get_executions_by_job
from backend.api.models.job_model import ExecutionStatus

def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/collect_job_outputs.py <job_id> <user_id>")
        sys.exit(1)
    
    job_id = int(sys.argv[1])
    user_id = int(sys.argv[2])
    
    print(f"Collecting output files for job {job_id}, user {user_id}...")
    
    # Get the execution for this job
    executions = get_executions_by_job(job_id)
    if not executions:
        print(f"Error: No executions found for job {job_id}")
        sys.exit(1)
    
    # Get the most recent completed execution
    completed_executions = [e for e in executions if e.status == ExecutionStatus.COMPLETED]
    if not completed_executions:
        print(f"Error: No completed executions found for job {job_id}")
        print(f"Available executions: {[e.status for e in executions]}")
        sys.exit(1)
    
    execution = completed_executions[-1]  # Most recent
    execution_id = execution.id
    print(f"Using execution {execution_id} (status: {execution.status})")
    
    # Get tenant container
    tenant_name = f"user_{user_id}"
    try:
        tenant_container = get_tenant_container(tenant_name, user_id=user_id)
        print(f"Found tenant container: {tenant_container.name}")
    except Exception as e:
        print(f"Error getting tenant container: {e}")
        sys.exit(1)
    
    # Find the pipeline run directory
    # Look for the most recent pipeline_run_* directory
    find_result = tenant_container.exec_run(
        ['find', f'/home/{tenant_container.name}', '-maxdepth', '1', '-type', 'd', '-name', 'pipeline_run_*'],
        user='root'
    )
    
    if find_result.exit_code != 0:
        print(f"Error finding pipeline run directories: {find_result.output.decode()}")
        sys.exit(1)
    
    pipeline_dirs = [line.strip() for line in find_result.output.decode().split('\n') if line.strip()]
    if not pipeline_dirs:
        print("Error: No pipeline run directories found")
        sys.exit(1)
    
    # Get the most recent one (highest timestamp)
    pipeline_dirs.sort(reverse=True)
    latest_pipeline_dir = pipeline_dirs[0]
    results_path = os.path.join(latest_pipeline_dir, 'results')
    
    print(f"Found pipeline directory: {latest_pipeline_dir}")
    print(f"Results path: {results_path}")
    
    # Extract pipeline_run_id from path
    import re
    pipeline_match = re.search(r'pipeline_run_(\d+)', latest_pipeline_dir)
    pipeline_run_id = pipeline_match.group(1) if pipeline_match else None
    
    print(f"Pipeline run ID: {pipeline_run_id}")
    
    # Verify results directory exists
    check_result = tenant_container.exec_run(['test', '-d', results_path], user='root')
    if check_result.exit_code != 0:
        print(f"Error: Results directory does not exist: {results_path}")
        sys.exit(1)
    
    # Get the pipeline runner and collect files
    runner = get_emulator_pipeline_runner()
    print("\n" + "="*60)
    print("COLLECTING OUTPUT FILES")
    print("="*60)
    
    try:
        runner._collect_and_upload_outputs(
            tenant_container=tenant_container,
            results_path=results_path,
            job_id=job_id,
            user_id=user_id,
            execution_id=execution_id,
            pipeline_run_id=pipeline_run_id,
            input_filename_base=None  # Don't filter by input filename for outputs
        )
        print("\n" + "="*60)
        print("COLLECTION COMPLETE")
        print("="*60)
        print(f"Output files should now be available for job {job_id}")
        print(f"Use: GET /api/storage/files?job_id={job_id}&file_type=OUTPUT")
    except Exception as e:
        print(f"\nError collecting files: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()


