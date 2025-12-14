# Project Specification Compliance Summary

This document summarizes how the database design and implementation plans comply with the CASSIE Project Specification Document (T2522).

---

## ✅ Compliance Checklist

### 1. Reproducibility Requirements (Spec Section 1.4)

**Requirement**: *"versions of the tools used in CASSIE, parameters, and workflow steps are logged by the system and presented to the user"*

**Implementation**:
- ✅ **Tool Versions**: `job_executions.tool_versions` (JSONB) - Stores Docker image versions used
- ✅ **Parameters**: `job_executions.parameters_used` (JSONB) - Stores actual parameters used in execution
- ✅ **Workflow Steps**: `workflows.workflow_steps` (JSONB) - Stores ordered workflow steps
- ✅ **Workflow Content**: `workflows.workflow_content` (TEXT) - Complete Nextflow pipeline code

**Status**: ✅ **COMPLIANT**

---

### 2. Data Privacy & Logging (Spec Section 1.3.3, 1.4)

**Requirement**: *"Log systems should not contain any sensitive biological data and should retain only minimal data solely for technical debugging purposes"*

**Implementation**:
- ✅ `job_executions.error_message` - Technical errors only (TEXT field)
- ✅ `files.file_type = 'log'` - Separate log file tracking
- ✅ Log files stored separately from genomic data files
- ⚠️ **Note**: Application code must ensure error messages and logs never contain genomic sequences

**Status**: ✅ **COMPLIANT** (with implementation note)

---

### 3. Multi-Tenant Data Isolation (Spec Section 1.3.3)

**Requirement**: *"completely isolate user data from each other"*

**Implementation**:
- ✅ Per-user S3 buckets (`users.bucket_name` - UNIQUE)
- ✅ All data tables have `user_id` foreign keys
- ✅ Files stored in user-specific S3 buckets (`files.s3_key` includes user bucket)
- ✅ Jobs linked to users (`jobs.user_id`)
- ✅ Workflows can be user-specific (`workflows.user_id`)

**Status**: ✅ **COMPLIANT**

---

### 4. Multi-Cloud Support (Spec Section 1.1, README)

**Requirement**: *"Multi-cloud support would be very good to have (as an option in the interface)"*

**Implementation**:
- ✅ `jobs.cloud_provider` field - Tracks which cloud provider was used
- ✅ Values: 'aws', 'gcp', 'azure', 'local'
- ✅ `credential_manager.py` service planned for credential management
- ✅ Can support different cloud providers per job

**Status**: ✅ **COMPLIANT**

---

### 5. Data Type Combinations (Spec Section 1.1, README)

**Requirement**: *"Illumina/Pacbio/ONT combinations, additional HiC, StrandSeq, BioNano combinations, RNAseq"*

**Implementation**:
- ✅ `jobs.data_types` as JSONB array (changed from VARCHAR)
- ✅ Supports multiple data types per job: `["pacbio", "hic"]`, `["illumina", "rna"]`, etc.
- ✅ Flexible to add new data types without schema changes

**Status**: ✅ **COMPLIANT**

---

### 6. User-Uploaded Workflows (Spec Section 1.1)

**Requirement**: *"users can upload their sequencing data, select appropriate tools, and run end-to-end assembly workflows"*

**Implementation**:
- ✅ `workflows.workflow_content` - Stores Nextflow .nf file content
- ✅ `workflows.user_id` - Links workflows to users
- ✅ `workflows.workflow_type = 'custom'` - For user-created workflows
- ✅ `workflows.original_filename` - Stores original filename
- ✅ `workflows.validation_status` - Tracks validation of uploaded workflows
- ✅ Unique workflow names per user

**Status**: ✅ **COMPLIANT**

---

### 7. Workflow Management (Spec Section 1.1)

**Requirement**: *"workflow conduction is managed by Nextflow"*

**Implementation**:
- ✅ Complete Nextflow pipeline storage in database
- ✅ Workflow versioning support
- ✅ Workflow steps tracking
- ✅ Tool usage tracking
- ✅ Parameter schema definition

**Status**: ✅ **COMPLIANT**

---

### 8. Containerization (Spec Section 1.1, 1.3.1)

