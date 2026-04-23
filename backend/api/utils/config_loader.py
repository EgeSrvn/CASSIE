"""
Configuration loader for CASSIE backend.

This module provides centralized configuration management with support for:
- Environment variables (priority)
- .env file (fallback)
- Sensible defaults for development

Usage:
    from backend.api.utils.config_loader import get_config
    
    config = get_config()
    db_host = config.database.host
    minio_endpoint = config.minio.endpoint
"""

import json
import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv


class DatabaseConfig:
    """Database configuration settings."""
    
    def __init__(self):
        self.host = os.getenv("DB_HOST", "127.0.0.1")
        self.port = int(os.getenv("DB_PORT", "5433"))
        self.user = os.getenv("DB_USER", "admin")
        self.password = os.getenv("DB_PASSWORD", "admin")
        self.database = os.getenv("DB_NAME", "cassie_db")
        self.min_connections = int(os.getenv("DB_MIN_CONNECTIONS", "1"))
        self.max_connections = int(os.getenv("DB_MAX_CONNECTIONS", "10"))


class MinIOConfig:
    """MinIO/S3 configuration settings."""
    
    def __init__(self):
        self.endpoint = os.getenv("MINIO_ENDPOINT", "http://127.0.0.1:9000")
        self.public_endpoint = os.getenv("MINIO_PUBLIC_ENDPOINT", self.endpoint)
        self.access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        self.secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
        self.use_ssl = os.getenv("MINIO_USE_SSL", "false").lower() in ("true", "1", "yes")
        self.region = os.getenv("MINIO_REGION", "us-east-1")
        self.bucket_prefix = os.getenv("MINIO_BUCKET_PREFIX", "cassie-")


class APIConfig:
    """API server configuration settings."""
    
    def __init__(self):
        self.host = os.getenv("API_HOST", "0.0.0.0")
        self.port = int(os.getenv("API_PORT", "8000"))
        self.prefix = os.getenv("API_PREFIX", "/api")
        self.debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
        self.enable_local_infra_bootstrap = os.getenv("ENABLE_LOCAL_INFRA_BOOTSTRAP", "true").lower() in ("true", "1", "yes")
        
        # Logging settings
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.log_file = os.getenv("LOG_FILE", None)  # None = no file logging
        
        # CORS settings
        cors_origins = os.getenv("CORS_ORIGINS", "*")
        if cors_origins == "*":
            self.cors_origins = ["*"]
        else:
            self.cors_origins = [origin.strip() for origin in cors_origins.split(",")]


