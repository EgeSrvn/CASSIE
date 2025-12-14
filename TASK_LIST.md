# CASSIE Project - Complete Task List

## Current Status
- ✅ Database design completed and documented
- ✅ Analysis documents created (Backend, Dockerfile, Database Design)
- ✅ Frontend prototype created (React + TypeScript)
- ✅ Phase 1: Database Foundation - Completed (Tasks 1.1, 1.2, 1.3)
- ❌ Backend implementation - In progress
- ❌ Nextflow pipelines - Not implemented
- ❌ Docker containers - 3/10 implemented

---

## Phase 1: Database Foundation

### Task 1.1: Create Database Schema SQL File
**File**: `backend/api/database/schemas.sql`
**Status**: Pending
**Description**: 
- Create complete SQL schema with all 6 tables (users, workflows, pipeline_configs, jobs, job_executions, files)
- Include all indexes, constraints, triggers
- Reference: `DATABASE_DESIGN.md`

**Tables to create**:
- `users` (id, username, email, password_hash, bucket_name, timestamps)
- `workflows` (id, name, description, workflow_type, user_id, workflow_content, original_filename, tools_used, workflow_steps, parameters_schema, validation_status, validation_error, is_public, version, is_active, timestamps)
- `pipeline_configs` (id, name, description, user_id, workflow_id, config_data, timestamps)
- `jobs` (id, user_id, name, status, workflow_id, pipeline_config_id, assembler, data_types, cloud_provider, timestamps)
- `job_executions` (id, job_id, execution_number, status, nextflow_run_id, work_dir, output_dir, process_id, tool_versions, parameters_used, error_message, timestamps)
- `files` (id, job_id, filename, s3_key, file_type, file_format, size_bytes, checksum, timestamps)

**Deliverable**: Complete SQL schema file ready for execution

---

### Task 1.2: Create Database Connection Module
**File**: `backend/api/database/db_init.py`
**Status**: ✅ Completed
**Description**:
- PostgreSQL connection pooling
- Database initialization function
- Context manager for connections
- Schema execution on startup
- Reference: `emulation/db_manager.py` for patterns

**Deliverable**: Working database connection and initialization

---

### Task 1.3: Test Database Setup
**Status**: ✅ Completed
**Description**:
- Start PostgreSQL container
- Run schema SQL file
- Test connection
- Verify all tables created correctly

**Deliverable**: Verified working database

---

## Phase 2: Backend Utilities

### Task 2.1: Create Configuration Loader
**File**: `backend/api/utils/config_loader.py`
**Status**: Pending
**Description**:
- Load environment variables
- Settings for database, MinIO, API, Nextflow
- Support for .env files
- Default values for development

**Settings needed**:
- DATABASE_URL
- MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET_NAME
- API_HOST, API_PORT, API_PREFIX
- NEXTFLOW_EXECUTABLE, NEXTFLOW_WORK_DIR, NEXTFLOW_OUTPUT_DIR
- CORS_ORIGINS

**Deliverable**: Configuration management utility

---

### Task 2.2: Create Logger Utility
**File**: `backend/api/utils/logger.py`
**Status**: Pending
**Description**:
- Structured logging setup
- Console output with timestamps
- Log levels (INFO, ERROR, DEBUG)
- Reusable logger instance

**Deliverable**: Logging utility

---

### Task 2.3: Create Response Builder
**File**: `backend/api/utils/response_builder.py`
**Status**: Pending
**Description**:
- Standardized API response format
- Success response helper
- Error response helper
- Pydantic models for responses

**Deliverable**: Response formatting utility

---

### Task 2.4: Create Input Validators
**File**: `backend/api/utils/validators.py`
**Status**: Pending
**Description**:
- Job name validation
- Assembler validation (hifiasm, flye, canu, spades, masurca)
- Data type validation (pacbio, ont, illumina, hifi)
- File extension validation
- Email validation

