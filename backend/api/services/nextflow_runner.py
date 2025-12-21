"""
Nextflow pipeline runner service for CASSIE backend.

This module provides a service for executing Nextflow pipelines in the background,
managing execution state, and tracking pipeline progress.

Usage:
    from backend.api.services.nextflow_runner import NextflowRunner
    
    runner = NextflowRunner()
    execution = runner.run_pipeline(
        job_id=1,
        workflow_path="/path/to/pipeline.nf",
        params={"input": "data.fastq"},
        work_dir="/work/job-1",
        output_dir="/output/job-1"
    )
"""

import os
import subprocess
import shutil
import json
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from backend.api.utils.config_loader import get_config
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


class NextflowRunner:
    """
    Nextflow pipeline execution service.
    
    Manages Nextflow pipeline execution, tracks status, and handles errors.
    Supports background execution and job-specific directories.
    """
    
    def __init__(self):
        """Initialize Nextflow runner with configuration."""
        self._config = get_config()
        self._logger = get_logger(__name__)
        self._executable = self._config.nextflow.executable
        self._work_dir_base = self._config.nextflow.work_dir
        self._output_dir_base = self._config.nextflow.output_dir
        self._log_dir = self._config.nextflow.log_dir
        
        # Ensure base directories exist
        os.makedirs(self._work_dir_base, exist_ok=True)
        os.makedirs(self._output_dir_base, exist_ok=True)
        os.makedirs(self._log_dir, exist_ok=True)
        
        # Verify Nextflow is available
        self._verify_nextflow()
    
    def _verify_nextflow(self):
        """
        Verify that Nextflow executable is available.
        
        Raises:
            FileNotFoundError: If Nextflow executable is not found
        """
        try:
            result = subprocess.run(
                [self._executable, '-version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.decode('utf-8', errors='ignore').strip().split('\n')[0]
                self._logger.info(f"Nextflow found: {version}")
            else:
                raise FileNotFoundError(
                    f"Nextflow executable found but returned error: {result.stderr.decode('utf-8', errors='ignore')}"
                )
        except FileNotFoundError:
            error_msg = (
                f"Nextflow executable not found: '{self._executable}'\n"
                f"Please install Nextflow:\n"
                f"  - Windows: Download from https://nextflow.io/ or use WSL\n"
                f"  - Linux/Mac: curl -s https://get.nextflow.io | bash\n"
                f"  - Or set NEXTFLOW_EXECUTABLE environment variable to the full path"
            )
            self._logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Nextflow version check timed out")
    
    def run_pipeline(
        self,
        job_id: int,
        workflow_path: str,
        params: Optional[Dict[str, Any]] = None,
        work_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        execution_number: int = 1,
        profile: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run a Nextflow pipeline in the background.
        
        Args:
            job_id: Job ID
            workflow_path: Path to Nextflow pipeline file (.nf)
            params: Pipeline parameters dictionary
            work_dir: Custom work directory (default: {work_dir_base}/job-{job_id}/exec-{execution_number})
            output_dir: Custom output directory (default: {output_dir_base}/job-{job_id}/exec-{execution_number})
            execution_number: Execution attempt number (default: 1)
            profile: Nextflow profile to use (optional)
        
        Returns:
            dict: Execution details with nextflow_run_id, work_dir, output_dir, process_id, log_file
        
        Raises:
            FileNotFoundError: If workflow file doesn't exist
            RuntimeError: If pipeline execution fails to start
        """
        if not os.path.isfile(workflow_path):
            raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
        
        # Set up directories
        if work_dir is None:
            work_dir = os.path.join(self._work_dir_base, f"job-{job_id}", f"exec-{execution_number}")
        if output_dir is None:
            output_dir = os.path.join(self._output_dir_base, f"job-{job_id}", f"exec-{execution_number}")
        
        os.makedirs(work_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
        
        # Log file for this execution
        log_file = os.path.join(self._log_dir, f"job-{job_id}-exec-{execution_number}.log")
        
        # Build Nextflow command
        cmd = self._build_command(
            workflow_path=workflow_path,
            params=params or {},
            work_dir=work_dir,
            output_dir=output_dir,
            profile=profile,
            log_file=log_file
        )
        
        self._logger.info(
            f"Starting Nextflow pipeline for job {job_id}, execution {execution_number}. "
            f"Workflow: {workflow_path}, Work dir: {work_dir}, Output dir: {output_dir}"
        )
        
        try:
            # Start process in background
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(workflow_path) or os.getcwd(),
                env=self._get_environment()
            )
            
            # Wait a moment to check if process started successfully
            process.poll()
            if process.returncode is not None and process.returncode != 0:
                # Process failed immediately
                stderr = process.stderr.read().decode('utf-8', errors='ignore')
                error_msg = f"Nextflow pipeline failed to start: {stderr}"
                self._logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Extract Nextflow run ID from log file (may take a moment)
            nextflow_run_id = self._extract_run_id(log_file, timeout=5)
            
            self._logger.info(
                f"Nextflow pipeline started for job {job_id}. "
                f"Process ID: {process.pid}, Run ID: {nextflow_run_id}"
            )
            
            return {
                'nextflow_run_id': nextflow_run_id,
                'work_dir': work_dir,
                'output_dir': output_dir,
                'process_id': process.pid,
                'log_file': log_file,
                'started_at': datetime.now().isoformat()
            }
            
        except subprocess.SubprocessError as e:
            error_msg = f"Failed to start Nextflow pipeline: {e}"
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def _build_command(
        self,
        workflow_path: str,
        params: Dict[str, Any],
        work_dir: str,
        output_dir: str,
        profile: Optional[str],
        log_file: str
    ) -> List[str]:
        """
        Build Nextflow command line arguments.
        
        Args:
            workflow_path: Path to pipeline file
            params: Pipeline parameters
            work_dir: Work directory
            output_dir: Output directory
            profile: Nextflow profile
            log_file: Log file path
        
        Returns:
            list: Command arguments
        """
        cmd = [self._executable, 'run', workflow_path]
        
        # Add profile if specified
        if profile:
            cmd.extend(['-profile', profile])
        
        # Add work directory
        cmd.extend(['-work-dir', work_dir])
        
        # Add parameters
        for key, value in params.items():
            if value is None:
                continue
            
            # Handle different parameter types
            if isinstance(value, bool):
                if value:
                    cmd.extend(['--' + key])
            elif isinstance(value, (list, tuple)):
                # For lists, pass as comma-separated or multiple flags
                cmd.extend(['--' + key, ','.join(str(v) for v in value)])
            else:
                cmd.extend(['--' + key, str(value)])
        
        # Add output directory parameter (common convention)
        if 'outdir' not in params and 'output_dir' not in params:
            cmd.extend(['--outdir', output_dir])
        
        # Add log file
        cmd.extend(['-log', log_file])
        
        # Run in background (detach)
        cmd.append('-bg')
        
        return cmd
    
    def _get_environment(self) -> Dict[str, str]:
        """
        Get environment variables for Nextflow execution.
        
        Returns:
            dict: Environment variables
        """
        env = os.environ.copy()
        
        # Set Nextflow cache directory
        env['NXF_CACHEDIR'] = self._config.nextflow.cache_dir
        
        # Ensure Nextflow cache directory exists
        os.makedirs(self._config.nextflow.cache_dir, exist_ok=True)
        
        return env
    
    def _extract_run_id(self, log_file: str, timeout: int = 5) -> Optional[str]:
        """
        Extract Nextflow run ID from log file.
        
        Args:
            log_file: Path to log file
            timeout: Maximum seconds to wait for run ID
        
        Returns:
            str: Nextflow run ID or None if not found
        """
        import time
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # Look for run ID pattern: "Launching `pipeline` [run-id]"
                        match = re.search(r'Launching.*?\[([a-z0-9-]+)\]', content)
                        if match:
                            return match.group(1)
                except (IOError, OSError):
                    pass
            
            time.sleep(0.5)
        
        # If not found, return a placeholder
        return None
    
    def check_status(self, process_id: int) -> Dict[str, Any]:
        """
        Check the status of a running Nextflow process.
        
        Args:
            process_id: Process ID
        
        Returns:
            dict: Status information (running, completed, failed, pid, returncode)
        """
        try:
            # Check if process is still running
            process = subprocess.Popen(['ps', '-p', str(process_id)], 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE)
            process.wait()
            
            if process.returncode == 0:
                return {
                    'status': 'running',
                    'pid': process_id,
                    'returncode': None
                }
            else:
                # Process not found (may have completed)
                return {
                    'status': 'completed',
                    'pid': process_id,
                    'returncode': None
                }
        except (subprocess.SubprocessError, OSError) as e:
            self._logger.warning(f"Error checking process {process_id}: {e}")
            return {
                'status': 'unknown',
                'pid': process_id,
                'error': str(e)
            }
    
    def get_execution_info(self, log_file: str) -> Dict[str, Any]:
        """
        Extract execution information from Nextflow log file.
        
        Args:
            log_file: Path to Nextflow log file
        
        Returns:
            dict: Execution information (run_id, status, completion, error_message)
        """
        if not os.path.exists(log_file):
            return {
                'run_id': None,
                'status': 'unknown',
                'completed': False,
                'error_message': None
            }
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            info = {
                'run_id': None,
                'status': 'running',
                'completed': False,
                'error_message': None
            }
            
            # Extract run ID
            match = re.search(r'Launching.*?\[([a-z0-9-]+)\]', content)
            if match:
                info['run_id'] = match.group(1)
            
            # Check for completion
            if 'Pipeline completed' in content or 'Execution completed' in content:
                info['status'] = 'completed'
                info['completed'] = True
            elif 'Pipeline failed' in content or 'Execution failed' in content:
                info['status'] = 'failed'
                info['completed'] = True
                # Try to extract error message
                error_match = re.search(r'Error.*?:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
                if error_match:
                    info['error_message'] = error_match.group(1).strip()
            
            return info
            
        except (IOError, OSError) as e:
            self._logger.warning(f"Error reading log file {log_file}: {e}")
            return {
                'run_id': None,
                'status': 'error',
                'completed': False,
                'error_message': str(e)
            }
    
    def stop_pipeline(self, process_id: int) -> bool:
        """
        Stop a running Nextflow pipeline.
        
        Args:
            process_id: Process ID
        
        Returns:
            bool: True if stopped successfully, False otherwise
        """
        try:
            # Try graceful termination first
            os.kill(process_id, 15)  # SIGTERM
            
            # Wait a moment
            import time
            time.sleep(2)
            
            # Check if still running
            process = subprocess.Popen(['ps', '-p', str(process_id)], 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE)
            process.wait()
            
            if process.returncode == 0:
                # Still running, force kill
                os.kill(process_id, 9)  # SIGKILL
                self._logger.warning(f"Force killed Nextflow process {process_id}")
            
            self._logger.info(f"Stopped Nextflow process {process_id}")
            return True
            
        except (OSError, ProcessLookupError) as e:
            self._logger.warning(f"Error stopping process {process_id}: {e}")
            return False
    
    def cleanup_execution(self, work_dir: str, output_dir: Optional[str] = None) -> bool:
        """
        Clean up execution directories (work and output).
        
        Args:
            work_dir: Work directory to clean
            output_dir: Optional output directory to clean
        
        Returns:
            bool: True if cleanup successful
        """
        try:
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir)
                self._logger.info(f"Cleaned up work directory: {work_dir}")
            
            if output_dir and os.path.exists(output_dir):
                # Don't delete output by default, just log
                self._logger.info(f"Output directory preserved: {output_dir}")
            
            return True
            
        except (OSError, shutil.Error) as e:
            self._logger.error(f"Error cleaning up directories: {e}")
            return False
    
    def get_trace_file(self, log_file: str) -> Optional[str]:
        """
        Get the path to the Nextflow trace file for an execution.
        
        Args:
            log_file: Path to log file
        
        Returns:
            str: Path to trace file or None if not found
        """
        # Trace file is typically in the same directory as the log file
        log_dir = os.path.dirname(log_file)
        
        # Look for trace file pattern
        trace_patterns = [
            os.path.join(log_dir, 'trace.txt'),
            os.path.join(log_dir, '*.trace.txt'),
        ]
        
        for pattern in trace_patterns:
            import glob
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
        
        return None


# Singleton instance (optional, for convenience)
_runner_instance: Optional[NextflowRunner] = None


def get_nextflow_runner() -> NextflowRunner:
    """
    Get or create singleton Nextflow runner instance.
    
    Returns:
        NextflowRunner: Singleton runner instance
    """
    global _runner_instance
    if _runner_instance is None:
        _runner_instance = NextflowRunner()
    return _runner_instance


def reset_nextflow_runner():
    """Reset singleton runner instance (for testing)."""
    global _runner_instance
    _runner_instance = None
