# Dockerfile & Container Analysis

## Summary
Only **3 out of 10 Dockerfiles** are fully implemented. Most container definitions are empty placeholders. The `dockerized_tools/` directory has working implementations, while `containers/` directory is mostly empty. This document analyzes what's available, what's missing, and provides an implementation plan.

---

## ✅ FULLY IMPLEMENTED (Ready to Use)

### 1. `dockerized_tools/fastqc/Dockerfile` ✅
**Status**: Complete and functional
**Lines**: 11 lines
**Base Image**: `ubuntu:22.04`
**Tool**: FastQC v0.12.1

```dockerfile
FROM ubuntu:22.04
RUN apt-get update && \
    apt-get install -y wget unzip default-jre && \
    wget https://www.bioinformatics.babraham.ac.uk/projects/fastqc/fastqc_v0.12.1.zip -O /tmp/fastqc.zip && \
    unzip /tmp/fastqc.zip -d /opt && \
    chmod +x /opt/FastQC/fastqc && \
    ln -s /opt/FastQC/fastqc /usr/local/bin/fastqc
ENTRYPOINT ["fastqc"]
```

**Supporting Files**:
- ✅ `dockerized_tools/runfastqc.sh` - Working wrapper script
- ✅ `dockerized_tools/buildtools.sh` - Build script includes FastQC

**Usage**: Ready to build and use
```bash
docker build -t fastqc:0.12.1 ./dockerized_tools/fastqc
docker run --rm -v $(pwd):/data fastqc:0.12.1 /data/reads.fastq.gz
```

**Integration**: Can be used immediately in Nextflow pipelines

---

### 2. `dockerized_tools/spades/Dockerfile` ✅
**Status**: Complete and functional
**Lines**: 12 lines
**Base Image**: `ubuntu:22.04`
**Tool**: SPAdes v3.15.5

```dockerfile
FROM ubuntu:22.04
RUN apt-get update && \
    apt-get install -y wget bzip2 python3
RUN wget https://github.com/ablab/spades/releases/download/v3.15.5/SPAdes-3.15.5-Linux.tar.gz -O /tmp/spades.tar.gz && \
    tar -xzf /tmp/spades.tar.gz -C /opt && \
    ln -s /opt/SPAdes-3.15.5-Linux/bin/spades.py /usr/local/bin/spades.py
ENTRYPOINT ["spades.py"]
```

**Supporting Files**:
- ✅ `dockerized_tools/runspades.sh` - Working wrapper script (supports single-end and paired-end)
- ✅ `dockerized_tools/buildtools.sh` - Build script includes SPAdes

**Usage**: Ready to build and use
```bash
docker build -t spades:3.15.5 ./dockerized_tools/spades
docker run --rm -v $(pwd):/data spades:3.15.5 -1 /data/R1.fq -2 /data/R2.fq -o /data/out
```

**Integration**: Can be used immediately in Nextflow pipelines

---

### 3. `dockerized_tools/genomescope2/Dockerfile` ⚠️
**Status**: Mostly complete, but **missing wrapper script**
**Lines**: 17 lines
**Base Image**: `ubuntu:22.04`
**Tool**: GenomeScope 2.0

```dockerfile
FROM ubuntu:22.04
RUN apt-get update && \
    apt-get install -y git r-base wget build-essential zlib1g-dev jellyfish
RUN R -e 'install.packages("devtools", repos="https://cloud.r-project.org")'
RUN R -e 'devtools::install_github("tbenavi1/genomescope2.0")'
COPY run_genomescope.sh /usr/local/bin/run_genomescope.sh
RUN chmod +x /usr/local/bin/run_genomescope.sh
ENTRYPOINT ["run_genomescope.sh"]
```

**Missing File**: ❌ `run_genomescope.sh` - Referenced but doesn't exist

**Supporting Files**:
- ✅ `dockerized_tools/rungenomescope2.sh` - Working wrapper script (has inline command)
- ✅ `dockerized_tools/buildtools.sh` - Build script includes GenomeScope2

**Issue**: The Dockerfile expects `run_genomescope.sh` to be copied, but the file doesn't exist in the directory. The `rungenomescope2.sh` script shows the expected workflow:
```bash
jellyfish count -C -m 21 -s 200M -t 8 <(zcat /data/$READS) -o counts.jf && \
jellyfish histo counts.jf > histogram.histo && \
Rscript -e "genomescope2::genomescope('histogram.histo', 21, 'genomescope_output', max_kmercov=10000)"
```