**Requirement**: *"All tools have been containerized using Docker"*

**Implementation**:
- ✅ Dockerfiles for tools (FastQC, SPAdes, GenomeScope2 implemented)
- ✅ Container images referenced in workflows
- ✅ Tool versions tracked in `job_executions.tool_versions`
- ✅ Nextflow uses Docker containers for execution

**Status**: ✅ **COMPLIANT**

---

## 📋 Database Schema Updates Made

### Changes to Support Spec Requirements:

1. **`jobs.data_type` → `jobs.data_types` (JSONB)**
   - Changed from VARCHAR to JSONB array
   - Supports combinations: `["pacbio", "hic"]`, `["illumina", "rna"]`

2. **Added `jobs.cloud_provider`**
   - Tracks cloud provider per job
   - Values: 'aws', 'gcp', 'azure', 'local'

3. **Added `job_executions.tool_versions` (JSONB)**
   - Stores Docker image versions used
   - Example: `{"fastqc": "0.12.1", "hifiasm": "0.19.8"}`

4. **Added `job_executions.parameters_used` (JSONB)**
   - Stores actual parameters used in execution
   - For reproducibility

5. **Added `workflows.original_filename`**
   - Stores original .nf filename when uploaded

6. **Added `workflows.validation_status` and `validation_error`**
   - Tracks validation of user-uploaded workflows

7. **Added `workflows.is_public`**
   - Enables workflow sharing

8. **Added unique constraint on `(user_id, name)` for workflows**
   - Ensures unique workflow names per user

---

## 🔍 Verification Against Spec Sections

### Section 1.1: Description
- ✅ Cloud-based platform
- ✅ Upload sequencing data
- ✅ Select tools
- ✅ Run workflows
- ✅ Support human and nonhuman data
- ✅ Data privacy mechanisms
- ✅ Docker containerization
- ✅ Nextflow workflow management
- ✅ Quality control, assembly, annotation steps

### Section 1.3.1: Implementation Constraints
- ✅ Docker-based containerization
- ✅ Nextflow workflow management
- ✅ Container compatibility

### Section 1.3.3: Ethical Constraints
- ✅ Data privacy and integrity
- ✅ Access control
- ✅ Multi-tenant isolation
- ✅ Log systems without sensitive data

### Section 1.4: Professional and Ethical Issues
- ✅ Transparency and reproducibility
- ✅ Tool versions logged
- ✅ Parameters logged
- ✅ Workflow steps logged
- ✅ Fairness in resource allocation (via K8s quotas)

### Section 1.5: Standards
- ✅ OCI container standards (Docker)
- ✅ Kubernetes API standards
- ✅ Data format standards (via file_format field)

---

## ⚠️ Implementation Notes

### Critical Implementation Requirements:

1. **Logging Sanitization**
   - Application code MUST ensure error messages never contain genomic sequences
   - Log files should only contain technical debugging information
   - Consider implementing log sanitization functions

2. **Tool Version Tracking**
   - When executing workflows, extract and store Docker image versions
   - Store in `job_executions.tool_versions` JSONB field
   - Example: Query Docker images to get versions before execution

3. **Parameter Logging**
   - Store actual parameters used (not just schema) in `job_executions.parameters_used`
   - Include all Nextflow parameters passed to pipeline
   - This enables exact reproducibility

4. **Data Type Combinations**
   - Frontend should allow selecting multiple data types
   - Store as JSONB array: `["pacbio", "hic"]`
   - Backend should validate combinations are valid

5. **Cloud Provider Selection**
   - Allow users to select cloud provider in UI
   - Store in `jobs.cloud_provider`
   - Use appropriate credentials and infrastructure per provider

---

## ✅ Summary

**All major specification requirements are supported by the database design.**

The schema has been updated to:
- ✅ Support reproducibility (tool versions, parameters, workflow steps)
- ✅ Ensure data privacy (per-user buckets, no sensitive data in logs)
- ✅ Enable multi-cloud support
- ✅ Support data type combinations
- ✅ Enable user-uploaded workflows
- ✅ Track all necessary information for compliance

**Next Steps**: Implement the backend code to properly populate these fields and ensure logging sanitization.

