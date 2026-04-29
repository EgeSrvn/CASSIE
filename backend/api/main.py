"""
Main FastAPI application for CASSIE backend.

This module initializes the FastAPI application, configures middleware,
registers routes, and sets up startup/shutdown handlers.

Usage:
    uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
"""

import uuid
import time
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    internal_error_response,
    validation_error_response,
    ErrorCode
)
from backend.api.database.db_init import initialize_database, check_database_health, reset_connection_pool
from backend.api.services.kubernetes_manager import get_kubernetes_pipeline_runner, kubernetes_is_available
from backend.api.services.user_service import ensure_admin_user

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting CASSIE backend API...")
    
    try:
        # Initialize database
        logger.info("Initializing database...")
        initialize_database()
        logger.info("Database initialized successfully")
        
        # Check database health
        health_status = check_database_health()
        if not health_status['healthy']:
            logger.warning(f"Database health check failed: {health_status.get('error')}")
        else:
            logger.info("Database health check passed")

        admin_user = ensure_admin_user()
        logger.info("Admin panel user ready", extra={"admin_username": admin_user.username})

        if kubernetes_is_available():
            try:
                recovery_summary = get_kubernetes_pipeline_runner().recover_orphaned_executions()
                recovered = recovery_summary.get("recovered_execution_ids") or []
                if recovered:
                    logger.warning(
                        "Recovered orphaned Kubernetes executions after backend startup",
                        extra={"execution_ids": recovered, "errors": recovery_summary.get("errors") or []},
                    )
                elif recovery_summary.get("errors"):
                    logger.warning(
                        "Kubernetes execution recovery completed with cleanup errors",
                        extra={"errors": recovery_summary.get("errors") or []},
                    )
            except Exception as recovery_error:
                logger.warning(
                    f"Failed to reconcile orphaned Kubernetes executions on startup: {recovery_error}",
                    exc_info=True,
                )
        
        if config.api.enable_local_infra_bootstrap:
            # Ensure MinIO is set up (using emulation system's setup)
            try:
                import sys
                from pathlib import Path
                
                current_file = Path(__file__).resolve()
                project_root = current_file.parent.parent.parent
                project_root_str = str(project_root)
                
                if project_root_str not in sys.path:
                    sys.path.insert(0, project_root_str)
                
                from emulation.bucket_manager import ensure_minio_container
                logger.info("Ensuring MinIO container is set up...")
                ensure_minio_container()
                logger.info("MinIO container ready")
            except ImportError as e:
                logger.warning(
                    f"Could not import emulation.bucket_manager: {e}. "
                    f"MinIO may need to be started manually. "
                    f"This is usually safe to ignore if tkinter is not available."
                )
            except Exception as e:
                logger.warning(
                    f"Could not ensure MinIO container: {e}. "
                    f"MinIO may need to be started manually. "
                    f"This is usually safe to ignore."
                )
            
            # Ensure tool images are built (required for VM provisioning)
            try:
                import sys
                from pathlib import Path
                
                current_file = Path(__file__).resolve()
                project_root = current_file.parent.parent.parent
                project_root_str = str(project_root)
                
                if project_root_str not in sys.path:
                    sys.path.insert(0, project_root_str)
                
                from emulation.docker_commands import ensure_tool_images
                logger.info("Ensuring tool Docker images are built...")
                ensure_tool_images()
                logger.info("Tool images ready")
            except ImportError as e:
                logger.warning(
                    f"Could not import emulation.docker_commands: {e}. "
                    f"Tool images may need to be built manually. "
                    f"This is usually safe to ignore if Docker is not available."
                )
            except Exception as e:
                logger.warning(
                    f"Could not ensure tool images: {e}. "
                    f"Tool images may need to be built manually. "
                    f"Run: cd dockerized_tools && bash buildtools.sh"
                )
            
            # Ensure VMs are set up (using emulation system's setup)
            try:
                import sys
                from pathlib import Path
                
                current_file = Path(__file__).resolve()
                project_root = current_file.parent.parent.parent
                project_root_str = str(project_root)
                
                if project_root_str not in sys.path:
                    sys.path.insert(0, project_root_str)
                
                from emulation.docker_commands import ensure_vms
                logger.info("Ensuring VM containers are set up...")
                ensure_vms()
                logger.info("VM containers ready")
            except ImportError as e:
                logger.warning(
                    f"Could not import emulation.docker_commands: {e}. "
                    f"VMs may need to be started manually. "
                    f"This is usually safe to ignore if Docker is not available."
                )
            except Exception as e:
                logger.warning(
                    f"Could not ensure VM containers: {e}. "
                    f"VMs may need to be started manually. "
                    f"This is usually safe to ignore."
                )
        else:
            logger.info("Skipping local infrastructure bootstrap because ENABLE_LOCAL_INFRA_BOOTSTRAP=false")
        
        logger.info("CASSIE backend API started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start application: {e}", exc_info=True)
        raise
    
    try:
        yield
    except asyncio.CancelledError:
        # Normal cancellation during shutdown - re-raise to allow proper cleanup
        logger.info("Shutdown initiated")
        raise
    finally:
        # Shutdown
        try:
            logger.info("Shutting down CASSIE backend API...")
            
            # Close database connection pool
            reset_connection_pool()
            logger.info("Database connections closed")
            
        except asyncio.CancelledError:
            # Ignore cancellation during cleanup
            pass
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)
        
        logger.info("CASSIE backend API shutdown complete")