**Action Needed**: Create `dockerized_tools/genomescope2/run_genomescope.sh` or modify Dockerfile to use inline commands.

---

## ❌ EMPTY (Need Implementation)

### 4. `containers/base/bio_base.Dockerfile` ❌
**Status**: Empty
**Purpose**: Base image for bioinformatics tools
**Action Needed**: Create base image with common dependencies (Python, R, common bioinformatics libraries)

**Implementation Plan**:
```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    r-base \
    wget curl git \
    build-essential \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
```

---

### 5. `containers/fastqc/Dockerfile` ❌
**Status**: Empty
**Purpose**: FastQC container (alternative to dockerized_tools version)
**Note**: Working version exists in `dockerized_tools/fastqc/`
**Action Needed**: Either copy from `dockerized_tools/fastqc/` or create new implementation

**Supporting Files**:
- ❌ `containers/fastqc/entrypoint.sh` - Empty

**Decision**: Use `dockerized_tools/fastqc/` version or create unified version

---

### 6. `containers/hifiasm/Dockerfile` ❌ **HIGH PRIORITY**
**Status**: Empty
**Purpose**: Hifiasm assembler (important for long-read assembly)
**Action Needed**: Create Dockerfile to install Hifiasm
**Reference**: Hifiasm is a key assembler mentioned in project spec

**Implementation Plan**:
```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \
    wget make g++ zlib1g-dev
RUN wget https://github.com/chhylp123/hifiasm/archive/refs/tags/v0.19.8.tar.gz && \
    tar -xzf v0.19.8.tar.gz && \
    cd hifiasm-0.19.8 && \
    make && \
    cp hifiasm /usr/local/bin/
ENTRYPOINT ["hifiasm"]
```

**Supporting Files**:
- ❌ `containers/hifiasm/entrypoint.sh` - Empty

---

### 7. `containers/quast/Dockerfile` ❌ **HIGH PRIORITY**
**Status**: Empty
**Purpose**: QUAST quality assessment tool (mentioned in project spec)
**Action Needed**: Create Dockerfile to install QUAST
**Reference**: QUAST is specifically mentioned in the project requirements

**Implementation Plan**:
```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \
    python3 python3-pip wget
RUN pip3 install quast
ENTRYPOINT ["quast.py"]
```

**Supporting Files**:
- ❌ `containers/quast/entrypoint.sh` - Empty

---

### 8. `containers/repeatmasker/Dockerfile` ❌
**Status**: Empty
**Purpose**: RepeatMasker for repeat annotation (mentioned in project spec)
**Action Needed**: Create Dockerfile to install RepeatMasker
**Note**: RepeatMasker requires additional databases (RepBase)

**Implementation Plan**:
```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \
    wget perl cpanminus
# Install RepeatMasker and dependencies
# Note: Requires RepBase database (license-restricted)
ENTRYPOINT ["RepeatMasker"]
```

**Supporting Files**:
- ❌ `containers/repeatmasker/entrypoint.sh` - Empty

---

### 9. `backend/Dockerfile` ❌
**Status**: Empty
**Purpose**: Backend API container
**Action Needed**: Create Dockerfile for FastAPI backend
**Dependencies**: Python, FastAPI, database drivers, etc.

**Implementation Plan**:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### 10. `frontend/Dockerfile` ❌
**Status**: Empty
**Purpose**: Frontend React application container
**Action Needed**: Create Dockerfile for React/TypeScript frontend
**Dependencies**: Node.js, npm/yarn, build tools