class EmailConfig:
    """SMTP email delivery configuration."""

    def __init__(self):
        self.enabled = os.getenv("EMAIL_ENABLED", "false").lower() in ("true", "1", "yes")
        self.host = os.getenv("EMAIL_HOST", "")
        self.port = int(os.getenv("EMAIL_PORT", "587"))
        self.username = os.getenv("EMAIL_USERNAME", "")
        self.password = os.getenv("EMAIL_PASSWORD", "")
        self.from_address = os.getenv("EMAIL_FROM_ADDRESS", self.username or "no-reply@cassie.local")
        self.from_name = os.getenv("EMAIL_FROM_NAME", "CASSIE")
        self.use_tls = os.getenv("EMAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
        self.use_ssl = os.getenv("EMAIL_USE_SSL", "false").lower() in ("true", "1", "yes")


class AdminPanelConfig:
    """Secret admin panel configuration."""

    def __init__(self):
        self.path = os.getenv("ADMIN_PANEL_PATH", "/_cassie_admin_console_7f3a9b")
        self.username = os.getenv("ADMIN_PANEL_USERNAME", "admin")
        self.default_password = os.getenv("ADMIN_PANEL_PASSWORD", "admin")
        self.session_cookie_name = os.getenv("ADMIN_PANEL_SESSION_COOKIE", "cassie_admin_session")
        self.session_duration_minutes = int(os.getenv("ADMIN_PANEL_SESSION_MINUTES", "720"))


class NextflowConfig:
    """Nextflow pipeline execution configuration."""
    
    def __init__(self):
        self.executable = os.getenv("NEXTFLOW_EXECUTABLE", "nextflow")
        self.work_dir = os.getenv("NEXTFLOW_WORK_DIR", "./work")
        self.output_dir = os.getenv("NEXTFLOW_OUTPUT_DIR", "./output")
        self.cache_dir = os.getenv("NEXTFLOW_CACHE_DIR", os.path.expanduser("~/.nextflow"))
        self.log_dir = os.getenv("NEXTFLOW_LOG_DIR", "./logs")


class DockerConfig:
    """Docker configuration for container management."""
    
    def __init__(self):
        self.socket = os.getenv("DOCKER_SOCKET", "unix://var/run/docker.sock")
        self.network = os.getenv("DOCKER_NETWORK", "bridge")
        self.timeout = int(os.getenv("DOCKER_TIMEOUT", "300"))  # 5 minutes


class ExecutionConfig:
    """Execution backend selection."""

    def __init__(self):
        self.backend = os.getenv("EXECUTION_BACKEND", "auto").strip().lower()


class KubernetesConfig:
    """Configuration for Kubernetes-based pipeline execution."""

    def __init__(self):
        self.namespace = os.getenv("KUBERNETES_NAMESPACE", "default")
        self.image_pull_policy = os.getenv("KUBERNETES_IMAGE_PULL_POLICY", "IfNotPresent")
        # Zero or a negative value means "no execution timeout".
        self.job_timeout_seconds = int(os.getenv("KUBERNETES_JOB_TIMEOUT_SECONDS", "0"))
        self.poll_interval_seconds = int(os.getenv("KUBERNETES_POLL_INTERVAL_SECONDS", "5"))
        self.cluster_check_timeout_seconds = int(os.getenv("KUBERNETES_CLUSTER_CHECK_TIMEOUT_SECONDS", "60"))
        self.minio_endpoint = os.getenv("KUBERNETES_MINIO_ENDPOINT", "")
        self.aws_cli_image = os.getenv("KUBERNETES_AWSCLI_IMAGE", "amazon/aws-cli:2.17.40")


class ToolsConfig:
    """Configuration for dockerized bioinformatics tools."""
    
    def __init__(self):
        # Tool image names/tags
        self.fastqc_image = os.getenv("FASTQC_IMAGE", "fastqc:0.12.1")
        self.spades_image = os.getenv("SPADES_IMAGE", "spades:3.15.5")
        self.genomescope2_image = os.getenv("GENOMESCOPE2_IMAGE", "genomescope2:latest")
        self.busco_default_lineage = os.getenv("BUSCO_DEFAULT_LINEAGE", "eukaryota_odb12")
        self.busco_download_path = os.getenv("BUSCO_DOWNLOAD_PATH", "/opt/busco_downloads")
        
        # Tool resource limits (optional)
        self.default_memory_limit = os.getenv("TOOL_MEMORY_LIMIT", "4g")
        self.default_cpu_limit = int(os.getenv("TOOL_CPU_LIMIT", "2"))


class UserLimitsConfig:
    """Per-user job and output access limits loaded from JSON."""

    def __init__(self, project_root: Path):
        self.path = Path(
            os.getenv(
                "USER_LIMITS_CONFIG_PATH",
                str(project_root / "config" / "user_limits.json"),
            )
        )
        self.default_max_running_jobs = 3
        self.default_downloadable_finished_jobs = 5
        self.default_interactive_output_jobs = 5
        self.raw = self._load_json()

    def _load_json(self) -> dict:
        if not self.path.exists():
            return {
                "default": {
                    "max_running_jobs": self.default_max_running_jobs,
                    "downloadable_finished_jobs": self.default_downloadable_finished_jobs,
                    "interactive_output_jobs": self.default_interactive_output_jobs,
                },
                "users": {},
            }

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

        return {
            "default": {
                "max_running_jobs": self.default_max_running_jobs,
                "downloadable_finished_jobs": self.default_downloadable_finished_jobs,
                "interactive_output_jobs": self.default_interactive_output_jobs,
            },
            "users": {},
        }

    def get_limits_for_username(self, username: Optional[str]) -> dict:
        defaults = self.raw.get("default", {}) if isinstance(self.raw, dict) else {}
        users = self.raw.get("users", {}) if isinstance(self.raw, dict) else {}
        user_overrides = users.get(username, {}) if username and isinstance(users, dict) else {}

        max_running_jobs = int(
            user_overrides.get(
                "max_running_jobs",
                defaults.get("max_running_jobs", self.default_max_running_jobs),
            )
        )
        downloadable_finished_jobs = int(
            user_overrides.get(
                "downloadable_finished_jobs",
                defaults.get("downloadable_finished_jobs", self.default_downloadable_finished_jobs),
            )
        )
        interactive_output_jobs = int(
            user_overrides.get(
                "interactive_output_jobs",
                defaults.get("interactive_output_jobs", self.default_interactive_output_jobs),
            )
        )

        return {
            "max_running_jobs": max_running_jobs,
            "downloadable_finished_jobs": downloadable_finished_jobs,
            "interactive_output_jobs": interactive_output_jobs,
        }


class Config:
    """
    Main configuration class for CASSIE backend.
    
    This class aggregates all configuration sections and provides
    a single point of access for all application settings.
    """
    
    def __init__(self):
        """Initialize configuration from environment variables and .env file."""
        # Load .env file if it exists (in project root or current directory)
        self._load_env_file()
        project_root = Path(__file__).parent.parent.parent.parent
        
        # Initialize configuration sections
        self.database = DatabaseConfig()
        self.minio = MinIOConfig()
        self.api = APIConfig()
        self.email = EmailConfig()
        self.admin_panel = AdminPanelConfig()
        self.nextflow = NextflowConfig()
        self.docker = DockerConfig()
        self.execution = ExecutionConfig()
        self.kubernetes = KubernetesConfig()
        self.tools = ToolsConfig()
        self.user_limits = UserLimitsConfig(project_root)
    
    def _load_env_file(self):
        """
        Load environment variables from .env file.
        
        Looks for .env file in:
        1. Current working directory
        2. Project root (3 levels up from this file)
        """
        # Try current directory first
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path)
            return
        
        # Try project root (backend/api/utils/config_loader.py -> project root)
        project_root = Path(__file__).parent.parent.parent.parent
        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    
    def to_dict(self) -> dict:
        """
        Convert configuration to dictionary (useful for debugging/logging).
        
        Returns:
            dict: Configuration as dictionary (passwords are masked)
        """
        return {
            "database": {
                "host": self.database.host,
                "port": self.database.port,
                "user": self.database.user,
                "password": "***",  # Mask password
                "database": self.database.database,
                "min_connections": self.database.min_connections,
                "max_connections": self.database.max_connections,
            },
            "minio": {
                "endpoint": self.minio.endpoint,
                "public_endpoint": self.minio.public_endpoint,
                "access_key": self.minio.access_key,
                "secret_key": "***",  # Mask secret key
                "use_ssl": self.minio.use_ssl,
                "region": self.minio.region,
                "bucket_prefix": self.minio.bucket_prefix,
            },
            "api": {
                "host": self.api.host,
                "port": self.api.port,
                "prefix": self.api.prefix,
                "debug": self.api.debug,
                "enable_local_infra_bootstrap": self.api.enable_local_infra_bootstrap,
                "log_level": self.api.log_level,
                "log_file": self.api.log_file,
                "cors_origins": self.api.cors_origins,
            },
            "email": {
                "enabled": self.email.enabled,
                "host": self.email.host,
                "port": self.email.port,
                "username": self.email.username,
                "password": "***" if self.email.password else "",
                "from_address": self.email.from_address,
                "from_name": self.email.from_name,
                "use_tls": self.email.use_tls,
                "use_ssl": self.email.use_ssl,
            },
            "admin_panel": {
                "path": self.admin_panel.path,
                "username": self.admin_panel.username,
                "default_password": "***",
                "session_cookie_name": self.admin_panel.session_cookie_name,
                "session_duration_minutes": self.admin_panel.session_duration_minutes,
            },
            "nextflow": {
                "executable": self.nextflow.executable,
                "work_dir": self.nextflow.work_dir,
                "output_dir": self.nextflow.output_dir,
                "cache_dir": self.nextflow.cache_dir,
                "log_dir": self.nextflow.log_dir,
            },
            "docker": {
                "socket": self.docker.socket,
                "network": self.docker.network,
                "timeout": self.docker.timeout,
            },
            "execution": {
                "backend": self.execution.backend,
            },
            "kubernetes": {
                "namespace": self.kubernetes.namespace,
                "image_pull_policy": self.kubernetes.image_pull_policy,
                "job_timeout_seconds": self.kubernetes.job_timeout_seconds,
                "poll_interval_seconds": self.kubernetes.poll_interval_seconds,
                "cluster_check_timeout_seconds": self.kubernetes.cluster_check_timeout_seconds,
                "minio_endpoint": self.kubernetes.minio_endpoint,
                "aws_cli_image": self.kubernetes.aws_cli_image,
            },
            "tools": {
                "fastqc_image": self.tools.fastqc_image,
                "spades_image": self.tools.spades_image,
                "genomescope2_image": self.tools.genomescope2_image,
                "busco_default_lineage": self.tools.busco_default_lineage,
                "busco_download_path": self.tools.busco_download_path,
                "default_memory_limit": self.tools.default_memory_limit,
                "default_cpu_limit": self.tools.default_cpu_limit,
            },
            "user_limits": {
                "path": str(self.user_limits.path),
                "default_limits": self.user_limits.get_limits_for_username(None),
            },
        }


# Singleton instance
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance (singleton pattern).
    
    The configuration is loaded once on first access and reused
    for subsequent calls. This ensures consistent configuration
    throughout the application.
    
    Returns:
        Config: Global configuration instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reset_config():
    """
    Reset the global configuration instance.
    
    Useful for testing when you need to reload configuration
    with different environment variables.
    """
    global _config_instance
    _config_instance = None