# Initialize FastAPI app
config = get_config()
_environment = config.environment.lower() if getattr(config, "environment", None) else "development"
_show_api_docs = _environment not in {"prod", "production"} or config.api.debug

app = FastAPI(
    title="CASSIE API",
    description="Cloud-based Automated Sequence assembly and annotation System for Integrated Execution",
    version="1.0.0",
    docs_url="/docs" if _show_api_docs else None,
    redoc_url="/redoc" if _show_api_docs else None,
    openapi_url="/openapi.json" if _show_api_docs else None,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.api.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Middleware
# ============================================================================

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """
    Add request ID to each request for tracing.
    
    Adds a unique request ID to the request state and response headers.
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    # Process request
    start_time = time.time()
    response = await call_next(request)
    
    # Add request ID to response headers
    response.headers["X-Request-ID"] = request_id
    
    # Log request
    process_time = time.time() - start_time
    logger.info(
        f"{request.method} {request.url.path} - {response.status_code}",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "process_time": process_time
        }
    )
    
    return response


@app.middleware("http")
async def exception_handler_middleware(request: Request, call_next):
    """
    Catch unhandled exceptions and return proper error responses.
    """
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(
            f"Unhandled exception: {e}",
            exc_info=True,
            extra={"request_id": getattr(request.state, "request_id", None)}
        )
        error_data = internal_error_response(
            message="An unexpected error occurred",
            details=str(e) if config.api.debug else None
        )
        return JSONResponse(
            content=error_data,
            status_code=500
        )


# ============================================================================
# Exception Handlers
# ============================================================================

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions."""
    request_id = getattr(request.state, "request_id", None)
    
    error_data = error_response(
        error_code=ErrorCode.INTERNAL_ERROR,
        message=exc.detail or "An error occurred",
        status_code=exc.status_code,
        details={"request_id": request_id} if request_id else None
    )
    return JSONResponse(
        content=error_data,
        status_code=exc.status_code
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors."""
    request_id = getattr(request.state, "request_id", None)
    
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"]
        })
    
    # Log validation errors for debugging
    logger.error(
        f"Request validation error: {errors}",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "errors": errors
        }
    )
    
    error_details = {"errors": errors}
    if request_id:
        error_details["request_id"] = request_id

    first_error = errors[0] if errors else None
    if first_error:
        field_name = first_error["field"].split(".")[-1].replace("_", " ")
        message = f"{field_name.capitalize()}: {first_error['message']}"
    else:
        message = "Validation error"
    
    error_data = validation_error_response(
        message=message,
        details=error_details
    )
    return JSONResponse(
        content=error_data,
        status_code=400
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions."""
    request_id = getattr(request.state, "request_id", None)
    
    logger.error(
        f"Unhandled exception: {exc}",
        exc_info=True,
        extra={"request_id": request_id}
    )
    
    error_data = internal_error_response(
        message="An unexpected error occurred",
        details=str(exc) if config.api.debug else None
    )
    return JSONResponse(
        content=error_data,
        status_code=500
    )


# ============================================================================
# Routes
# ============================================================================

# Import route modules (will be implemented in subsequent tasks)
# For now, we'll create placeholder routers

from fastapi import APIRouter

# Import route modules
from backend.api.routes import auth, jobs, storage, pipelines, folders, data_files, forum
from backend.api.routes.admin_panel import router as admin_panel_router
from backend.api.routes.estimator import router as estimator_router
from backend.api.routes import tools

# Register routers
app.include_router(auth.router, prefix=config.api.prefix)
app.include_router(jobs.router, prefix=config.api.prefix)
app.include_router(storage.router, prefix=config.api.prefix)
app.include_router(pipelines.router, prefix=config.api.prefix)
app.include_router(folders.router, prefix=config.api.prefix)
app.include_router(data_files.router, prefix=config.api.prefix)
app.include_router(estimator_router, prefix=config.api.prefix)
app.include_router(tools.router, prefix=config.api.prefix)
app.include_router(forum.router, prefix=config.api.prefix)
app.include_router(admin_panel_router)


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint.
    
    Returns the health status of the API and its dependencies.
    """
    health_status: Dict[str, Any] = {
        "status": "healthy",
        "service": "CASSIE API",
        "version": "1.0.0"
    }
    
    # Check database health
    db_health = check_database_health()
    health_status["database"] = {
        "status": "healthy" if db_health["healthy"] else "unhealthy",
        "error": db_health.get("error")
    }
    
    # Overall status
    if not db_health["healthy"]:
        health_status["status"] = "degraded"
    
    return success_response(
        data=health_status,
        message="Health check completed"
    )


@app.get("/", tags=["root"])
async def root():
    """Root endpoint with API information."""
    return success_response(
        data={
            "name": "CASSIE API",
            "version": "1.0.0",
            "description": "Cloud-based Automated Sequence assembly and annotation System for Integrated Execution",
            "docs": "/docs",
            "health": "/health"
        },
        message="Welcome to CASSIE API"
    )


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "backend.api.main:app",
        host=config.api.host,
        port=config.api.port,
        reload=config.api.debug,
        log_level=config.api.log_level.lower()
    )