**Deliverable**: Input validation utilities

---

## Phase 3: Data Models

### Task 3.1: Create User Models
**File**: `backend/api/models/user_model.py`
**Status**: Pending
**Description**:
- UserBase (username, email)
- UserCreate (with password)
- UserResponse (with id, timestamps)
- Pydantic models matching database schema

**Deliverable**: User data models

---

### Task 3.2: Create Job Models
**File**: `backend/api/models/job_model.py`
**Status**: Pending
**Description**:
- JobStatus enum (pending, running, completed, failed, cancelled)
- JobBase (name, assembler, data_type)
- JobCreate (with optional pipeline_config)
- JobUpdate (status, nextflow_run_id, output_files, error_message)
- JobResponse (complete job data with timestamps)

**Deliverable**: Job data models

---

### Task 3.3: Create Pipeline Models
**File**: `backend/api/models/pipeline_model.py`
**Status**: Pending
**Description**:
- WorkflowBase, WorkflowCreate, WorkflowResponse
- PipelineConfigBase, PipelineConfigCreate, PipelineConfigResponse
- WorkflowType enum
- Models matching database schema

**Deliverable**: Pipeline and workflow data models

---

## Phase 4: Core Services

### Task 4.1: Create MinIO/S3 Client Service
**File**: `backend/api/services/minio_client.py`
**Status**: Pending
**Description**:
- Initialize S3 client (boto3)
- Per-user bucket management
- Upload file to S3
- Download file from S3
- List files with prefix
- Delete file
- Generate presigned URLs
- Reference: `emulation/bucket_manager.py`

**Deliverable**: Working MinIO/S3 client service

---

### Task 4.2: Create Nextflow Runner Service
**File**: `backend/api/services/nextflow_runner.py`
**Status**: Pending
**Description**:
- Initialize Nextflow runner
- Run pipeline with parameters
- Background execution (non-blocking)
- Job-specific work/output directories
- Basic status checking
- Error handling

**Deliverable**: Nextflow pipeline execution service

---

## Phase 5: FastAPI Application

### Task 5.1: Create Main FastAPI Application
**File**: `backend/api/main.py`
**Status**: Pending
**Description**:
- Initialize FastAPI app
- Configure CORS middleware
- Register route modules
- Database initialization on startup
- Health check endpoint
- Shutdown handlers

**Deliverable**: Working FastAPI application

---

### Task 5.2: Create Job Management Routes
**File**: `backend/api/routes/jobs.py`
**Status**: Pending
**Description**:
- POST /api/jobs - Create new job
- GET /api/jobs - List user's jobs
- GET /api/jobs/{job_id} - Get job details
- DELETE /api/jobs/{job_id} - Delete job
- Input validation
- Database integration
- Error handling

**Deliverable**: Complete job CRUD API

---

### Task 5.3: Create Storage Routes
**File**: `backend/api/routes/storage.py`
**Status**: Pending
**Description**:
- POST /api/storage/upload - Upload file (for job inputs)
- GET /api/storage/files - List user files
- GET /api/storage/files/{file_id} - Get file details
- GET /api/storage/files/{file_id}/download - Download file
- DELETE /api/storage/files/{file_id} - Delete file
- Link files to jobs

**Note**: Workflow file uploads are handled in workflow routes, not storage routes

**Deliverable**: File management API

---

### Task 5.4: Create Authentication Routes (Placeholder)
**File**: `backend/api/routes/auth.py`
**Status**: Pending
**Description**:
- POST /api/auth/register - User registration
- POST /api/auth/login - User login
- GET /api/auth/status - Check auth status
- JWT token generation (basic implementation)
- Password hashing

**Deliverable**: Basic authentication API

---

### Task 5.5: Create Cost Estimation Routes (Placeholder)
**File**: `backend/api/routes/estimator.py`
**Status**: Pending
**Description**:
- POST /api/estimator/estimate - Estimate job cost
- Basic cost calculation
- Resource estimation

