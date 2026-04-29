"""
Input validation utilities for CASSIE backend.

This module provides centralized validation functions for API inputs.
All validators return (is_valid: bool, error_message: str) tuples.

Usage:
    from backend.api.utils.validators import validate_job_name, validate_assembler
    
    is_valid, error = validate_job_name("my-job")
    if not is_valid:
        return error_response("VALIDATION_ERROR", error)
"""

import re
from typing import Tuple, List, Optional


# ============================================================================
# Constants
# ============================================================================

# Allowed assemblers
ALLOWED_ASSEMBLERS = {"hifiasm", "flye", "canu", "spades", "masurca"}

# Allowed data types
ALLOWED_DATA_TYPES = {
    "pacbio", "ont", "illumina", "hifi", "hic", "rna", 
    "strandseq", "bionano", "10x", "nanopore"
}

# Allowed cloud providers
ALLOWED_CLOUD_PROVIDERS = {"aws", "gcp", "azure", "local"}

# Allowed workflow types
ALLOWED_WORKFLOW_TYPES = {"predefined", "custom", "template"}

# Allowed file types
ALLOWED_FILE_TYPES = {"input", "output", "intermediate", "log"}

# Allowed file extensions for genomic data
ALLOWED_FILE_EXTENSIONS = {
    ".fastq", ".fastq.gz", ".fq", ".fq.gz",
    ".fasta", ".fasta.gz", ".fa", ".fa.gz", ".fna", ".fna.gz", ".fas", ".fas.gz",
    ".sam", ".bam", ".cram",
    ".vcf", ".vcf.gz", ".gff", ".gff.gz", ".gff3", ".gff3.gz", ".gtf", ".gtf.gz",
    ".bed", ".bed.gz", ".gfa", ".gfa.gz", ".hal", ".hal.gz", ".txt", ".txt.gz",
    ".cfg", ".cfg.gz", ".conf", ".conf.gz", ".ini", ".ini.gz", ".json", ".json.gz",
    ".meryl", ".tar", ".tar.gz", ".tgz"
}

# Username allowed characters: alphanumeric, underscore, hyphen
USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

# Job/workflow name allowed characters: alphanumeric, spaces, underscore, hyphen, dot
NAME_PATTERN = re.compile(r'^[a-zA-Z0-9\s._-]+$')


# ============================================================================
# Job Validation
# ============================================================================

def validate_job_name(name: Optional[str]) -> Tuple[bool, str]:
    """
    Validate job name.
    
    Args:
        name: Job name to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Rules:
        - Must not be None or empty
        - Length: 1-100 characters
        - Allowed characters: alphanumeric, spaces, underscore, hyphen, dot
    """
    if name is None:
        return False, "Job name is required"
    
    if not isinstance(name, str):
        return False, "Job name must be a string"
    
    name = name.strip()
    
    if len(name) == 0:
        return False, "Job name cannot be empty"
    
    if len(name) > 100:
        return False, f"Job name must be at most 100 characters (got {len(name)})"
    
    if not NAME_PATTERN.match(name):
        return False, "Job name can only contain alphanumeric characters, spaces, underscores, hyphens, and dots"
    
    return True, ""


def validate_assembler(assembler: Optional[str]) -> Tuple[bool, str]:
    """
    Validate assembler name.
    
    Args:
        assembler: Assembler name to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Allowed values: hifiasm, flye, canu, spades, masurca
    """
    if assembler is None:
        return True, ""  # Optional field
    
    if not isinstance(assembler, str):
        return False, "Assembler must be a string"
    
    assembler_lower = assembler.lower().strip()
    
    if assembler_lower not in ALLOWED_ASSEMBLERS:
        allowed = ", ".join(sorted(ALLOWED_ASSEMBLERS))
        return False, f"Invalid assembler '{assembler}'. Allowed values: {allowed}"
    
    return True, ""


