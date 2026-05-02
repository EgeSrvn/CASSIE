-- CASSIE Database Schema
-- Created incrementally for Task 1.1
-- Revised to be idempotent (safe to run multiple times)

-- ============================================================================
-- Table 1: Users
-- ============================================================================
-- Purpose: Store user accounts and authentication information
-- Features: User accounts plus a legacy storage namespace column used by the app

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    bucket_name VARCHAR(100) UNIQUE NOT NULL,
    cash_balance_usd NUMERIC(12, 2) NOT NULL DEFAULT 0,
    cash_reserved_usd NUMERIC(12, 2) NOT NULL DEFAULT 0,
    storage_plan_id VARCHAR(120),
    max_storage_gb NUMERIC(12, 3),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    login_two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    job_notifications_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    email_verification_code VARCHAR(12),
    email_verification_expires_at TIMESTAMP,
    password_reset_code VARCHAR(12),
    password_reset_expires_at TIMESTAMP,
    login_two_factor_code VARCHAR(12),
    login_two_factor_expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    account_deletion_code VARCHAR(12),
    account_deletion_expires_at TIMESTAMP,
    suspended_until TIMESTAMP,
    suspension_reason VARCHAR(255)
);

-- Indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_bucket_name ON users(bucket_name);

CREATE TABLE IF NOT EXISTS app_migrations (
    key VARCHAR(120) PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invitation_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(64) UNIQUE NOT NULL,
    note VARCHAR(255),
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    used_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_invitation_codes_code ON invitation_codes(code);
CREATE INDEX IF NOT EXISTS idx_invitation_codes_used_at ON invitation_codes(used_at);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'display_name'
    ) THEN
        ALTER TABLE users ADD COLUMN display_name VARCHAR(120);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'bio'
    ) THEN
        ALTER TABLE users ADD COLUMN bio TEXT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'affiliation'
    ) THEN
        ALTER TABLE users ADD COLUMN affiliation VARCHAR(255);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'job_title'
    ) THEN
        ALTER TABLE users ADD COLUMN job_title VARCHAR(120);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'location'
    ) THEN
        ALTER TABLE users ADD COLUMN location VARCHAR(120);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'website_url'
    ) THEN
        ALTER TABLE users ADD COLUMN website_url VARCHAR(500);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'avatar_url'
    ) THEN
        ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'cash_balance_usd'
    ) THEN
        ALTER TABLE users ADD COLUMN cash_balance_usd NUMERIC(12, 2) NOT NULL DEFAULT 0;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'cash_reserved_usd'
    ) THEN
        ALTER TABLE users ADD COLUMN cash_reserved_usd NUMERIC(12, 2) NOT NULL DEFAULT 0;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'email_verified'
    ) THEN
        ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'storage_plan_id'
    ) THEN
        ALTER TABLE users ADD COLUMN storage_plan_id VARCHAR(120);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'max_storage_gb'
    ) THEN
        ALTER TABLE users ADD COLUMN max_storage_gb NUMERIC(12, 3);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'email_verification_code'
    ) THEN
        ALTER TABLE users ADD COLUMN email_verification_code VARCHAR(12);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'email_verification_expires_at'
    ) THEN
        ALTER TABLE users ADD COLUMN email_verification_expires_at TIMESTAMP;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'password_reset_code'
    ) THEN
        ALTER TABLE users ADD COLUMN password_reset_code VARCHAR(12);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'password_reset_expires_at'
    ) THEN
        ALTER TABLE users ADD COLUMN password_reset_expires_at TIMESTAMP;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'login_two_factor_enabled'
    ) THEN
        ALTER TABLE users ADD COLUMN login_two_factor_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'job_notifications_enabled'
    ) THEN
        ALTER TABLE users ADD COLUMN job_notifications_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'login_two_factor_code'
    ) THEN
        ALTER TABLE users ADD COLUMN login_two_factor_code VARCHAR(12);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'login_two_factor_expires_at'
    ) THEN
        ALTER TABLE users ADD COLUMN login_two_factor_expires_at TIMESTAMP;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'account_deletion_code'
    ) THEN
        ALTER TABLE users ADD COLUMN account_deletion_code VARCHAR(12);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'account_deletion_expires_at'
    ) THEN
        ALTER TABLE users ADD COLUMN account_deletion_expires_at TIMESTAMP;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'suspended_until'
    ) THEN
        ALTER TABLE users ADD COLUMN suspended_until TIMESTAMP;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'suspension_reason'
    ) THEN
        ALTER TABLE users ADD COLUMN suspension_reason VARCHAR(255);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM app_migrations
        WHERE key = 'split_reserved_balance_20260428'
    ) THEN
        UPDATE users
        SET cash_balance_usd = GREATEST(cash_balance_usd - cash_reserved_usd, 0),
            updated_at = NOW()
        WHERE cash_reserved_usd > 0;

        INSERT INTO app_migrations (key)
        VALUES ('split_reserved_balance_20260428');
    END IF;