**Deliverable**: Cost estimation API (placeholder)

---

## Phase 6: Nextflow Pipelines

### Task 6.1: Create Basic Nextflow Pipeline
**File**: `pipelines/main.nf`
**Status**: Pending
**Description**:
- Main pipeline entry point
- Support for FastQC (available tool)
- Support for SPAdes (available tool)
- Container-based execution
- Input/output handling
- Parameter passing

**Deliverable**: Working Nextflow pipeline

---

### Task 6.2: Create FastQC Pipeline Module
**File**: `pipelines/fastqc.nf`
**Status**: Pending
**Description**:
- FastQC process definition
- Use fastqc:0.12.1 container
- Input/output channels
- Quality control workflow

**Deliverable**: FastQC pipeline module

---

### Task 6.3: Create SPAdes Pipeline Module
**File**: `pipelines/assembler/spades.nf` or integrate into main.nf
**Status**: Pending
**Description**:
- SPAdes process definition
- Use spades:3.15.5 container
- Support single-end and paired-end
- Assembly workflow

**Deliverable**: SPAdes pipeline module

---

## Phase 7: Integration & Testing

### Task 7.1: Integrate Job Creation with Pipeline Execution
**Status**: Pending
**Description**:
- Trigger Nextflow pipeline when job is created
- Update job status to "running"
- Store execution details in job_executions table
- Handle pipeline errors

**Deliverable**: Automatic pipeline execution on job creation

---

### Task 7.2: Implement Job Status Monitoring
**Status**: Pending
**Description**:
- Poll Nextflow pipeline status
- Update job status in database
- Handle completion/failure
- Store output file references

**Deliverable**: Job status tracking

---

### Task 7.3: Test End-to-End Flow
**Status**: Pending
**Description**:
- Test: Frontend → Backend → Database
- Test: Job creation → Pipeline execution
- Test: File upload → Job execution → Results
- Verify all integrations work

**Deliverable**: Working end-to-end system

---

## Phase 8: Docker Containers (Parallel Track)

### Task 8.1: Fix GenomeScope2 Dockerfile
**File**: `dockerized_tools/genomescope2/run_genomescope.sh`
**Status**: Pending
**Description**:
- Create missing wrapper script
- Test container build
- Verify execution

**Deliverable**: Working GenomeScope2 container

---

### Task 8.2: Create Hifiasm Dockerfile
**File**: `containers/hifiasm/Dockerfile`
**Status**: Pending
**Description**:
- Install Hifiasm
- Create entrypoint script
- Test with sample data
- Reference: Project spec requires Hifiasm

**Deliverable**: Working Hifiasm container

---

### Task 8.3: Create QUAST Dockerfile
**File**: `containers/quast/Dockerfile`
**Status**: Pending
**Description**:
- Install QUAST
- Create entrypoint script
- Test with sample assembly
- Reference: Project spec requires QUAST

**Deliverable**: Working QUAST container

---

### Task 8.4: Create Backend Dockerfile
**File**: `backend/Dockerfile`
**Status**: Pending
**Description**:
- Python 3.11 base image
- Install dependencies
- Copy application code
- Expose port 8000
- CMD to run uvicorn

**Deliverable**: Backend container image

---

### Task 8.5: Create Frontend Dockerfile
**File**: `frontend/Dockerfile`
**Status**: Pending
**Description**:
- Multi-stage build (Node.js build, nginx serve)
- Build React app
- Serve with nginx
- Expose port 80

**Deliverable**: Frontend container image

---

## Phase 9: Advanced Features (Future)

