# CASSIE Database Design

## Overview

This document describes the complete database schema for the CASSIE (Cloud-based Assembly Streamlined Service Integration Engine) platform. The database is designed to support multi-tenant genome assembly workflows with per-user data isolation, workflow management, job execution tracking, and file storage integration.

## Design Principles

1. **Multi-tenancy**: Per-user buckets and data isolation
2. **Workflow Management**: Store Nextflow pipeline definitions with versioning
3. **Execution Tracking**: Separate table for job execution history (supports retries)
4. **File Management**: Comprehensive file tracking with S3 integration
5. **Flexibility**: JSONB fields for dynamic configurations
6. **Audit Trail**: Timestamps and user tracking throughout

## Database Schema

### 1. Users Table

**Purpose**: Store user accounts and authentication information.

```sql
users
├── id (SERIAL PRIMARY KEY)
├── username (VARCHAR(50) UNIQUE NOT NULL)
├── email (VARCHAR(100) UNIQUE)
├── password_hash (VARCHAR(255) NOT NULL)
├── bucket_name (VARCHAR(100) UNIQUE NOT NULL) -- Per-user S3 bucket
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

**Key Features**:
- Per-user S3 buckets for complete data isolation
- Unique username and email constraints
- Automatic timestamp management

**Indexes**:
- `idx_users_username` on `username`
- `idx_users_email` on `email`
- `idx_users_bucket_name` on `bucket_name`

---

### 2. Workflows Table

**Purpose**: Store Nextflow pipeline definitions (workflows) that orchestrate bioinformatics tools.

```sql
workflows
├── id (SERIAL PRIMARY KEY)
├── name (VARCHAR(200) NOT NULL)
├── description (TEXT)
├── workflow_type (VARCHAR(20) NOT NULL) -- 'predefined', 'custom', 'template'
├── user_id (INTEGER REFERENCES users(id) ON DELETE SET NULL) -- NULL for system workflows
├── workflow_content (TEXT NOT NULL) -- Complete Nextflow .nf file content
├── original_filename (VARCHAR(255)) -- Original .nf filename when uploaded by user
├── tools_used (JSONB) -- Array: ["fastqc", "hifiasm", "quast"]
├── workflow_steps (JSONB) -- Ordered steps with metadata
├── parameters_schema (JSONB) -- Parameter definitions and validation rules
├── validation_status (VARCHAR(20) DEFAULT 'pending') -- 'pending', 'valid', 'invalid', 'error'
├── validation_error (TEXT) -- Error message if validation fails
├── is_public (BOOLEAN DEFAULT false) -- Whether workflow can be shared/used by others
├── version (INTEGER DEFAULT 1)
├── is_active (BOOLEAN DEFAULT true)
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
├── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── created_by_user_id (INTEGER REFERENCES users(id) ON DELETE SET NULL)
```

**Key Features**:
- Stores complete Nextflow pipeline code as TEXT
- Supports system workflows (user_id = NULL) and user-created workflows
- User-uploaded workflows: users can upload their own .nf files
- Stores original filename for user reference
- Validation status tracking for uploaded workflows
- Public/private sharing capability
- JSONB fields for flexible metadata
- Version tracking for workflow evolution
- Soft delete via `is_active` flag

**Workflow Types**:
- **predefined**: System-provided workflows (FastQC, Hifiasm, etc.)
- **custom**: User-created workflows
- **template**: Base templates users can clone and customize

**JSONB Structure Examples**:

`tools_used`:
```json
["fastqc", "hifiasm", "quast"]
```

`workflow_steps`:
```json
[
  {"step": 1, "tool": "fastqc", "description": "Quality control"},
  {"step": 2, "tool": "hifiasm", "description": "Genome assembly"},
  {"step": 3, "tool": "quast", "description": "Quality assessment"}
]
```

`parameters_schema`:
```json
{
  "assembler": {"type": "string", "required": true, "default": "hifiasm"},
  "kmer_size": {"type": "integer", "required": false, "default": 21},
  "threads": {"type": "integer", "required": false, "default": 8}
}
```

**Indexes**:
- `idx_workflows_user_id` on `user_id`
- `idx_workflows_workflow_type` on `workflow_type`
- `idx_workflows_is_active` on `is_active`
- `idx_workflows_validation_status` on `validation_status`
- `idx_workflows_is_public` on `is_public`
- `idx_workflows_workflow_type_active` on `(workflow_type, is_active)`
- `idx_workflows_user_name` on `(user_id, name)` -- For unique name constraint per user

---

### 3. Pipeline Configs Table

**Purpose**: Store reusable pipeline configurations that users can save and reuse.

```sql
pipeline_configs
├── id (SERIAL PRIMARY KEY)
├── name (VARCHAR(200) NOT NULL)
├── description (TEXT)
├── user_id (INTEGER REFERENCES users(id) ON DELETE CASCADE)
├── workflow_id (INTEGER REFERENCES workflows(id) ON DELETE RESTRICT)
├── config_data (JSONB NOT NULL) -- Parameter values
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