**Implementation Plan**:
```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

---

## 📋 Supporting Scripts Analysis

### ✅ Implemented Scripts

1. **`dockerized_tools/buildtools.sh`** ✅
   - Builds FastQC, SPAdes, and GenomeScope2 images
   - Ready to use
   - Can be extended for new tools

2. **`dockerized_tools/runfastqc.sh`** ✅
   - Wrapper script for running FastQC
   - Handles volume mounting and output directory

3. **`dockerized_tools/runspades.sh`** ✅
   - Wrapper script for running SPAdes
   - Supports both single-end and paired-end reads

4. **`dockerized_tools/rungenomescope2.sh`** ✅
   - Wrapper script for running GenomeScope2
   - Includes full workflow (jellyfish + R script)

### ❌ Empty Scripts

1. **`storage/scripts/sync_to_s3.sh`** ❌
2. **`storage/scripts/fetch_from_s3.sh`** ❌
3. **`scripts/setup_local.sh`** ❌
4. **`scripts/cleanup_jobs.sh`** ❌
5. **`scripts/deploy_cloud.sh`** ❌
6. **`containers/*/entrypoint.sh`** ❌ (all empty)

---

## 🔧 What You Can Work With

### Immediate Use (Ready Now)
1. **FastQC** - Fully functional, can be used for quality control
2. **SPAdes** - Fully functional, can be used for assembly (though project spec mentions other assemblers)
3. **GenomeScope2** - Almost ready, just needs the wrapper script

### Priority Implementation (Project Requirements)
Based on the project specification, these tools are **required** but missing:

1. **Hifiasm** - Critical for long-read assembly (PacBio/HiFi)
2. **QUAST** - Required for assembly quality assessment
3. **RepeatMasker** - Required for repeat annotation
4. **Other Assemblers** mentioned in spec:
   - Flye (long-read assembler)
   - Canu (long-read assembler)
   - MaSuRCA (hybrid assembler)

### Infrastructure Containers
1. **Backend Dockerfile** - Needed to containerize the API
2. **Frontend Dockerfile** - Needed to containerize the web UI
3. **Base bioinformatics image** - Could simplify other Dockerfiles

---

## 🎯 Implementation Plan

### Phase 1: Fix Existing Issues (Quick Wins)
**Goal**: Make all existing Dockerfiles functional

1. **Fix GenomeScope2**
   - Create `dockerized_tools/genomescope2/run_genomescope.sh`
   - Test the container build and execution
   - **Time**: 30 minutes

2. **Test Existing Tools**
   - Build FastQC, SPAdes, GenomeScope2
   - Test each with sample data
   - Verify Nextflow integration
   - **Time**: 1-2 hours

**Deliverable**: 3 fully functional bioinformatics tools

---

### Phase 2: Critical Missing Tools (High Priority)
**Goal**: Implement tools required by project specification

1. **Hifiasm** (Critical)
   - Create `containers/hifiasm/Dockerfile`
   - Create `containers/hifiasm/entrypoint.sh`
   - Test with sample data
   - **Time**: 2-3 hours

2. **QUAST** (Critical)
   - Create `containers/quast/Dockerfile`
   - Create `containers/quast/entrypoint.sh`
   - Test with sample assembly
   - **Time**: 1-2 hours

3. **RepeatMasker** (Medium Priority)
   - Create `containers/repeatmasker/Dockerfile`
   - Handle RepBase database (license considerations)
   - **Time**: 3-4 hours

**Deliverable**: Core tools for assembly and quality assessment

---

### Phase 3: Additional Assemblers (Medium Priority)
**Goal**: Support multiple assembler options

1. **Flye**
   - Create Dockerfile
   - Test installation
   - **Time**: 1-2 hours

2. **Canu**
   - Create Dockerfile
   - Test installation
   - **Time**: 2-3 hours

3. **MaSuRCA**
   - Create Dockerfile
   - Test installation
   - **Time**: 2-3 hours

**Deliverable**: Multiple assembler options for users

---

### Phase 4: Infrastructure Containers (Essential)
**Goal**: Containerize application components

1. **Backend Dockerfile**
   - Create multi-stage build if needed
   - Optimize image size
   - Test with database connection
   - **Time**: 1 hour

2. **Frontend Dockerfile**
   - Create build stage
   - Create production stage with nginx
   - Test deployment
   - **Time**: 1-2 hours

3. **Base Bioinformatics Image** (Optional)
   - Create common base image
   - Refactor other Dockerfiles to use it
   - **Time**: 2-3 hours

**Deliverable**: Complete containerized application

---

### Phase 5: Supporting Tools (Lower Priority)
**Goal**: Additional tools mentioned in spec

1. **BUSCO** - Gene completeness assessment
2. **SEDEF/BISER** - Segmental duplications
3. **SALSA** - Scaffolding
4. **DENTIST** - Scaffolding
5. **HiC Integration** tools

**Deliverable**: Complete toolset for full assembly pipeline

---

## 📊 Implementation Priority Matrix

| Tool | Priority | Status | Estimated Time | Dependencies |
|------|----------|--------|----------------|--------------|
| FastQC | ✅ Done | Complete | - | None |
| SPAdes | ✅ Done | Complete | - | None |
| GenomeScope2 | ⚠️ High | Needs script | 30 min | None |
| Hifiasm | 🔴 Critical | Empty | 2-3 hours | None |
| QUAST | 🔴 Critical | Empty | 1-2 hours | None |
| Backend | 🔴 Critical | Empty | 1 hour | Python, FastAPI |
| Frontend | 🔴 Critical | Empty | 1-2 hours | Node.js |
| RepeatMasker | 🟡 Medium | Empty | 3-4 hours | RepBase DB |
| Flye | 🟡 Medium | Empty | 1-2 hours | None |
| Canu | 🟡 Medium | Empty | 2-3 hours | None |
| MaSuRCA | 🟡 Medium | Empty | 2-3 hours | None |

---

## 🔗 Integration with Backend

For your backend implementation, you'll need to:

1. **Use existing tools**: FastQC, SPAdes, GenomeScope2 can be used immediately
2. **Implement missing tools**: Create Dockerfiles for Hifiasm, QUAST, etc.
3. **Nextflow integration**: These containers need to work with Nextflow pipelines
4. **Container registry**: Decide where to store/pull images (Docker Hub, private registry, or build on-demand)

The backend's `nextflow_runner.py` service will need to:
- Know which container images are available
- Launch Nextflow with appropriate container parameters
- Handle container resource limits
- Monitor container execution

---

## 💡 Key Implementation Insights

1. **Two Container Directories**: 
   - `dockerized_tools/` - Has working implementations (3 tools)
   - `containers/` - Empty placeholders (intended for Nextflow integration?)

2. **Tool Versions**: The working Dockerfiles use specific versions:
   - FastQC: v0.12.1
   - SPAdes: v3.15.5
   - GenomeScope2: Latest from GitHub

3. **Build System**: `buildtools.sh` provides a simple build script, but you'll need a more comprehensive build system for production.

4. **Nextflow Integration**: The empty `containers/` directory suggests these are meant to be used with Nextflow pipelines. You'll need to:
   - Implement the Dockerfiles
   - Ensure they work with Nextflow's container execution
   - Create proper entrypoint scripts

5. **Missing Critical Tools**: The project spec requires several tools that don't have Dockerfiles yet, especially assemblers for long-read data (Hifiasm, Flye, Canu).

---

## 🚀 Getting Started

### Step 1: Fix GenomeScope2 (Quick Win)
```bash
# Create the missing wrapper script
cat > dockerized_tools/genomescope2/run_genomescope.sh << 'EOF'
#!/bin/bash
set -e
READS=$1
jellyfish count -C -m 21 -s 200M -t 8 <(zcat $READS) -o counts.jf
jellyfish histo counts.jf > histogram.histo
Rscript -e "genomescope2::genomescope('histogram.histo', 21, 'genomescope_output', max_kmercov=10000)"
EOF

chmod +x dockerized_tools/genomescope2/run_genomescope.sh
```

### Step 2: Test Existing Tools
```bash
cd dockerized_tools
bash buildtools.sh

# Test FastQC
docker run --rm -v $(pwd):/data fastqc:0.12.1 /data/test.fastq

# Test SPAdes
docker run --rm -v $(pwd):/data spades:3.15.5 -1 /data/R1.fq -2 /data/R2.fq -o /data/out
```

### Step 3: Implement Critical Tools
Start with Hifiasm and QUAST as they're required by the project specification.

---

## 📝 Important Notes

1. **Start with Available Tools**: Use FastQC and SPAdes to build and test the Nextflow integration first
2. **Prioritize Critical Tools**: Focus on Hifiasm and QUAST before other assemblers
3. **Test Each Tool**: Verify each Dockerfile works before moving to the next
4. **Consider Versions**: Use stable, tested versions of tools
5. **Document Dependencies**: Note any special requirements (like RepBase for RepeatMasker)

---

## 🔄 Next Steps

1. ✅ Fix GenomeScope2 wrapper script
2. ✅ Test all 3 existing tools
3. ✅ Implement Hifiasm Dockerfile
4. ✅ Implement QUAST Dockerfile
5. ✅ Create Backend and Frontend Dockerfiles
6. ✅ Integrate with Nextflow pipelines

