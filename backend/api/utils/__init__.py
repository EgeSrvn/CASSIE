"""
Backend utilities module.

This module provides common utilities for the CASSIE backend:
- Configuration management
- Logging
- Response formatting
- Input validation
"""

from backend.api.utils.config_loader import get_config, reset_config, Config
from backend.api.utils.logger import get_logger, reset_logging
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    paginated_response,
    validation_error_response,
    not_found_response,
    unauthorized_response,
    forbidden_response,
    internal_error_response,
    ErrorCode,
    get_status_code_for_error
)
from backend.api.utils.validators import (
    validate_job_name,
    validate_assembler,
    validate_data_types,
    validate_cloud_provider,
    validate_file_extension,
    validate_file_type,
    validate_file_size,
    validate_username,
    validate_email,
    validate_password,
    validate_workflow_name,
    validate_workflow_type,
    validate_dataset_name,
    validate_data_type,
    validate_job_input,
)

__all__ = [
    "get_config",
    "reset_config",
    "Config",
    "get_logger",
    "reset_logging",
    "success_response",
    "error_response",
    "paginated_response",
    "validation_error_response",
    "not_found_response",
    "unauthorized_response",
    "forbidden_response",
    "internal_error_response",
    "ErrorCode",
    "get_status_code_for_error",
    "validate_job_name",
    "validate_assembler",
    "validate_data_types",
    "validate_cloud_provider",
    "validate_file_extension",
    "validate_file_type",
    "validate_file_size",
    "validate_username",
    "validate_email",
    "validate_password",
    "validate_workflow_name",
    "validate_workflow_type",
    "validate_dataset_name",
    "validate_data_type",
    "validate_job_input",
]