def validate_data_types(data_types: Optional[List[str]]) -> Tuple[bool, str]:
    """
    Validate data types list.
    
    Args:
        data_types: List of data types to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Allowed values: pacbio, ont, illumina, hifi, hic, rna, strandseq, bionano, 10x, nanopore
    """
    if data_types is None:
        return True, ""  # Optional field
    
    if not isinstance(data_types, list):
        return False, "Data types must be a list"
    
    # Empty list is valid (same as None)
    if len(data_types) == 0:
        return True, ""
    
    # Check for duplicates
    if len(data_types) != len(set(data_types)):
        return False, "Data types list contains duplicates"
    
    # Validate each data type
    invalid_types = []
    for data_type in data_types:
        if not isinstance(data_type, str):
            invalid_types.append(str(data_type))
            continue
        
        data_type_lower = data_type.lower().strip()
        if data_type_lower not in ALLOWED_DATA_TYPES:
            invalid_types.append(data_type)
    
    if invalid_types:
        allowed = ", ".join(sorted(ALLOWED_DATA_TYPES))
        return False, f"Invalid data types: {', '.join(invalid_types)}. Allowed values: {allowed}"
    
    return True, ""


def validate_cloud_provider(cloud_provider: Optional[str]) -> Tuple[bool, str]:
    """
    Validate cloud provider.
    
    Args:
        cloud_provider: Cloud provider name to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Allowed values: aws, gcp, azure, local
    """
    if cloud_provider is None:
        return True, ""  # Optional field
    
    if not isinstance(cloud_provider, str):
        return False, "Cloud provider must be a string"
    
    provider_lower = cloud_provider.lower().strip()
    
    if provider_lower not in ALLOWED_CLOUD_PROVIDERS:
        allowed = ", ".join(sorted(ALLOWED_CLOUD_PROVIDERS))
        return False, f"Invalid cloud provider '{cloud_provider}'. Allowed values: {allowed}"
    
    return True, ""


# ============================================================================
# File Validation
# ============================================================================

def validate_file_extension(filename: Optional[str]) -> Tuple[bool, str]:
    """
    Validate file extension.
    
    Args:
        filename: Filename to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Allowed extensions: .fastq, .fastq.gz, .fq, .fq.gz, .fasta, .fa, .fa.gz, etc.
    """
    if filename is None:
        return False, "Filename is required"
    
    if not isinstance(filename, str):
        return False, "Filename must be a string"
    
    filename = filename.strip()
    
    if len(filename) == 0:
        return False, "Filename cannot be empty"
    
    # Check if filename has an extension
    if '.' not in filename:
        return False, "Filename must have an extension"
    
    # Get extension (handle .gz compressed files)
    filename_lower = filename.lower()
    if filename_lower.endswith('.gz'):
        # For .fastq.gz, we want to check both .fastq.gz and .fastq
        base_ext = filename_lower.rsplit('.', 2)[-2] + '.' + filename_lower.rsplit('.', 2)[-1]
        single_ext = '.' + filename_lower.rsplit('.', 2)[-2]
        if base_ext in ALLOWED_FILE_EXTENSIONS or single_ext in ALLOWED_FILE_EXTENSIONS:
            return True, ""
    else:
        ext = '.' + filename_lower.rsplit('.', 1)[-1]
        if ext in ALLOWED_FILE_EXTENSIONS:
            return True, ""
    
    allowed = ", ".join(sorted(ALLOWED_FILE_EXTENSIONS))
    return False, f"Invalid file extension. Allowed extensions: {allowed}"