**Key Features**:
- Links to a specific workflow
- Stores parameter values as JSONB
- User-specific configurations
- Reusable across multiple jobs

**Example `config_data`**:
```json
{
  "assembler": "hifiasm",
  "kmer_size": 21,
  "threads": 16,
  "data_types": ["pacbio", "hic"],
  "min_contig_length": 1000
}
```

**Indexes**:
- `idx_pipeline_configs_user_id` on `user_id`
- `idx_pipeline_configs_workflow_id` on `workflow_id`

---

### 4. Jobs Table

**Purpose**: Store assembly job records that users create.

```sql
jobs
├── id (SERIAL PRIMARY KEY)
├── user_id (INTEGER REFERENCES users(id) ON DELETE CASCADE)
├── name (VARCHAR(100) NOT NULL)
├── status (VARCHAR(20) DEFAULT 'pending') -- 'pending', 'running', 'completed', 'failed', 'cancelled'
├── workflow_id (INTEGER REFERENCES workflows(id) ON DELETE RESTRICT)
├── pipeline_config_id (INTEGER REFERENCES pipeline_configs(id) ON DELETE SET NULL) -- Optional
├── assembler (VARCHAR(50)) -- Denormalized for quick access
├── data_types (JSONB) -- Array: ["pacbio", "ont"] or ["illumina"] - supports combinations
├── cloud_provider (VARCHAR(20)) -- 'aws', 'gcp', 'azure', 'local' - for multi-cloud support
├── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
└── updated_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

**Key Features**:
- Links to workflow and optional pipeline config
- Denormalized `assembler` for quick filtering
- `data_types` as JSONB array to support combinations (e.g., ["pacbio", "hic"], ["illumina", "rna"])
- `cloud_provider` field for multi-cloud support
- Status tracking for job lifecycle
- Execution details stored in separate `job_executions` table

**Example `data_types`**:
```json
["pacbio", "hic"]  // PacBio with HiC data
["illumina", "rna"]  // Illumina with RNAseq
["ont"]  // Single ONT data
["pacbio", "strandseq", "bionano"]  // Multiple data types
```

**Status Values**:
- `pending`: Job created but not started
- `running`: Job currently executing
- `completed`: Job finished successfully
- `failed`: Job encountered an error
- `cancelled`: Job was cancelled by user

**Indexes**:
- `idx_jobs_user_id` on `user_id`
- `idx_jobs_status` on `status`
- `idx_jobs_workflow_id` on `workflow_id`
- `idx_jobs_created_at` on `created_at`
- `idx_jobs_user_status` on `(user_id, status)`

---

### 5. Job Executions Table

**Purpose**: Track individual execution attempts for jobs (supports retries and execution history).

```sql
job_executions
├── id (SERIAL PRIMARY KEY)
├── job_id (INTEGER REFERENCES jobs(id) ON DELETE CASCADE)
├── execution_number (INTEGER NOT NULL) -- 1, 2, 3... for retries
├── status (VARCHAR(20) DEFAULT 'running') -- 'running', 'completed', 'failed', 'cancelled'
├── nextflow_run_id (VARCHAR(100)) -- Nextflow execution ID
├── work_dir (VARCHAR(500)) -- Nextflow work directory path
├── output_dir (VARCHAR(500)) -- Nextflow output directory path
├── process_id (INTEGER) -- System process ID
├── tool_versions (JSONB) -- Tool versions used: {"fastqc": "0.12.1", "hifiasm": "0.19.8", ...}
├── parameters_used (JSONB) -- Actual parameters used in execution (for reproducibility)
├── error_message (TEXT) -- Error details if failed (NO sensitive biological data)
├── started_at (TIMESTAMP)
├── completed_at (TIMESTAMP)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

**Key Features**:
- Supports multiple execution attempts per job (retries)
- Tracks Nextflow-specific execution details
- **Reproducibility**: Stores tool versions and parameters used (spec requirement)
- Stores error messages for debugging (technical only, no sensitive biological data per spec)
- Execution timing for performance analysis

**Example `tool_versions`**:
```json
{
  "fastqc": "0.12.1",
  "hifiasm": "0.19.8",
  "quast": "5.2.0",
  "nextflow": "23.10.0"
}
```

