# Database Setup Testing (Task 1.3)

This directory contains tests for verifying the database setup works correctly.

## Quick Start

### Option 1: Automated Setup and Test

1. **Set up the database** (first time only):
   ```bash
   python backend/scripts/setup_database.py
   ```

2. **Run the test**:
   ```bash
   python -m backend.tests.test_database_setup
   ```
   OR
   ```bash
   cd backend && python tests/test_database_setup.py
   ```

### Option 2: Manual Setup

1. **Start PostgreSQL container manually**:
   ```bash
   docker run -d --name postgres-cassie \
     -e POSTGRES_USER=admin \
     -e POSTGRES_PASSWORD=admin \
     -e POSTGRES_DB=postgres \
     -p 5432:5432 \
     postgres:15
   ```

2. **Create the database** (connect to PostgreSQL and run):
   ```sql
   CREATE DATABASE cassie_db;
   ```

3. **Run the test**:
   ```bash
   python -m backend.tests.test_database_setup
   ```

## What the Test Does

The test script (`test_database_setup.py`) verifies:

1. ✅ **Connection Test**: Can connect to PostgreSQL
2. ✅ **Schema Initialization**: Can run the schema SQL file
3. ✅ **Tables Verification**: All 6 tables are created:
   - `users`
   - `workflows`
   - `pipeline_configs`
   - `jobs`
   - `job_executions`
   - `files`
4. ✅ **Indexes/Constraints**: Key indexes, constraints, and triggers exist

## Requirements

- Python 3.8+
- `psycopg2-binary` package
- `docker` package (for automated setup)
- Docker installed and running (for container setup)

Install dependencies:
```bash
pip install psycopg2-binary docker
```

## Troubleshooting

### Connection Failed
- Make sure PostgreSQL container is running: `docker ps`
- Check if port 5432 is available
- Verify credentials match (admin/admin)

### Database Doesn't Exist
- Run `setup_database.py` to create it automatically
- Or create manually: `CREATE DATABASE cassie_db;`

### Schema Initialization Fails
- Check that `schemas.sql` exists in `backend/api/database/`
- Verify SQL syntax is correct
- Check PostgreSQL logs: `docker logs postgres-cassie`