def validate_file_format(file_format: Optional[str]) -> Tuple[bool, str]:
    """
    Validate file format.
    
    Args:
        file_format: File format string (e.g., 'fastq', 'fasta', 'sam', 'bam', etc.)
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if file_format is None:
        return True, ""  # Optional field
    
    # Common genomic file formats (case-insensitive)
    valid_formats = [
        'fastq', 'fastq.gz', 'fq', 'fq.gz',
        'fasta', 'fasta.gz', 'fa', 'fa.gz', 'fna', 'fna.gz', 'fas', 'fas.gz',
        'sam', 'bam', 'cram', 'vcf', 'vcf.gz', 'bcf',
        'gff', 'gff.gz', 'gtf', 'gtf.gz', 'gff3', 'gff3.gz',
        'bed', 'bed.gz', 'wig', 'bigwig', 'bigbed', 'tsv', 'tsv.gz', 'csv', 'csv.gz',
        'txt', 'txt.gz', 'json', 'json.gz', 'xml', 'xml.gz', 'h5', 'hdf5', 'bw', 'bb',
        'hal', 'hal.gz', 'gfa', 'gfa.gz', 'cfg', 'cfg.gz', 'conf', 'conf.gz',
        'ini', 'ini.gz', 'meryl', 'meryl.tar', 'meryl.tar.gz', 'meryl.tgz', 'tar', 'tar.gz', 'tgz'
    ]
    
    file_format_lower = file_format.lower().strip()
    
    if not file_format_lower:
        return False, "File format cannot be empty"
    
    if file_format_lower not in valid_formats:
        return False, f"Invalid file format '{file_format}'. Valid formats: {', '.join(valid_formats)}"
    
    return True, ""


def validate_file_type(file_type: Optional[str]) -> Tuple[bool, str]:
    """
    Validate file type.
    
    Args:
        file_type: File type to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Allowed values: input, output, intermediate, log
    """
    if file_type is None:
        return False, "File type is required"
    
    if not isinstance(file_type, str):
        return False, "File type must be a string"
    
    file_type_lower = file_type.lower().strip()
    
    if file_type_lower not in ALLOWED_FILE_TYPES:
        allowed = ", ".join(sorted(ALLOWED_FILE_TYPES))
        return False, f"Invalid file type '{file_type}'. Allowed values: {allowed}"
    
    return True, ""


def validate_file_size(size_bytes: Optional[int], max_size_mb: int = 10000) -> Tuple[bool, str]:
    """
    Validate file size.
    
    Args:
        size_bytes: File size in bytes
        max_size_mb: Maximum file size in MB (default: 10000 MB = 10 GB)
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if size_bytes is None:
        return True, ""  # Optional field
    
    if not isinstance(size_bytes, int):
        return False, "File size must be an integer"
    
    if size_bytes < 0:
        return False, "File size cannot be negative"
    
    max_size_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_size_bytes:
        size_gb = size_bytes / (1024 * 1024 * 1024)
        max_gb = max_size_mb / 1024
        return False, f"File size ({size_gb:.2f} GB) exceeds maximum allowed size ({max_gb} GB)"
    
    return True, ""


# ============================================================================
# User Validation
# ============================================================================

def validate_username(username: Optional[str]) -> Tuple[bool, str]:
    """
    Validate username.
    
    Args:
        username: Username to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Rules:
        - Must not be None or empty
        - Length: 3-50 characters
        - Allowed characters: alphanumeric, underscore, hyphen
    """
    if username is None:
        return False, "Username is required"
    
    if not isinstance(username, str):
        return False, "Username must be a string"
    
    username = username.strip()
    
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    
    if len(username) > 50:
        return False, f"Username must be at most 50 characters (got {len(username)})"
    
    if not USERNAME_PATTERN.match(username):
        return False, "Username can only contain alphanumeric characters, underscores, and hyphens"
    
    return True, ""


def validate_email(email: Optional[str]) -> Tuple[bool, str]:
    """
    Validate email address format.
    
    Args:
        email: Email address to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Note: This only validates format, not uniqueness (requires DB check)
    """
    if email is None:
        return True, ""  # Optional field
    
    if not isinstance(email, str):
        return False, "Email must be a string"
    
    email = email.strip()
    
    if len(email) == 0:
        return True, ""  # Empty string is treated as None
    
    if len(email) > 100:
        return False, f"Email must be at most 100 characters (got {len(email)})"
    
    # Use regex-based email validation (RFC 5322 simplified)
    email_pattern = re.compile(
        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
    )
    
    if email_pattern.match(email):
        return True, ""
    
    return False, "Invalid email format"


def validate_password(password: Optional[str], min_length: int = 8) -> Tuple[bool, str]:
    """
    Validate password strength.
    
    Args:
        password: Password to validate
        min_length: Minimum password length (default: 8)
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Rules:
        - Must not be None or empty
        - Minimum length: 8 characters (configurable)
        - Should contain at least one letter and one number (recommended, not enforced)
    """
    if password is None:
        return False, "Password is required"
    
    if not isinstance(password, str):
        return False, "Password must be a string"
    
    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters"
    
    # Optional: Check for at least one letter and one number
    # (We'll keep it simple for now, can be enhanced later)
    
    return True, ""


# ============================================================================
# Workflow Validation
# ============================================================================

