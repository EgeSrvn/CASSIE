"""
Response builder utility for CASSIE backend.

This module provides standardized API response formats for all endpoints.
All responses follow a consistent structure for easy client-side handling.

Usage:
    from backend.api.utils.response_builder import success_response, error_response, paginated_response
    
    # Success response
    return success_response(data={"job_id": 123}, message="Job created")
    
    # Error response
    return error_response("VALIDATION_ERROR", "Invalid input", status_code=400)
    
    # Paginated response
    return paginated_response(data=[...], page=1, per_page=20, total=100)
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum


class ErrorCode(str, Enum):
    """Standard error codes for API responses."""
    
    # Validation errors (400)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FORMAT = "INVALID_FORMAT"
    
    # Authentication/Authorization errors (401, 403)
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    
    # Not found errors (404)
    NOT_FOUND = "NOT_FOUND"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    
    # Conflict errors (409)
    CONFLICT = "CONFLICT"
    RESOURCE_EXISTS = "RESOURCE_EXISTS"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    
    # Server errors (500)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    
    # Service errors (503)
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"


def get_status_code_for_error(error_code: str) -> int:
    """
    Get HTTP status code for an error code.
    
    Args:
        error_code: Error code string
    
    Returns:
        int: HTTP status code
    """
    error_code_upper = error_code.upper()
    
    # 400 Bad Request
    if error_code_upper in ("VALIDATION_ERROR", "INVALID_INPUT", "MISSING_REQUIRED_FIELD", "INVALID_FORMAT"):
        return 400
    
    # 401 Unauthorized
    if error_code_upper in ("UNAUTHORIZED", "INVALID_CREDENTIALS", "TOKEN_EXPIRED"):
        return 401
    
    # 403 Forbidden
    if error_code_upper == "FORBIDDEN":
        return 403
    
    # 404 Not Found
    if error_code_upper in ("NOT_FOUND", "RESOURCE_NOT_FOUND", "JOB_NOT_FOUND", 
                           "WORKFLOW_NOT_FOUND", "FILE_NOT_FOUND", "USER_NOT_FOUND"):
        return 404
    
    # 409 Conflict
    if error_code_upper in ("CONFLICT", "RESOURCE_EXISTS", "DUPLICATE_ENTRY"):
        return 409
    
    # 500 Internal Server Error
    if error_code_upper in ("INTERNAL_ERROR", "DATABASE_ERROR", "EXECUTION_ERROR", "STORAGE_ERROR"):
        return 500
    
    # 503 Service Unavailable
    if error_code_upper in ("SERVICE_UNAVAILABLE", "EXTERNAL_SERVICE_ERROR"):
        return 503
    
    # Default to 500 for unknown error codes
    return 500


def success_response(
    data: Any = None,
    message: Optional[str] = None,
    status_code: int = 200
) -> Dict[str, Any]:
    """
    Create a standardized success response.
    
    Args:
        data: Response data (can be dict, list, or any serializable object)
        message: Optional success message
        status_code: HTTP status code (default: 200)
    
    Returns:
        dict: Standardized success response
    
    Example:
        success_response(data={"job_id": 123}, message="Job created")
        # Returns:
        # {
        #     "success": true,
        #     "data": {"job_id": 123},
        #     "message": "Job created",
        #     "timestamp": "2024-01-01T00:00:00Z"
        # }
    """
    response = {
        "success": True,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if message:
        response["message"] = message
    
    return response


def error_response(
    error_code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    status_code: Optional[int] = None
) -> Dict[str, Any]:
    """
    Create a standardized error response.
    
    Args:
        error_code: Error code (use ErrorCode enum or string)
        message: Human-readable error message
        details: Optional additional error details
        status_code: HTTP status code (auto-determined from error_code if not provided)
    
    Returns:
        dict: Standardized error response
    
    Example:
        error_response("VALIDATION_ERROR", "Invalid job name", details={"field": "name"})
        # Returns:
        # {
        #     "success": false,
        #     "error": {
        #         "code": "VALIDATION_ERROR",
        #         "message": "Invalid job name",
        #         "details": {"field": "name"}
        #     },
        #     "timestamp": "2024-01-01T00:00:00Z"
        # }
    """
    # Auto-determine status code if not provided
    if status_code is None:
        status_code = get_status_code_for_error(error_code)
    
    response = {
        "success": False,
        "error": {
            "code": error_code,
            "message": message
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if details:
        response["error"]["details"] = details
    
    return response


def paginated_response(
    data: List[Any],
    page: int,
    per_page: int,
    total: int,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a standardized paginated response.
    
    Args:
        data: List of items for current page
        page: Current page number (1-indexed)
        per_page: Number of items per page
        total: Total number of items
        message: Optional success message
    
    Returns:
        dict: Standardized paginated response
    
    Example:
        paginated_response(data=[...], page=1, per_page=20, total=100)
        # Returns:
        # {
        #     "success": true,
        #     "data": [...],
        #     "pagination": {
        #         "page": 1,
        #         "per_page": 20,
        #         "total": 100,
        #         "total_pages": 5
        #     },
        #     "timestamp": "2024-01-01T00:00:00Z"
        # }
    """
    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    
    response = {
        "success": True,
        "data": data,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if message:
        response["message"] = message
    
    return response


def validation_error_response(
    message: str,
    field: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convenience function for validation errors.
    
    Args:
        message: Error message
        field: Optional field name that failed validation
        details: Optional additional details
    
    Returns:
        dict: Standardized validation error response
    """
    error_details = details or {}
    if field:
        error_details["field"] = field
    
    return error_response(
        error_code=ErrorCode.VALIDATION_ERROR,
        message=message,
        details=error_details if error_details else None,
        status_code=400
    )


def not_found_response(
    resource_type: str,
    resource_id: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Convenience function for not found errors.
    
    Args:
        resource_type: Type of resource (e.g., "Job", "Workflow", "User")
        resource_id: Optional resource ID
    
    Returns:
        dict: Standardized not found error response
    """
    message = f"{resource_type} not found"
    if resource_id is not None:
        message += f" (id: {resource_id})"
    
    return error_response(
        error_code=ErrorCode.NOT_FOUND,
        message=message,
        details={"resource_type": resource_type, "resource_id": resource_id} if resource_id is not None else {"resource_type": resource_type},
        status_code=404
    )


def unauthorized_response(message: str = "Authentication required") -> Dict[str, Any]:
    """
    Convenience function for unauthorized errors.
    
    Args:
        message: Error message
    
    Returns:
        dict: Standardized unauthorized error response
    """
    return error_response(
        error_code=ErrorCode.UNAUTHORIZED,
        message=message,
        status_code=401
    )


def forbidden_response(message: str = "Access denied") -> Dict[str, Any]:
    """
    Convenience function for forbidden errors.
    
    Args:
        message: Error message
    
    Returns:
        dict: Standardized forbidden error response
    """
    return error_response(
        error_code=ErrorCode.FORBIDDEN,
        message=message,
        status_code=403
    )


def internal_error_response(
    message: str = "An internal error occurred",
    details: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convenience function for internal server errors.
    
    Args:
        message: Error message
        details: Optional error details (be careful not to expose sensitive info)
    
    Returns:
        dict: Standardized internal error response
    """
    return error_response(
        error_code=ErrorCode.INTERNAL_ERROR,
        message=message,
        details=details,
        status_code=500
    )