END $$;

-- ============================================================================
-- Trigger Helper: Automatic Timestamp Updates
-- ============================================================================
-- Defined before any trigger declarations so the schema can be replayed from a
-- clean database as well as against an existing one.

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Table 15: Forum Threads
-- ============================================================================
-- Purpose: Public question threads for the CASSIE forum

CREATE TABLE IF NOT EXISTS forum_threads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    image_keys JSONB DEFAULT '[]'::jsonb,
    view_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forum_threads' AND column_name = 'image_keys'
    ) THEN
        ALTER TABLE forum_threads ADD COLUMN image_keys JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_forum_threads_user_id ON forum_threads(user_id);
CREATE INDEX IF NOT EXISTS idx_forum_threads_created_at ON forum_threads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_forum_threads_updated_at ON forum_threads(updated_at DESC);

-- ============================================================================
-- Table 16: Forum Answers
-- ============================================================================
-- Purpose: Answers posted on forum threads

CREATE TABLE IF NOT EXISTS forum_answers (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forum_answers_thread_id ON forum_answers(thread_id);
CREATE INDEX IF NOT EXISTS idx_forum_answers_user_id ON forum_answers(user_id);
CREATE INDEX IF NOT EXISTS idx_forum_answers_created_at ON forum_answers(created_at ASC);

-- ============================================================================
-- Table 17: Forum Comments
-- ============================================================================
-- Purpose: General thread comments and replies to specific answers

CREATE TABLE IF NOT EXISTS forum_comments (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
    answer_id INTEGER REFERENCES forum_answers(id) ON DELETE CASCADE,
    parent_comment_id INTEGER REFERENCES forum_comments(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    image_keys JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forum_comments' AND column_name = 'parent_comment_id'
    ) THEN
        ALTER TABLE forum_comments ADD COLUMN parent_comment_id INTEGER REFERENCES forum_comments(id) ON DELETE CASCADE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forum_comments' AND column_name = 'image_keys'
    ) THEN
        ALTER TABLE forum_comments ADD COLUMN image_keys JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_forum_comments_thread_id ON forum_comments(thread_id);
CREATE INDEX IF NOT EXISTS idx_forum_comments_answer_id ON forum_comments(answer_id);
CREATE INDEX IF NOT EXISTS idx_forum_comments_parent_comment_id ON forum_comments(parent_comment_id);
CREATE INDEX IF NOT EXISTS idx_forum_comments_user_id ON forum_comments(user_id);
CREATE INDEX IF NOT EXISTS idx_forum_comments_created_at ON forum_comments(created_at ASC);

CREATE TABLE IF NOT EXISTS forum_thread_votes (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote_type VARCHAR(16) NOT NULL CHECK (vote_type IN ('upvote', 'downvote')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE (thread_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_forum_thread_votes_thread_id ON forum_thread_votes(thread_id);
CREATE INDEX IF NOT EXISTS idx_forum_thread_votes_user_id ON forum_thread_votes(user_id);

CREATE TABLE IF NOT EXISTS forum_comment_votes (
    id SERIAL PRIMARY KEY,
    comment_id INTEGER NOT NULL REFERENCES forum_comments(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote_type VARCHAR(16) NOT NULL CHECK (vote_type IN ('upvote', 'downvote')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE (comment_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_forum_comment_votes_comment_id ON forum_comment_votes(comment_id);
CREATE INDEX IF NOT EXISTS idx_forum_comment_votes_user_id ON forum_comment_votes(user_id);

CREATE TABLE IF NOT EXISTS moderation_reports (
    id SERIAL PRIMARY KEY,
    reporter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type VARCHAR(32) NOT NULL CHECK (target_type IN ('pipeline', 'forum_thread', 'forum_comment')),
    target_id INTEGER NOT NULL,
    reason VARCHAR(160) NOT NULL,
    details TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'dismissed')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE (reporter_user_id, target_type, target_id)
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'moderation_reports' AND column_name = 'status'
    ) THEN
        ALTER TABLE moderation_reports DROP CONSTRAINT IF EXISTS moderation_reports_status_check;
        ALTER TABLE moderation_reports
            ADD CONSTRAINT moderation_reports_status_check
            CHECK (status IN ('open', 'reviewed', 'dismissed', 'resolved_removed', 'resolved_suspended'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_moderation_reports_target ON moderation_reports(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_moderation_reports_reporter ON moderation_reports(reporter_user_id);
CREATE INDEX IF NOT EXISTS idx_moderation_reports_status ON moderation_reports(status);

-- Forum triggers are declared here because the forum tables are created after the
-- main trigger block above in this legacy schema file.
DROP TRIGGER IF EXISTS trigger_update_forum_threads_updated_at ON forum_threads;
CREATE TRIGGER trigger_update_forum_threads_updated_at
    BEFORE UPDATE ON forum_threads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_forum_answers_updated_at ON forum_answers;
CREATE TRIGGER trigger_update_forum_answers_updated_at
    BEFORE UPDATE ON forum_answers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_forum_comments_updated_at ON forum_comments;
CREATE TRIGGER trigger_update_forum_comments_updated_at
    BEFORE UPDATE ON forum_comments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_forum_thread_votes_updated_at ON forum_thread_votes;
CREATE TRIGGER trigger_update_forum_thread_votes_updated_at
    BEFORE UPDATE ON forum_thread_votes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_forum_comment_votes_updated_at ON forum_comment_votes;
CREATE TRIGGER trigger_update_forum_comment_votes_updated_at
    BEFORE UPDATE ON forum_comment_votes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_moderation_reports_updated_at ON moderation_reports;
CREATE TRIGGER trigger_update_moderation_reports_updated_at
    BEFORE UPDATE ON moderation_reports
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

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

-- Drop unique constraint on workflow names if it exists (allow duplicate names)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'idx_workflows_user_name_unique'
    ) THEN
        DROP INDEX idx_workflows_user_name_unique;
        RAISE NOTICE 'Dropped unique index idx_workflows_user_name_unique';
    END IF;
END $$;

-- Note: Workflow names are allowed to be duplicated (no unique constraint)
-- Users can create multiple workflows with the same name

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
    execution_preferences JSONB,
    vm_name VARCHAR(50),
    estimated_price_usd NUMERIC(12, 2) NOT NULL DEFAULT 0,
    max_charge_usd NUMERIC(12, 2) NOT NULL DEFAULT 0,
    actual_price_charged_usd NUMERIC(12, 2),
    balance_reserved_at TIMESTAMP,
    balance_charged_at TIMESTAMP,
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
-- Note: idx_jobs_pipeline_id is created in the migration block after pipelines table
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
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_execution_status'
          AND conrelid = 'job_executions'::regclass
          AND pg_get_constraintdef(oid) NOT LIKE '%pending%'
    ) THEN
        ALTER TABLE job_executions
        DROP CONSTRAINT chk_execution_status;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_execution_status'
          AND conrelid = 'job_executions'::regclass
    ) THEN
        ALTER TABLE job_executions
        ADD CONSTRAINT chk_execution_status
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));
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
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
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

DO $$
DECLARE
    existing_constraint_name TEXT;
BEGIN
    SELECT tc.constraint_name INTO existing_constraint_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.table_name = 'files'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = 'job_id'
    LIMIT 1;

    IF existing_constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE files DROP CONSTRAINT %I', existing_constraint_name);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_name = 'files'
          AND constraint_name = 'fk_files_job_id'
    ) THEN
        ALTER TABLE files
        ADD CONSTRAINT fk_files_job_id
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Indexes for files table
CREATE INDEX IF NOT EXISTS idx_files_job_id ON files(job_id);
CREATE INDEX IF NOT EXISTS idx_files_file_type ON files(file_type);
CREATE INDEX IF NOT EXISTS idx_files_s3_key ON files(s3_key);
CREATE INDEX IF NOT EXISTS idx_files_job_type ON files(job_id, file_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_files_unassigned_s3_key_unique ON files(s3_key) WHERE job_id IS NULL;

-- Add folder_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'files' AND column_name = 'folder_id'
    ) THEN
        ALTER TABLE files ADD COLUMN folder_id INTEGER;
    END IF;
END $$;

-- Make job_id nullable (for folder-managed files)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'files' 
        AND column_name = 'job_id' 
        AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE files ALTER COLUMN job_id DROP NOT NULL;
    END IF;
END $$;

-- ============================================================================
-- Table 6.5: Folders
-- ============================================================================
-- Purpose: User-managed folder structure for organizing data files
-- Features: Nested folders with path tracking, per-user isolation

CREATE TABLE IF NOT EXISTS folders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    parent_folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    path TEXT NOT NULL, -- Full path like "root/folder1/subfolder"
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE(user_id, parent_folder_id, name) -- Prevent duplicate folder names in same parent
);

CREATE INDEX IF NOT EXISTS idx_folders_user_id ON folders(user_id);
CREATE INDEX IF NOT EXISTS idx_folders_parent_id ON folders(parent_folder_id);
CREATE INDEX IF NOT EXISTS idx_folders_path ON folders(path);

-- Add foreign key constraint for folder_id in files table (after folders table exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'files_folder_id_fkey'
        AND table_name = 'files'
    ) THEN
        ALTER TABLE files
        ADD CONSTRAINT files_folder_id_fkey
        FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Clean up existing data before adding constraint
DO $$
BEGIN
    -- Drop existing constraint if it exists (in case we need to recreate it)
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_file_location'
    ) THEN
        ALTER TABLE files DROP CONSTRAINT chk_file_location;
    END IF;
    
    -- Fix files where both job_id and folder_id are set (shouldn't happen, but clean up)
    -- Prioritize job_id - if a file has both, it's a job file
    UPDATE files 
    SET folder_id = NULL 
    WHERE job_id IS NOT NULL AND folder_id IS NOT NULL;
    
    -- Note: Files with both NULL are staging files and will be allowed by the constraint
END $$;

-- Add constraint: file must be in folder OR job OR staging (both NULL allowed for staging)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_file_location'
    ) THEN
        ALTER TABLE files
        ADD CONSTRAINT chk_file_location
        CHECK (
            (job_id IS NOT NULL AND folder_id IS NULL) OR 
            (job_id IS NULL AND folder_id IS NOT NULL) OR
            (job_id IS NULL AND folder_id IS NULL)  -- Allow staging files (temporary uploads)
        );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_files_folder_id ON files(folder_id);

-- ============================================================================
-- Table 7: Datasets
-- ============================================================================
-- Purpose: User-managed datasets (input files)
-- Features: Links to files table, supports dataset metadata

CREATE TABLE IF NOT EXISTS datasets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    data_type VARCHAR(50),
    is_imported BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for datasets table
CREATE INDEX IF NOT EXISTS idx_datasets_user_id ON datasets(user_id);
CREATE INDEX IF NOT EXISTS idx_datasets_file_id ON datasets(file_id);
CREATE INDEX IF NOT EXISTS idx_datasets_data_type ON datasets(data_type);

-- ============================================================================
-- Table 8: Community Workflows
-- ============================================================================
-- Purpose: Published workflows available in the community catalog
-- Features: Workflow sharing, popularity tracking, tags

CREATE TABLE IF NOT EXISTS community_workflows (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER REFERENCES workflows(id) ON DELETE CASCADE,
    published_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    tags JSONB,
    popularity_score INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    is_featured BOOLEAN DEFAULT false,
    published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for community_workflows table
CREATE INDEX IF NOT EXISTS idx_community_workflows_workflow_id ON community_workflows(workflow_id);
CREATE INDEX IF NOT EXISTS idx_community_workflows_published_by ON community_workflows(published_by_user_id);
CREATE INDEX IF NOT EXISTS idx_community_workflows_popularity ON community_workflows(popularity_score);
CREATE INDEX IF NOT EXISTS idx_community_workflows_is_featured ON community_workflows(is_featured);

-- ============================================================================
-- Table 9: Saved Workflows
-- ============================================================================
-- Purpose: User-saved community workflows (imported workflows)
-- Features: Tracks which community workflows users have imported

CREATE TABLE IF NOT EXISTS saved_workflows (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    community_workflow_id INTEGER REFERENCES community_workflows(id) ON DELETE CASCADE,
    workflow_id INTEGER REFERENCES workflows(id) ON DELETE CASCADE,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP
);

-- Indexes for saved_workflows table
CREATE INDEX IF NOT EXISTS idx_saved_workflows_user_id ON saved_workflows(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_workflows_community_workflow_id ON saved_workflows(community_workflow_id);
CREATE INDEX IF NOT EXISTS idx_saved_workflows_workflow_id ON saved_workflows(workflow_id);

-- Unique constraint: one saved workflow per user per community workflow
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_workflows_user_community
    ON saved_workflows(user_id, community_workflow_id);

-- ============================================================================
-- Table 10: Votes
-- ============================================================================
-- Purpose: User votes on community workflows (upvote/downvote)
-- Features: Supports upvote/downvote, updates popularity scores

CREATE TABLE IF NOT EXISTS votes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    community_workflow_id INTEGER REFERENCES community_workflows(id) ON DELETE CASCADE,
    vote_type VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Check constraint for votes table (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_vote_type'
          AND conrelid = 'votes'::regclass
    ) THEN
        ALTER TABLE votes
        ADD CONSTRAINT chk_vote_type
        CHECK (vote_type IN ('upvote', 'downvote'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_vote_user_workflow'
          AND conrelid = 'votes'::regclass
    ) THEN
        ALTER TABLE votes
        ADD CONSTRAINT uq_vote_user_workflow
        UNIQUE (user_id, community_workflow_id);
    END IF;
END $$;

-- Indexes for votes table
CREATE INDEX IF NOT EXISTS idx_votes_user_id ON votes(user_id);
CREATE INDEX IF NOT EXISTS idx_votes_community_workflow_id ON votes(community_workflow_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_votes_user_workflow ON votes(user_id, community_workflow_id);

-- ============================================================================
-- Table 11: Execution Datasets
-- ============================================================================
-- Purpose: Linking table between job executions and input datasets
-- Features: Supports multiple datasets per execution with roles

CREATE TABLE IF NOT EXISTS execution_datasets (
    id SERIAL PRIMARY KEY,
    execution_id INTEGER REFERENCES job_executions(id) ON DELETE CASCADE,
    dataset_id INTEGER REFERENCES datasets(id) ON DELETE RESTRICT,
    role VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for execution_datasets table
CREATE INDEX IF NOT EXISTS idx_execution_datasets_execution_id ON execution_datasets(execution_id);
CREATE INDEX IF NOT EXISTS idx_execution_datasets_dataset_id ON execution_datasets(dataset_id);
CREATE INDEX IF NOT EXISTS idx_execution_datasets_execution_dataset ON execution_datasets(execution_id, dataset_id);

-- ============================================================================
-- Triggers: Automatic Timestamp Updates
-- ============================================================================
-- Purpose: Automatically update updated_at timestamp on row modification

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

DROP TRIGGER IF EXISTS trigger_update_datasets_updated_at ON datasets;
CREATE TRIGGER trigger_update_datasets_updated_at
    BEFORE UPDATE ON datasets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_community_workflows_updated_at ON community_workflows;
CREATE TRIGGER trigger_update_community_workflows_updated_at
    BEFORE UPDATE ON community_workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS trigger_update_votes_updated_at ON votes;
CREATE TRIGGER trigger_update_votes_updated_at
    BEFORE UPDATE ON votes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- EMULATION-ONLY TABLES (Temporary - will be removed when moving to AWS)
-- ============================================================================
-- These tables are used by the emulation system for local Docker-based
-- multi-tenant execution. They will be deprecated and removed when the
-- system moves to AWS cloud infrastructure.
-- ============================================================================

-- ============================================================================
-- Table 12: VMs (Emulation Only)
-- ============================================================================
-- Purpose: Track Docker VM containers used for emulation
-- Features: Capacity management and load tracking
-- NOTE: This is emulation-specific and will be removed when moving to AWS

CREATE TABLE IF NOT EXISTS vms (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    max_capacity INTEGER NOT NULL,
    current_load INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for vms table
CREATE INDEX IF NOT EXISTS idx_vms_name ON vms(name);

-- ============================================================================
-- Table 13: Tenants (Emulation Only)
-- ============================================================================
-- Purpose: Track tenant Docker containers per user for emulation
-- Features: Links users to VMs, tracks tenant assignments
-- NOTE: This is emulation-specific and will be removed when moving to AWS
-- NOTE: Tenant names must be unique per user (enforced by application logic)

CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    vm_name VARCHAR(50),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for tenants table
CREATE INDEX IF NOT EXISTS idx_tenants_user_id ON tenants(user_id);
CREATE INDEX IF NOT EXISTS idx_tenants_vm_name ON tenants(vm_name);
CREATE INDEX IF NOT EXISTS idx_tenants_user_name ON tenants(user_id, name);

-- Unique constraint: tenant name must be unique per user
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_user_name_unique
    ON tenants(user_id, name);

-- ============================================================================
-- Table 14: Pipelines
-- ============================================================================
-- Purpose: Store user-created visual pipelines (nodes/edges from ReactFlow)
-- Features: Allows users to save and reuse pipeline configurations

CREATE TABLE IF NOT EXISTS pipelines (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    nodes JSONB,
    edges JSONB,
    saved_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    is_shared BOOLEAN DEFAULT false
);

-- Indexes for pipelines table
CREATE INDEX IF NOT EXISTS idx_pipelines_user_id ON pipelines(user_id);
CREATE INDEX IF NOT EXISTS idx_pipelines_saved_at ON pipelines(saved_at);
-- Note: idx_pipelines_is_shared is created in the migration block below

CREATE TABLE IF NOT EXISTS pipeline_votes (
    id SERIAL PRIMARY KEY,
    pipeline_id INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote_type VARCHAR(16) NOT NULL CHECK (vote_type IN ('upvote', 'downvote')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    UNIQUE (pipeline_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_votes_pipeline_id ON pipeline_votes(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_votes_user_id ON pipeline_votes(user_id);

DROP TRIGGER IF EXISTS trigger_update_pipeline_votes_updated_at ON pipeline_votes;
CREATE TRIGGER trigger_update_pipeline_votes_updated_at
    BEFORE UPDATE ON pipeline_votes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add pipeline_id column to jobs table if it doesn't exist (for existing databases)
-- This must run after pipelines table is created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'pipeline_id'
    ) THEN
        ALTER TABLE jobs ADD COLUMN pipeline_id INTEGER;
    END IF;
    
    -- Add vm_name column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'vm_name'
    ) THEN
        ALTER TABLE jobs ADD COLUMN vm_name VARCHAR(50);
    END IF;

    -- Add execution_preferences column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'execution_preferences'
    ) THEN
        ALTER TABLE jobs ADD COLUMN execution_preferences JSONB;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'estimated_price_usd'
    ) THEN
        ALTER TABLE jobs ADD COLUMN estimated_price_usd NUMERIC(12, 2) NOT NULL DEFAULT 0;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'max_charge_usd'
    ) THEN
        ALTER TABLE jobs ADD COLUMN max_charge_usd NUMERIC(12, 2) NOT NULL DEFAULT 0;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'actual_price_charged_usd'
    ) THEN
        ALTER TABLE jobs ADD COLUMN actual_price_charged_usd NUMERIC(12, 2);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'balance_reserved_at'
    ) THEN
        ALTER TABLE jobs ADD COLUMN balance_reserved_at TIMESTAMP;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'balance_charged_at'
    ) THEN
        ALTER TABLE jobs ADD COLUMN balance_charged_at TIMESTAMP;
    END IF;
    
    -- Add foreign key constraint for pipeline_id after column is added (if pipeline_id was just added)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'jobs' AND column_name = 'pipeline_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_jobs_pipeline_id' AND table_name = 'jobs'
    ) THEN
        ALTER TABLE jobs ADD CONSTRAINT fk_jobs_pipeline_id 
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id) ON DELETE SET NULL;
    END IF;
    
    -- Create index for pipeline_id if it doesn't already exist
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_jobs_pipeline_id'
    ) THEN
        CREATE INDEX idx_jobs_pipeline_id ON jobs(pipeline_id);
    END IF;
    
    -- Add is_shared column to pipelines table if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'pipelines' AND column_name = 'is_shared'
    ) THEN
        ALTER TABLE pipelines ADD COLUMN is_shared BOOLEAN DEFAULT false;
    END IF;
    
    -- Create index for is_shared if it doesn't already exist (only if column exists)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'pipelines' AND column_name = 'is_shared'
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_pipelines_is_shared'
    ) THEN
        CREATE INDEX idx_pipelines_is_shared ON pipelines(is_shared);
    END IF;
END $$;

-- ============================================================================
-- Demo Mode: Add is_admin and is_active columns to users table
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'is_admin'
    ) THEN
        ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'is_active'
    ) THEN
        ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin);

-- ============================================================================
-- Demo Mode: demo_codes table
-- ============================================================================
CREATE TABLE IF NOT EXISTS demo_codes (
    id SERIAL PRIMARY KEY,
    code_hash VARCHAR(255) NOT NULL,
    code_prefix_masked VARCHAR(8) NOT NULL,
    created_by_admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    used_at TIMESTAMP,
    used_by_session_id VARCHAR(36),
    deactivated_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_demo_codes_code_hash ON demo_codes(code_hash);
CREATE INDEX IF NOT EXISTS idx_demo_codes_is_active ON demo_codes(is_active);

-- ============================================================================
-- Demo Mode: demo_sessions table
-- ============================================================================
CREATE TABLE IF NOT EXISTS demo_sessions (
    id VARCHAR(36) PRIMARY KEY,
    demo_code_id INTEGER REFERENCES demo_codes(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    cleanup_completed_at TIMESTAMP
);