def validate_workflow_name(name: Optional[str]) -> Tuple[bool, str]:
    """
    Validate workflow name.
    
    Args:
        name: Workflow name to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Rules:
        - Must not be None or empty
        - Length: 1-200 characters
        - Allowed characters: alphanumeric, spaces, underscore, hyphen, dot
    """
    if name is None:
        return False, "Workflow name is required"
    
    if not isinstance(name, str):
        return False, "Workflow name must be a string"
    
    name = name.strip()
    
    if len(name) == 0:
        return False, "Workflow name cannot be empty"
    
    if len(name) > 200:
        return False, f"Workflow name must be at most 200 characters (got {len(name)})"
    
    if not NAME_PATTERN.match(name):
        return False, "Workflow name can only contain alphanumeric characters, spaces, underscores, hyphens, and dots"
    
    return True, ""


def validate_workflow_type(workflow_type: Optional[str]) -> Tuple[bool, str]:
    """
    Validate workflow type.
    
    Args:
        workflow_type: Workflow type to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Allowed values: predefined, custom, template
    """
    if workflow_type is None:
        return False, "Workflow type is required"
    
    if not isinstance(workflow_type, str):
        return False, "Workflow type must be a string"
    
    workflow_type_lower = workflow_type.lower().strip()
    
    if workflow_type_lower not in ALLOWED_WORKFLOW_TYPES:
        allowed = ", ".join(sorted(ALLOWED_WORKFLOW_TYPES))
        return False, f"Invalid workflow type '{workflow_type}'. Allowed values: {allowed}"
    
    return True, ""


# ============================================================================
# Dataset Validation
# ============================================================================

def validate_dataset_name(name: Optional[str]) -> Tuple[bool, str]:
    """
    Validate dataset name.
    
    Args:
        name: Dataset name to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Rules:
        - Must not be None or empty
        - Length: 1-200 characters
        - Allowed characters: alphanumeric, spaces, underscore, hyphen, dot
    """
    if name is None:
        return False, "Dataset name is required"
    
    if not isinstance(name, str):
        return False, "Dataset name must be a string"
    
    name = name.strip()
    
    if len(name) == 0:
        return False, "Dataset name cannot be empty"
    
    if len(name) > 200:
        return False, f"Dataset name must be at most 200 characters (got {len(name)})"
    
    if not NAME_PATTERN.match(name):
        return False, "Dataset name can only contain alphanumeric characters, spaces, underscores, hyphens, and dots"
    
    return True, ""


def validate_data_type(data_type: Optional[str]) -> Tuple[bool, str]:
    """
    Validate single data type.
    
    Args:
        data_type: Data type to validate
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    
    Allowed values: pacbio, ont, illumina, hifi, hic, rna, strandseq, bionano, 10x, nanopore
    """
    if data_type is None:
        return True, ""  # Optional field
    
    if not isinstance(data_type, str):
        return False, "Data type must be a string"
    
    data_type_lower = data_type.lower().strip()
    
    if data_type_lower not in ALLOWED_DATA_TYPES:
        allowed = ", ".join(sorted(ALLOWED_DATA_TYPES))
        return False, f"Invalid data type '{data_type}'. Allowed values: {allowed}"
    
    return True, ""


# ============================================================================
# Combined Validation Functions
# ============================================================================

def validate_job_input(
    name: Optional[str],
    assembler: Optional[str] = None,
    data_types: Optional[List[str]] = None,
    cloud_provider: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Validate all job input fields at once.
    
    Args:
        name: Job name
        assembler: Optional assembler name
        data_types: Optional list of data types
        cloud_provider: Optional cloud provider
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
        Returns first validation error found
    """
    # Validate name (required)
    is_valid, error = validate_job_name(name)
    if not is_valid:
        return False, error
    
    # Validate assembler (optional)
    if assembler is not None:
        is_valid, error = validate_assembler(assembler)
        if not is_valid:
            return False, error
    
    # Validate data types (optional)
    if data_types is not None:
        is_valid, error = validate_data_types(data_types)
        if not is_valid:
            return False, error
    
    # Validate cloud provider (optional)
    if cloud_provider is not None:
        is_valid, error = validate_cloud_provider(cloud_provider)
        if not is_valid:
            return False, error
    
    return True, ""