### Task 9.1: Workflow Management API
**Status**: Pending
**Description**:
- CRUD operations for workflows
- **POST /api/workflows** - Upload/create workflow (accept .nf file upload)
- **GET /api/workflows** - List workflows (user's workflows + public workflows)
- **GET /api/workflows/{id}** - Get workflow details
- **PUT /api/workflows/{id}** - Update workflow
- **DELETE /api/workflows/{id}** - Delete workflow
- Store Nextflow content in database
- Validate uploaded workflows (syntax checking)
- System workflow seeding
- Workflow versioning
- Support for user-uploaded workflows
- Workflow sharing (public/private)

---

### Task 9.2: Pipeline Configuration Management
**Status**: Pending
**Description**:
- CRUD operations for pipeline configs
- Reusable configurations
- Parameter validation

---

### Task 9.3: Kubernetes Integration
**File**: `backend/api/services/kubernetes_manager.py`
**Status**: Pending
**Description**:
- Namespace management
- Pod deployment
- Resource quotas

---

### Task 9.4: Auto-scaling Service
**File**: `backend/api/services/vm_autoscaler.py`
**Status**: Pending
**Description**:
- Resource monitoring
- Scale up/down logic
- Cost optimization

---

## Documentation Tasks

### Task D.1: Create Backend README
**File**: `backend/README.md`
**Status**: Pending
**Description**:
- Setup instructions
- API documentation
- Development guide

---

### Task D.2: Update Main README
**File**: `README.md`
**Status**: Pending
**Description**:
- Project overview
- Setup instructions
- Architecture overview

---

## Testing Tasks

### Task T.1: Create Unit Tests
**Status**: Pending
**Description**:
- Test utilities
- Test models
- Test services

---

### Task T.2: Create API Tests
**Status**: Pending
**Description**:
- Test job endpoints
- Test storage endpoints
- Test authentication

---

## Priority Order

### Must Have (MVP)
1. Task 1.1 - Database Schema SQL
2. Task 1.2 - Database Connection
3. Task 2.1-2.4 - Backend Utilities
4. Task 3.1-3.3 - Data Models
5. Task 4.1 - MinIO Client
6. Task 5.1 - FastAPI Main App
7. Task 5.2 - Job Routes
8. Task 4.2 - Nextflow Runner
9. Task 6.1 - Basic Nextflow Pipeline
10. Task 7.1 - Job-Pipeline Integration

### Should Have (Core Features)
11. Task 5.3 - Storage Routes
12. Task 5.4 - Authentication
13. Task 7.2 - Status Monitoring
14. Task 8.2 - Hifiasm Container
15. Task 8.3 - QUAST Container

### Nice to Have (Advanced)
16. Task 8.1 - Fix GenomeScope2
17. Task 8.4-8.5 - Application Containers
18. Task 9.x - Advanced Features

---

## Key Files Reference

### Analysis Documents
- `BACKEND_ANALYSIS.md` - Backend implementation analysis
- `DOCKERFILE_ANALYSIS.md` - Container analysis
- `DATABASE_DESIGN.md` - Complete database schema design

### Reference Code
- `emulation/db_manager.py` - Database connection patterns
- `emulation/bucket_manager.py` - MinIO/S3 patterns
- `emulation/tenant_commands.py` - Multi-tenancy patterns

### Working Tools
- `dockerized_tools/fastqc/` - Working FastQC container
- `dockerized_tools/spades/` - Working SPAdes container
- `dockerized_tools/genomescope2/` - Almost working (needs script)

---

## Next Steps for New Session

1. ✅ **Phase 1 Complete** - Database Foundation (Tasks 1.1, 1.2, 1.3)
2. Start with **Task 2.1** - Create Configuration Loader
3. Continue with Tasks 2.2-2.4 (Backend Utilities)
4. Follow priority order above
5. Test each component as you build
6. Reference analysis documents for guidance
7. Use emulation code as reference for patterns

---

## Notes

- Work incrementally: one file at a time
- Test as you go: verify each component works
- Use reference code: emulation system has working patterns
- Follow database design: `DATABASE_DESIGN.md` is the source of truth
- Start simple: get basic functionality working first

