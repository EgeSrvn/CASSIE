-- CASSIE Database Schema
-- Created incrementally for Task 1.1
-- Revised to be idempotent (safe to run multiple times)

-- ============================================================================
-- Table 1: Users
-- ============================================================================
-- Purpose: Store user accounts and authentication information
-- Features: Per-user S3 buckets for complete data isolation

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    bucket_name VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_bucket_name ON users(bucket_name);

-- ============================================================================
-- Table 2: Workflows
-- ============================================================================
-- Purpose: Store Nextflow pipeline definitions (workflows) that orchestrate bioinformatics tools
-- Features: Supports system workflows, user-uploaded workflows, versioning, and sharing

CREATE TABLE IF NOT EXISTS workflows (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    workflow_type VARCHAR(20) NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    workflow_content TEXT NOT NULL,
    original_filename VARCHAR(255),
    tools_used JSONB,
    workflow_steps JSONB,
    parameters_schema JSONB,
    validation_status VARCHAR(20) DEFAULT 'pending',
    validation_error TEXT,
    is_public BOOLEAN DEFAULT false,
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);

-- Check constraints for workflows (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_workflow_type'
          AND conrelid = 'workflows'::regclass
    ) THEN
        ALTER TABLE workflows
        ADD CONSTRAINT chk_workflow_type
        CHECK (workflow_type IN ('predefined', 'custom', 'template'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_validation_status'
          AND conrelid = 'workflows'::regclass
    ) THEN
        ALTER TABLE workflows
        ADD CONSTRAINT chk_validation_status
        CHECK (validation_status IN ('pending', 'valid', 'invalid', 'error'));
    END IF;
END $$;

-- Indexes for workflows table
CREATE INDEX IF NOT EXISTS idx_workflows_user_id ON workflows(user_id);
CREATE INDEX IF NOT EXISTS idx_workflows_workflow_type ON workflows(workflow_type);
CREATE INDEX IF NOT EXISTS idx_workflows_is_active ON workflows(is_active);
CREATE INDEX IF NOT EXISTS idx_workflows_validation_status ON workflows(validation_status);
CREATE INDEX IF NOT EXISTS idx_workflows_is_public ON workflows(is_public);
CREATE INDEX IF NOT EXISTS idx_workflows_workflow_type_active ON workflows(workflow_type, is_active);

-- Unique constraint: workflow name per user (for custom workflows)
-- System workflows (user_id = NULL) can have duplicate names
CREATE UNIQUE INDEX IF NOT EXISTS idx_workflows_user_name_unique
    ON workflows(user_id, name)
    WHERE user_id IS NOT NULL;

-- ============================================================================
-- Table 3: Pipeline Configs
-- ============================================================================
-- Purpose: Store reusable pipeline configurations that users can save and reuse
-- Features: Links to workflows, stores parameter values as JSONB

CREATE TABLE IF NOT EXISTS pipeline_configs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    workflow_id INTEGER REFERENCES workflows(id) ON DELETE RESTRICT,
    config_data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for pipeline_configs table
CREATE INDEX IF NOT EXISTS idx_pipeline_configs_user_id ON pipeline_configs(user_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_configs_workflow_id ON pipeline_configs(workflow_id);

-- ============================================================================
-- Table 4: Jobs
-- ============================================================================
-- Purpose: Store assembly job records that users create
-- Features: Links to workflows and optional pipeline configs, tracks job status

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    workflow_id INTEGER REFERENCES workflows(id) ON DELETE RESTRICT,
    pipeline_config_id INTEGER REFERENCES pipeline_configs(id) ON DELETE SET NULL,
    assembler VARCHAR(50),
    data_types JSONB,
    cloud_provider VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Check constraints for jobs table (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_job_status'
          AND conrelid = 'jobs'::regclass
    ) THEN
        ALTER TABLE jobs
        ADD CONSTRAINT chk_job_status
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_cloud_provider'
          AND conrelid = 'jobs'::regclass
    ) THEN
        ALTER TABLE jobs
        ADD CONSTRAINT chk_cloud_provider
        CHECK (cloud_provider IN ('aws', 'gcp', 'azure', 'local') OR cloud_provider IS NULL);
    END IF;
END $$;

-- Indexes for jobs table
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_workflow_id ON jobs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_id, status);

-- ============================================================================
-- Table 5: Job Executions
-- ============================================================================
-- Purpose: Track individual execution attempts for jobs (supports retries and execution history)
-- Features: Stores tool versions and parameters for reproducibility

CREATE TABLE IF NOT EXISTS job_executions (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    execution_number INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'running',
    nextflow_run_id VARCHAR(100),
    work_dir VARCHAR(500),
    output_dir VARCHAR(500),
    process_id INTEGER,
    tool_versions JSONB,
    parameters_used JSONB,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Constraints for job_executions (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_execution_status'
          AND conrelid = 'job_executions'::regclass
    ) THEN
        ALTER TABLE job_executions
        ADD CONSTRAINT chk_execution_status
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_job_execution_number'
          AND conrelid = 'job_executions'::regclass
    ) THEN
        ALTER TABLE job_executions
        ADD CONSTRAINT uq_job_execution_number
        UNIQUE (job_id, execution_number);
    END IF;
END $$;

-- Indexes for job_executions table
CREATE INDEX IF NOT EXISTS idx_job_executions_job_id ON job_executions(job_id);
CREATE INDEX IF NOT EXISTS idx_job_executions_status ON job_executions(status);
CREATE INDEX IF NOT EXISTS idx_job_executions_nextflow_run_id ON job_executions(nextflow_run_id);
CREATE INDEX IF NOT EXISTS idx_job_executions_job_execution_number ON job_executions(job_id, execution_number);

-- ============================================================================
-- Table 6: Files
-- ============================================================================
-- Purpose: Track all files associated with jobs (inputs, outputs, intermediates, logs)
-- Features: Stores S3 keys, file metadata, and checksums for integrity

CREATE TABLE IF NOT EXISTS files (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    file_format VARCHAR(50),
    size_bytes BIGINT,
    checksum VARCHAR(64),
    uploaded_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Check constraint for files table (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_file_type'
          AND conrelid = 'files'::regclass
    ) THEN
        ALTER TABLE files
        ADD CONSTRAINT chk_file_type
        CHECK (file_type IN ('input', 'output', 'intermediate', 'log'));
    END IF;
END $$;

-- Indexes for files table
CREATE INDEX IF NOT EXISTS idx_files_job_id ON files(job_id);
CREATE INDEX IF NOT EXISTS idx_files_file_type ON files(file_type);
CREATE INDEX IF NOT EXISTS idx_files_s3_key ON files(s3_key);
CREATE INDEX IF NOT EXISTS idx_files_job_type ON files(job_id, file_type);

-- ============================================================================
-- Triggers: Automatic Timestamp Updates
-- ============================================================================
-- Purpose: Automatically update updated_at timestamp on row modification

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers (idempotent: drop then create)
DROP TRIGGER IF EXISTS trigger_update_users_updated_at ON users;
CREATE TRIGGER trigger_update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_workflows_updated_at ON workflows;
CREATE TRIGGER trigger_update_workflows_updated_at
    BEFORE UPDATE ON workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_pipeline_configs_updated_at ON pipeline_configs;
CREATE TRIGGER trigger_update_pipeline_configs_updated_at
    BEFORE UPDATE ON pipeline_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_jobs_updated_at ON jobs;
CREATE TRIGGER trigger_update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
