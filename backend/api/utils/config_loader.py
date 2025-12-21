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
        
        # Logging settings
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.log_file = os.getenv("LOG_FILE", None)  # None = no file logging
        
        # CORS settings
        cors_origins = os.getenv("CORS_ORIGINS", "*")
        if cors_origins == "*":
            self.cors_origins = ["*"]
        else:
            self.cors_origins = [origin.strip() for origin in cors_origins.split(",")]


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


class ToolsConfig:
    """Configuration for dockerized bioinformatics tools."""
    
    def __init__(self):
        # Tool image names/tags
        self.fastqc_image = os.getenv("FASTQC_IMAGE", "fastqc:0.12.1")
        self.spades_image = os.getenv("SPADES_IMAGE", "spades:3.15.5")
        self.genomescope2_image = os.getenv("GENOMESCOPE2_IMAGE", "genomescope2:latest")
        
        # Tool resource limits (optional)
        self.default_memory_limit = os.getenv("TOOL_MEMORY_LIMIT", "4g")
        self.default_cpu_limit = int(os.getenv("TOOL_CPU_LIMIT", "2"))


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
        
        # Initialize configuration sections
        self.database = DatabaseConfig()
        self.minio = MinIOConfig()
        self.api = APIConfig()
        self.nextflow = NextflowConfig()
        self.docker = DockerConfig()
        self.tools = ToolsConfig()
    
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
                "log_level": self.api.log_level,
                "log_file": self.api.log_file,
                "cors_origins": self.api.cors_origins,
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
            "tools": {
                "fastqc_image": self.tools.fastqc_image,
                "spades_image": self.tools.spades_image,
                "genomescope2_image": self.tools.genomescope2_image,
                "default_memory_limit": self.tools.default_memory_limit,
                "default_cpu_limit": self.tools.default_cpu_limit,
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
