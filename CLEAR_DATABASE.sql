-- CASSIE Database Cleanup Script
-- This script truncates all tables and resets sequences
-- WARNING: This will delete ALL data in the database!

-- Disable foreign key checks temporarily (PostgreSQL doesn't support this directly,
-- so we'll use TRUNCATE CASCADE which handles foreign keys automatically)

-- Truncate all tables in a single statement
-- Using CASCADE to automatically handle foreign key constraints
-- RESTART IDENTITY resets all sequences automatically

TRUNCATE TABLE 
    execution_datasets,
    votes,
    saved_workflows,
    community_workflows,
    datasets,
    folders,        -- Must be before files (files reference folders)
    files,
    job_executions,
    pipelines,      -- Must be before jobs (jobs reference pipelines)
    jobs,
    pipeline_configs,
    workflows,
    tenants,
    vms,
    users
RESTART IDENTITY CASCADE;

-- Note: Order respects foreign key dependencies:
-- - folders truncated before files (files.folder_id references folders.id)
-- - pipelines truncated before jobs (jobs.pipeline_id references pipelines.id)
-- CASCADE handles remaining dependencies automatically

-- Note: RESTART IDENTITY in TRUNCATE above already resets all sequences
-- No need for separate ALTER SEQUENCE statements

-- Verify tables are empty
SELECT 
    'users' as table_name, COUNT(*) as row_count FROM users
UNION ALL
SELECT 'workflows', COUNT(*) FROM workflows
UNION ALL
SELECT 'pipeline_configs', COUNT(*) FROM pipeline_configs
UNION ALL
SELECT 'pipelines', COUNT(*) FROM pipelines
UNION ALL
SELECT 'jobs', COUNT(*) FROM jobs
UNION ALL
SELECT 'job_executions', COUNT(*) FROM job_executions
UNION ALL
SELECT 'files', COUNT(*) FROM files
UNION ALL
SELECT 'folders', COUNT(*) FROM folders
UNION ALL
SELECT 'datasets', COUNT(*) FROM datasets
UNION ALL
SELECT 'community_workflows', COUNT(*) FROM community_workflows
UNION ALL
SELECT 'saved_workflows', COUNT(*) FROM saved_workflows
UNION ALL
SELECT 'votes', COUNT(*) FROM votes
UNION ALL
SELECT 'execution_datasets', COUNT(*) FROM execution_datasets
UNION ALL
SELECT 'vms', COUNT(*) FROM vms
UNION ALL
SELECT 'tenants', COUNT(*) FROM tenants
ORDER BY table_name;