**Example `parameters_used`**:
```json
{
  "assembler": "hifiasm",
  "kmer_size": 21,
  "threads": 16,
  "min_contig_length": 1000,
  "data_types": ["pacbio"]
}
```

**Unique Constraint**:
- `(job_id, execution_number)` must be unique

**Indexes**:
- `idx_job_executions_job_id` on `job_id`
- `idx_job_executions_status` on `status`
- `idx_job_executions_nextflow_run_id` on `nextflow_run_id`
- `idx_job_executions_job_execution_number` on `(job_id, execution_number)`

---

### 6. Files Table

**Purpose**: Track all files associated with jobs (inputs, outputs, intermediates, logs).

```sql
files
├── id (SERIAL PRIMARY KEY)
├── job_id (INTEGER REFERENCES jobs(id) ON DELETE CASCADE)
├── filename (VARCHAR(255) NOT NULL)
├── s3_key (VARCHAR(500) NOT NULL) -- Full S3 path in user's bucket
├── file_type (VARCHAR(20) NOT NULL) -- 'input', 'output', 'intermediate', 'log'
├── file_format (VARCHAR(50)) -- 'fastq', 'fasta', 'vcf', 'bam', 'html', etc.
├── size_bytes (BIGINT)
├── checksum (VARCHAR(64)) -- MD5 or SHA256 for integrity
├── uploaded_at (TIMESTAMP)
└── created_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
```

**Key Features**:
- Tracks all file types (input, output, intermediate, logs)
- Stores S3 keys for file retrieval
- File format and size tracking
- Checksum for integrity verification

**File Types**:
- `input`: User-uploaded input files
- `output`: Final results from pipeline
- `intermediate`: Temporary files during execution
- `log`: Execution logs and reports

**Indexes**:
- `idx_files_job_id` on `job_id`
- `idx_files_file_type` on `file_type`
- `idx_files_s3_key` on `s3_key`
- `idx_files_job_type` on `(job_id, file_type)`

---

## Relationships

```
users (1) ──→ (many) jobs
users (1) ──→ (many) workflows (custom/template)
users (1) ──→ (many) pipeline_configs

workflows (1) ──→ (many) pipeline_configs
workflows (1) ──→ (many) jobs

jobs (1) ──→ (many) job_executions
jobs (1) ──→ (many) files

pipeline_configs (1) ──→ (many) jobs (optional)
```

## Constraints

### Check Constraints

```sql
-- Job status validation
ALTER TABLE jobs ADD CONSTRAINT chk_job_status 
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));

-- Execution status validation
ALTER TABLE job_executions ADD CONSTRAINT chk_execution_status 
    CHECK (status IN ('running', 'completed', 'failed', 'cancelled'));

-- File type validation
ALTER TABLE files ADD CONSTRAINT chk_file_type 
    CHECK (file_type IN ('input', 'output', 'intermediate', 'log'));

-- Workflow type validation
ALTER TABLE workflows ADD CONSTRAINT chk_workflow_type 
    CHECK (workflow_type IN ('predefined', 'custom', 'template'));

ALTER TABLE workflows ADD CONSTRAINT chk_validation_status 
    CHECK (validation_status IN ('pending', 'valid', 'invalid', 'error'));

ALTER TABLE jobs ADD CONSTRAINT chk_cloud_provider 
    CHECK (cloud_provider IN ('aws', 'gcp', 'azure', 'local') OR cloud_provider IS NULL);
```

### Unique Constraints

```sql
-- One execution number per job
ALTER TABLE job_executions ADD CONSTRAINT uq_job_execution_number 
    UNIQUE (job_id, execution_number);

-- Unique workflow name per user (for custom workflows)
-- System workflows (user_id = NULL) can have duplicate names
CREATE UNIQUE INDEX idx_workflows_user_name_unique 
    ON workflows(user_id, name) 
    WHERE user_id IS NOT NULL;
```

## Triggers

### Automatic Timestamp Updates

