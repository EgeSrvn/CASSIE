# CASSIE: Cloud-based Assembly Streamlined Service Integration Engine

![CASSIE Logo](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## 📋 Table of Contents

- [Overview](#overview)
- [Purpose & Goals](#purpose--goals)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Core Features](#core-features)
- [Quick Start](#quick-start)
- [Detailed Setup Instructions](#detailed-setup-instructions)
- [Available Bioinformatics Tools](#available-bioinformatics-tools)
- [Project Structure](#project-structure)
- [Environment Configuration](#environment-configuration)
- [Development & Deployment](#development--deployment)
- [Admin Panel](#admin-panel)
- [Contributing & Next Steps](#contributing--next-steps)

---

## 📖 Overview

**CASSIE** is a comprehensive, cloud-native genomics analysis platform designed to streamline genome assembly and annotation workflows. It provides a user-friendly web interface for researchers to:

- Create and execute complex bioinformatics pipelines
- Manage genomic data (Illumina, PacBio, Oxford Nanopore reads)
- Perform quality control, assembly, and annotation
- Monitor job execution in real-time
- Store and share results securely

CASSIE abstracts the complexity of distributed computation, containerized tools, and cloud infrastructure, enabling scientists to focus on their research rather than DevOps.

---

## Purpose & Goals

### Problem Statement
Genome assembly and annotation involve multiple interdependent tools and requires significant computational resources. Researchers often struggle with:
- Complex environment setup and dependency management
- Expensive computational infrastructure
- Manual job orchestration and monitoring
- Data management across different storage backends

### Solution
CASSIE provides:

1. **Unified Interface**: Single web application for all assembly/annotation tasks
2. **Visual Pipeline Builder**: Drag-and-drop workflow creation without command-line knowledge
3. **Automated Scaling**: Dynamically provision cloud resources as needed
4. **Multi-Cloud Support**: Run on AWS, GCP, or Azure
5. **Complete Data Isolation**: Per-user S3 buckets for secure data management
6. **Containerized Tools**: Consistent execution environment across platforms

---

## 🏗️ Architecture

CASSIE follows a modern **microservices architecture** with clear separation of concerns:

Frontend (React + Vite) → Backend API (FastAPI) → PostgreSQL, MinIO, Docker, Kubernetes

### Data Flow

1. **User submits job** → Frontend sends job definition to Backend
2. **Backend validates** → Checks tool requirements, input data availability
3. **Job enqueued** → Stored in PostgreSQL with status tracking
4. **Execution** → Docker containers (or Kubernetes pods) run sequentially
5. **Output collection** → Results stored in MinIO/S3
6. **User notified** → Frontend polls backend for job status updates

---

## 🛠️ Technology Stack

### Frontend

| Technology | Version | Purpose |
|-----------|---------|---------|
| **React** | 18.2.0 | UI framework |
| **TypeScript** | 5.2.2 | Type-safe JavaScript |
| **Vite** | 5.0.8 | Lightning-fast build tool |
| **ReactFlow** | 11.10.1 | Visual pipeline builder |
| **React Router** | 6.20.0 | Client-side routing |
| **Axios** | 1.6.2 | HTTP client |

### Backend

| Technology | Version | Purpose |
|-----------|---------|---------|
| **FastAPI** | 0.104.0 | Async web framework |
| **Python** | 3.9+ | Core language |
| **SQLAlchemy** | Latest | ORM for database |
| **Pydantic** | 2.0.0 | Data validation |
| **Uvicorn** | 0.24.0 | ASGI server |
| **psycopg2** | 2.9.0+ | PostgreSQL adapter |
| **Boto3** | 1.28.0+ | AWS S3 / MinIO client |
| **Docker SDK** | 7.0.0+ | Container management |

### Infrastructure & Data

| Technology | Version | Purpose |
|-----------|---------|---------|
| **PostgreSQL** | 15+ | Relational database |
| **MinIO** | Latest | S3-compatible storage |
| **Docker** | Latest | Containerization |
| **Docker Compose** | Latest | Local orchestration |
| **Kubernetes** | 1.24+ | Production orchestration (optional) |
| **Nextflow** | Latest | Workflow engine (optional) |

---

## Core Features

### ✅ User Authentication & Management
- Secure user registration with email verification
- JWT-based authentication and session management
- Per-user data isolation with dedicated S3 buckets
- Bcrypt password hashing for security

### ✅ Visual Pipeline Builder
- Drag-and-drop interface using ReactFlow
- Multiple node types (Input, Tool, Output)
- Automatic validation (no cycles, proper connections)
- Pipeline saving and loading
- Automatic input requirement inference

### ✅ Job Management
- Create one-time jobs or use saved pipelines
- Real-time job status monitoring
- Detailed execution logs and error reporting
- Batch job submission

### ✅ Data Management
- Upload genomic data files (FASTQ, FASTA, BAM/CRAM)
- Organize files in folders
- Secure storage in MinIO/S3
- Automatic cleanup policies
- Download results

### ✅ Forum & Collaboration
- Community forum for discussions
- Moderation tools for admins
- Share results and methods

### ✅ Admin Panel
- User management (create, suspend, delete accounts)
- System monitoring and health checks
- Job queue management
- Database management

---

## Quick Start

### Prerequisites

- **Docker** and **Docker Compose** installed
- **Git** for cloning the repository
- Linux/Mac terminal or Windows PowerShell

### Option 1: One-Command Docker Startup (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd CASSIE

# Run the startup script (Linux/Mac)
./scripts/start-cassie.sh

# Or on Windows PowerShell
.\scripts\start-cassie.ps1
```

**Access CASSIE:**
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **MinIO Console**: http://localhost:9011 (minioadmin/minioadmin)
- **Admin Panel**: http://localhost:8000/_cassie_admin_console_7f3a9b (admin/admin)

### Option 2: Manual Setup (Development)

#### Backend Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

---

## 📖 Detailed Setup Instructions

### System Requirements

**Minimum:**
- CPU: 4 cores
- RAM: 8GB
- Storage: 50GB free space

**Recommended:**
- CPU: 8+ cores
- RAM: 16GB+
- Storage: 200GB+

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd CASSIE
```

### Step 2: Environment Configuration

```bash
cp .env.example .env
```

### Step 3: Start Services

```bash
docker-compose up -d
docker-compose ps
```

### Step 4: Initialize Database (Optional)

```bash
cd backend/scripts
python3 setup_database.py
python3 seed_workflow.py
```

### Step 5: Verify Installation

```bash
curl http://localhost:8000/health
curl http://localhost:9010/minio/health/live
```

---

## 🧬 Available Bioinformatics Tools

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| **FastQC** | Read QC assessment | FASTQ | HTML report |
| **GenomeScope2** | Genome stats estimation | FASTQ k-mer | Genome size, heterozygosity |
| **SPAdes** | Short-read assembly | FASTQ | FASTA contigs |
| **metaSPAdes** | Metagenomic assembly | FASTQ | FASTA contigs |
| **HiFiasm** | Long-read assembly | FASTQ (PacBio) | FASTA contigs |
| **Verkko** | Phased long-read assembly | FASTQ (HiFi+ONT) | Phased FASTA |
| **QUAST** | Assembly quality evaluation | FASTA + FASTQ | HTML QC report |
| **BUSCO** | Gene completeness assessment | FASTA | Completeness metrics |
| **CAT** | Contig annotation | FASTA, GFF | Annotated FASTA |
| **Liftoff** | Gene annotation transfer | FASTA reference + target | GFF annotations |
| **Merqury** | Assembly evaluation using k-mers | FASTA + k-mer count | QV scores |

---

## 📁 Project Structure

```
CASSIE/
├── frontend/                    # React TypeScript UI
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── services/
│   │   └── styles/
│   └── package.json
│
├── backend/                     # FastAPI REST API
│   ├── api/
│   │   ├── main.py
│   │   ├── models/
│   │   ├── routes/
│   │   ├── services/
│   │   └── database/
│   ├── scripts/
│   └── requirements.txt
│
├── dockerized_tools/           # Bioinformatics tool containers
│   ├── busco/
│   ├── fastqc/
│   ├── hifiasm/
│   ├── spades/
│   ├── verkko/
│   └── buildtools.sh
│
├── kubernetes/                 # Kubernetes manifests
├── scripts/                    # Utility scripts
│   ├── start-cassie.sh
│   ├── stop-cassie.sh
│   └── check_health.py
│
├── docker-compose.yml
├── README.md
├── README_final.md
├── features.md
└── requirements.txt
```

---

## 🏢 Development & Deployment

### Development Workflow

```bash
# Terminal 1: Backend
cd backend
source venv/bin/activate
uvicorn api.main:app --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

### Production Deployment

#### Docker Compose

```bash
docker-compose -f docker-compose.yml up -d
```

#### Kubernetes

```bash
kubectl apply -f kubernetes/
```

#### Cloud Platforms

```bash
./scripts/deploy_cloud.sh --provider aws --region us-east-1
```

---

## 👨‍💼 Admin Panel

**URL**: http://localhost:8000/_cassie_admin_console_7f3a9b

**Default Credentials**:
- Username: `admin`
- Password: `admin`

⚠️ **Change immediately in production!**

### Features

1. **User Management** - Create, suspend, delete accounts
2. **System Monitoring** - Service health, database status
3. **Job Management** - View, pause, resume, cancel jobs
4. **Configuration** - System settings and tool management

---

## 🔐 Security

### Current Implementation
- ✅ JWT-based authentication
- ✅ Bcrypt password hashing
- ✅ Per-user data isolation
- ✅ HTTPS-ready

### Production Recommendations
1. Change all default credentials
2. Use Docker/Kubernetes secrets
3. Enable HTTPS with Let's Encrypt
4. Regular database backups
5. Restrict S3/MinIO bucket policies

---

## 📞 Support

- **Issues**: GitHub Issues
- **Email**: Contact maintainers

---

## 📄 License

MIT License - see LICENSE file

---

**Last Updated**: April 2026
**Maintained By**: CASSIE Development Team

For latest info, refer to README.md and source code.