All tables with `updated_at` fields automatically update on row modification:

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Applied to: users, workflows, pipeline_configs, jobs
```

## Design Decisions

### 1. Per-User Buckets
- **Decision**: Each user has their own S3 bucket
- **Rationale**: Better data isolation, easier access control, cleaner organization
- **Implementation**: `users.bucket_name` field stores unique bucket name

### 2. Workflow Storage
- **Decision**: Store Nextflow content as TEXT in database
- **Rationale**: All data in one place, easier versioning, simpler deployment
- **User Uploads**: Users can upload .nf files which are stored in `workflow_content`
- **Original Filename**: Stored for user reference
- **Alternative Considered**: File system storage (rejected for complexity)

### 3. Separate Job Executions Table
- **Decision**: Track executions separately from jobs
- **Rationale**: Supports retries, better audit trail, cleaner job status
- **Benefit**: Can track multiple execution attempts per job

### 4. Separate Files Table
- **Decision**: Normalized file storage
- **Rationale**: Better queries, easier file management, supports metadata
- **Alternative Considered**: JSONB arrays in jobs table (rejected for query complexity)

### 5. Denormalized Fields
- **Decision**: Store `assembler` in jobs table, `data_types` as JSONB array
- **Rationale**: Faster filtering and queries without joins
- **Data Types**: Changed to JSONB array to support combinations (PacBio+HiC, Illumina+RNAseq, etc.)
- **Trade-off**: Slight data duplication for performance

### 6. JSONB Usage
- **Decision**: Use JSONB for flexible configurations
- **Rationale**: Supports dynamic parameters, easy to extend
- **Fields**: `tools_used`, `workflow_steps`, `parameters_schema`, `config_data`, `data_types`, `tool_versions`, `parameters_used`

### 7. Reproducibility Support
- **Decision**: Store tool versions and parameters in `job_executions` table
- **Rationale**: Spec requires "versions of tools, parameters, and workflow steps are logged"
- **Implementation**: `tool_versions` and `parameters_used` JSONB fields in job_executions
- **Benefit**: Full reproducibility - can recreate exact execution environment

### 8. Multi-Cloud Support
- **Decision**: Add `cloud_provider` field to jobs table
- **Rationale**: Spec mentions "Multi-cloud support would be very good to have"
- **Implementation**: Track which cloud provider (AWS/GCP/Azure/local) was used per job

## Migration Strategy

1. Create all tables in order (respecting foreign key dependencies)
2. Create indexes after table creation
3. Add constraints and triggers
4. Seed system workflows (predefined workflows)
5. Create initial admin user if needed

## Compliance with Project Specification

### ✅ Reproducibility Requirements (Spec Section 1.4)
- **Requirement**: "versions of the tools used in CASSIE, parameters, and workflow steps are logged"
- **Implementation**:
  - ✅ Tool versions: `job_executions.tool_versions` (JSONB)
  - ✅ Parameters: `job_executions.parameters_used` (JSONB)
  - ✅ Workflow steps: `workflows.workflow_steps` (JSONB)
  - ✅ Workflow content: `workflows.workflow_content` (TEXT)

### ✅ Data Privacy Requirements (Spec Section 1.3.3, 1.4)
- **Requirement**: "Log systems should not contain any sensitive biological data"
- **Implementation**:
  - ✅ `job_executions.error_message` - Technical errors only
  - ✅ `files.file_type = 'log'` - Separate log file tracking
  - ⚠️ **Note**: Application code must ensure logs don't contain genomic sequences

### ✅ Multi-Tenant Isolation (Spec Section 1.3.3)
- **Requirement**: "completely isolate user data from each other"
- **Implementation**:
  - ✅ Per-user buckets (`users.bucket_name`)
  - ✅ All tables have `user_id` foreign keys
  - ✅ Files stored in user-specific S3 buckets

### ✅ Multi-Cloud Support (Spec Section 1.1, README)
- **Requirement**: "Multi-cloud support would be very good to have"
- **Implementation**:
  - ✅ `jobs.cloud_provider` field
  - ✅ `credential_manager.py` service planned

### ✅ Data Type Combinations (Spec Section 1.1, README)
- **Requirement**: "Illumina/Pacbio/ONT combinations, additional HiC, StrandSeq, BioNano combinations, RNAseq"
- **Implementation**:
  - ✅ `jobs.data_types` as JSONB array (supports combinations)

## Future Considerations

1. **Workflow Versioning**: May need `workflow_versions` table for full version history
2. **Cost Tracking**: Could add cost estimation and actual cost fields
3. **Notifications**: May need table for job completion notifications
4. **Workflow Sharing**: Already supported via `is_public` flag, could add workflow marketplace
5. **Execution Logs**: Could add detailed execution log storage
6. **File Versioning**: May need file version tracking for outputs
7. **Workflow Validation**: Could add automated Nextflow syntax validation on upload
8. **Workflow Categories/Tags**: Could add categorization for better organization

## Notes

- All timestamps use PostgreSQL's `TIMESTAMP` type (timezone-aware)
- Foreign keys use appropriate `ON DELETE` actions (CASCADE, RESTRICT, SET NULL)
- Indexes are optimized for common query patterns
- JSONB fields allow flexible schema evolution without migrations

