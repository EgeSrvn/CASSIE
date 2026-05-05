# CASSIE: Cloud-based Assembly Streamlined Service Integration Engine

CASSIE is a cloud-native genomics workflow platform that combines a visual pipeline builder, job execution on Kubernetes, community-shared workflows, and integrated file storage into one web application. It abstracts distributed computation, containerized tools, and cloud infrastructure so researchers can focus on their science rather than DevOps.

---

## Table of Contents

- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Features](#features)
- [Available Bioinformatics Tools](#available-bioinformatics-tools)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Building Tool Images](#building-tool-images)
- [Execution Backends](#execution-backends)
- [Adding a New Tool](#adding-a-new-tool)
- [Kubernetes Execution Tracking](#kubernetes-execution-tracking)
- [EC2 and AWS S3 Deployment](#ec2-and-aws-s3-deployment)
- [Operational Checklist](#operational-checklist)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [Support](#support)

---

## Architecture

CASSIE follows a microservices architecture with clear separation between the UI, API, storage, and execution layers.

```
Frontend (React + Vite)
        |
Backend API (FastAPI)
        |
  ------+------+--------+
  |            |        |
PostgreSQL   MinIO/S3  Kubernetes
```

### Data Flow

1. User submits a job from the frontend.
2. The backend validates tool requirements and input availability.
3. The job is stored in PostgreSQL with a pending status.
4. The execution backend (Kubernetes or local Docker emulator) runs each tool stage sequentially inside an isolated container.
5. Outputs are written to MinIO or AWS S3.
6. The frontend polls job status and displays logs, stage progress, and output files.

---

## Technology Stack

### Frontend

| Technology   | Version | Purpose                      |
|--------------|---------|------------------------------|
| React        | 18.2.0  | UI framework                 |
| TypeScript   | 5.2.2   | Type-safe JavaScript         |
| Vite         | 5.0.8   | Build tool                   |
| ReactFlow    | 11.10.1 | Visual pipeline builder      |
| React Router | 6.20.0  | Client-side routing          |
| Axios        | 1.6.2   | HTTP client                  |

### Backend

| Technology  | Version | Purpose                      |
|-------------|---------|------------------------------|
| FastAPI     | 0.104.0 | Async REST framework         |
| Python      | 3.9+    | Core language                |
| SQLAlchemy  | Latest  | ORM                          |
| Pydantic    | 2.0.0   | Data validation              |
| Uvicorn     | 0.24.0  | ASGI server                  |
| psycopg2    | 2.9.0+  | PostgreSQL adapter           |
| Boto3       | 1.28.0+ | AWS S3 and MinIO client      |
| Docker SDK  | 7.0.0+  | Container management         |

### Infrastructure

| Technology      | Purpose                            |
|-----------------|------------------------------------|
| PostgreSQL 15+  | Relational database                |
| MinIO           | S3-compatible local storage        |
| Docker          | Tool containerization              |
| Docker Compose  | Local orchestration                |
| Kubernetes 1.24+| Production job execution           |

---

## Features

### User Authentication
- Registration with email verification, JWT session management, bcrypt password hashing, and per-user data isolation using dedicated S3 prefixes.

### Visual Pipeline Builder
- Drag-and-drop interface built with ReactFlow. Supports input, tool, checkpoint, and result nodes. Pipelines can be saved, cloned, renamed, and published to the community space.

### Job Management
- Create one-time tool jobs or pipeline-based jobs. Real-time stage status, live logs, retry from any failed or cancelled job, and output download as individual files or a ZIP archive.

### File Storage
- Upload FASTQ, FASTA, GFF, and other genomic formats. Hierarchical folder organization. Format hints per input block and manual format override.

### Runtime and Cost Estimation
- Deterministic heuristic model that combines per-tool baseline runtimes, a size-scaling factor, a pod input-copy overhead, a compression penalty for gzipped inputs, and a VM partition multiplier. Runtime and cost estimates do not call external prediction services.

### Community
- Forum for sharing workflows and results. Pipelines can be published to a community library where other users can browse, inspect, and clone them. Publishing does not share input files or job history.

### Admin Panel
- User management, system health monitoring, job queue management, and configuration.
- URL: `http://localhost:8000/_cassie_admin_console_7f3a9b`
- Default credentials: `admin` / `admin` — change immediately in production.

---

## Available Bioinformatics Tools

| Tool          | Purpose                              | Input                   | Output              |
|---------------|--------------------------------------|-------------------------|---------------------|
| FastQC        | Read quality control                 | FASTQ                   | HTML report         |
| GenomeScope2  | Genome size and heterozygosity       | FASTQ k-mer histogram   | Genome stats        |
| SPAdes        | Short-read assembly                  | FASTQ                   | FASTA contigs       |
| metaSPAdes    | Metagenomic assembly                 | FASTQ                   | FASTA contigs       |
| Hifiasm       | Long-read HiFi assembly              | FASTQ (PacBio HiFi)     | FASTA assembly      |
| Verkko        | Phased long-read assembly            | FASTQ (HiFi + ONT)      | Phased FASTA        |
| QUAST         | Assembly quality evaluation          | FASTA                   | HTML QC report      |
| BUSCO         | Gene completeness assessment         | FASTA                   | Completeness report |
| CAT           | Contig annotation                    | FASTA, GFF              | Annotated FASTA     |
| Liftoff       | Gene annotation transfer             | FASTA reference + target| GFF annotations     |
| Meryl         | K-mer database construction          | FASTQ                   | Meryl k-mer DB      |
| Merqury       | K-mer-based assembly evaluation      | FASTA + Meryl DB        | QV scores           |

---

## Prerequisites

- Docker and Docker Compose
- Git
- Linux, macOS, or Windows with WSL or PowerShell

For manual (non-Docker) setup:
- Python 3.9+
- Node.js 18+ and npm
- PostgreSQL 14+

---

## Quick Start

### One-Command Docker Startup

```bash
git clone <repository-url>
cd CASSIE

# Linux / macOS
./scripts/start-cassie.sh

# Windows PowerShell
.\scripts\start-cassie.ps1

# Windows batch
scripts\start-cassie.bat
```

The script copies `.env.example` to `.env` if needed, builds missing tool images, and starts PostgreSQL, MinIO, backend, and frontend with Docker Compose.

Access points after startup:

| Service         | URL                                                   |
|-----------------|-------------------------------------------------------|
| Frontend        | http://localhost:3000                                 |
| Backend API     | http://localhost:8000                                 |
| API docs        | http://localhost:8000/docs                            |
| MinIO console   | http://localhost:9011 (minioadmin / minioadmin)       |
| Admin panel     | http://localhost:8000/_cassie_admin_console_7f3a9b    |

### Manual Setup

#### Backend

```bash
python -m venv backend/venv
source backend/venv/bin/activate        # Windows: backend\venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

The backend automatically creates the database and initializes the schema on first startup.

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

#### Building Tool Images (first time)

```bash
cd dockerized_tools
bash buildtools.sh
```

The script skips images that already exist, so it is safe to run multiple times.

---

## Configuration

Copy `.env.example` to `.env` and set the values:

```env
# Database
DB_HOST=127.0.0.1
DB_PORT=5433
DB_USER=admin
DB_PASSWORD=replace-with-a-strong-database-password
DB_NAME=cassie_db

# Storage (MinIO for local dev; leave MINIO_ENDPOINT blank for AWS S3)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=replace-with-a-storage-access-key
MINIO_SECRET_KEY=replace-with-a-strong-storage-secret
MINIO_BUCKET_PREFIX=cassie

# Auth
JWT_SECRET_KEY=replace-with-a-long-random-secret

# Execution backend: auto | kubernetes | emulator
EXECUTION_BACKEND=auto
KUBERNETES_NAMESPACE=default
KUBERNETES_IMAGE_PULL_POLICY=IfNotPresent
KUBERNETES_JOB_TIMEOUT_SECONDS=0
KUBERNETES_POLL_INTERVAL_SECONDS=5
```

Frontend API URL override (optional):

```bash
VITE_API_URL=http://localhost:8000
```

---

## Building Tool Images

```bash
cd dockerized_tools
bash buildtools.sh
```

This builds the following images: FastQC, GenomeScope2, SPAdes, metaSPAdes, QUAST, Hifiasm, Verkko, Liftoff, CAT, BUSCO, Merqury.

Each tool lives in its own subdirectory under `dockerized_tools/`. Each directory contains a Dockerfile and a wrapper script that the execution backend calls.

Wrapper scripts must:
- accept positional inputs and an output directory
- validate that input files exist before starting the tool
- create or clean the output directory explicitly
- print logs to stdout/stderr
- exit non-zero on failure

---

## Execution Backends

The backend supports two execution modes controlled by `EXECUTION_BACKEND`:

| Value        | Behavior                                                            |
|--------------|---------------------------------------------------------------------|
| `auto`       | Use Kubernetes when `kubectl` can reach a cluster; fall back to emulator |
| `kubernetes` | Require Kubernetes; fail if unavailable                             |
| `emulator`   | Use the local Docker emulator                                       |

Kubernetes-specific variables:

```bash
KUBERNETES_NAMESPACE=default
KUBERNETES_IMAGE_PULL_POLICY=IfNotPresent
KUBERNETES_JOB_TIMEOUT_SECONDS=0
KUBERNETES_POLL_INTERVAL_SECONDS=5
KUBERNETES_MINIO_ENDPOINT=http://<linux-host-ip>:9010
```

---

## Adding a New Tool

1. Copy `dockerized_tools/templates/new-tool` to a new directory such as `dockerized_tools/my_tool`.
2. Update the Dockerfile and wrapper script with the real bioinformatics command.
3. Add a tool entry to `tool_registry.py`. Required fields: `id`, `name`, `type`, `description`, `node_labels`, `input_requirements`, `docker`, `kubernetes`, `process_template`.
4. Add the image to `dockerized_tools/buildtools.sh`.
5. If the tool needs a Kubernetes example job, adapt `kubernetes/templates/tool-job-template.yaml`.

The registry is the single source of truth for tool metadata. All backend services, the pipeline analyzer, and the frontend tool list read from it.

---

## Kubernetes Execution Tracking

CASSIE labels all Kubernetes Jobs it submits with:

- `cassie/job-id`
- `cassie/execution-id`
- `cassie/stage`
- `cassie/tool-id`

Track jobs in the terminal:

```bash
kubectl get jobs -n default
kubectl get pods -n default
kubectl logs job/<cassie-job-name> -n default

# Filter by job ID
kubectl get jobs -n default -l cassie/job-id=12
kubectl get pods -n default -l cassie/job-id=12
```

The CASSIE job details page also shows the execution backend, namespace, stage status, Kubernetes Job name, Pod name, and recent logs directly in the UI.

For a local graphical view, Docker Desktop's Kubernetes tab is the simplest option. For a separate in-cluster UI, prefer Headlamp over the deprecated Kubernetes Dashboard.

---

## EC2 and AWS S3 Deployment

This section covers deploying CASSIE on a single Amazon EC2 instance with AWS S3 as the storage backend.

### Architecture

- EC2 instance running Ubuntu 22.04 or 24.04
- Docker Compose for frontend, backend, and PostgreSQL containers
- Minikube on the same host for Kubernetes job execution
- AWS S3 for object storage (set `MINIO_ENDPOINT` to blank to activate native S3 mode)
- Application Load Balancer with ACM certificate for public HTTPS access

The frontend nginx container proxies `/api/` to the backend, so only port 3000 needs to be reachable from the ALB. The backend, PostgreSQL, and MinIO-style storage ports stay private.

### Recommended EC2 Size

| Use case        | vCPU | RAM     | Storage     |
|-----------------|------|---------|-------------|
| Demo / testing  | 4    | 16 GiB  | 100 GiB gp3 |
| Starting point  | 8    | 32 GiB  | 200+ GiB gp3|

### Step 1: Launch EC2 Instance

- Ubuntu Server 22.04 LTS or 24.04 LTS, x86_64
- `t3a.2xlarge` or larger
- 200 GiB gp3 root volume
- Attach an Elastic IP

Security groups:

| Group | Rule                                |
|-------|-------------------------------------|
| ALB   | 80/tcp and 443/tcp from 0.0.0.0/0  |
| EC2   | 22/tcp from your IP; 3000/tcp from ALB SG only |

### Step 2: Install Host Dependencies

```bash
sudo apt update
sudo apt install -y ca-certificates curl git unzip jq docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker

curl -fsSL https://dl.k8s.io/release/stable.txt -o /tmp/kubectl-version
curl -fsSL "https://dl.k8s.io/release/$(cat /tmp/kubectl-version)/bin/linux/amd64/kubectl" -o kubectl
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
rm -f minikube-linux-amd64
```

### Step 3: Clone and Configure

```bash
cd /opt
sudo git clone <YOUR_REPOSITORY_URL> CASSIE
sudo chown -R $USER:$USER /opt/CASSIE
cd /opt/CASSIE
cp .env.example .env
```

Edit `.env` with production values:

```env
DB_USER=cassie
DB_PASSWORD=CHANGE_THIS_DB_PASSWORD
DB_NAME=cassie_db

MINIO_ENDPOINT=
MINIO_PUBLIC_ENDPOINT=
MINIO_ACCESS_KEY=YOUR_AWS_ACCESS_KEY_ID
MINIO_SECRET_KEY=YOUR_AWS_SECRET_ACCESS_KEY
MINIO_REGION=us-east-2
MINIO_BUCKET_PREFIX=cassie-prod-123456789012

JWT_SECRET_KEY=CHANGE_THIS_TO_A_LONG_RANDOM_SECRET
CORS_ORIGINS=https://cassie.example.com

EXECUTION_BACKEND=kubernetes
KUBERNETES_NAMESPACE=default
KUBERNETES_IMAGE_PULL_POLICY=IfNotPresent
KUBERNETES_JOB_TIMEOUT_SECONDS=0
KUBERNETES_POLL_INTERVAL_SECONDS=5

ENABLE_LOCAL_INFRA_BOOTSTRAP=false

VITE_API_URL=
```

`MINIO_ENDPOINT` must be blank for native AWS S3 mode.

### Step 4: IAM Permissions for S3

The IAM principal used by the backend needs the following policy (replace `cassie-prod-123456789012` with your actual globally unique bucket name):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListAllBucketsForStartupCheck",
      "Effect": "Allow",
      "Action": ["s3:ListAllMyBuckets"],
      "Resource": "*"
    },
    {
      "Sid": "ManageCassieBucket",
      "Effect": "Allow",
      "Action": ["s3:CreateBucket", "s3:ListBucket", "s3:GetBucketLocation", "s3:HeadBucket"],
      "Resource": ["arn:aws:s3:::cassie-prod-123456789012"]
    },
    {
      "Sid": "ManageCassieObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": ["arn:aws:s3:::cassie-prod-123456789012/users/*"]
    }
  ]
}
```

### Step 5: Start Minikube

```bash
minikube start --driver=docker --cpus=4 --memory=7800mb --disk-size=40g
kubectl config use-context minikube
```

### Step 6: Prepare Kubeconfig for the Backend Container

```bash
mkdir -p /opt/CASSIE/.cassie/kube
kubectl config view --raw --minify --flatten > /opt/CASSIE/.cassie/kube/config

API_PORT=$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}' | sed -E 's#.*:([0-9]+)$#\1#')
sed -i -E "s#server: https://(127\.0\.0\.1|localhost):[0-9]+#server: https://host.docker.internal:${API_PORT}#g" \
    /opt/CASSIE/.cassie/kube/config

grep -q 'tls-server-name:' /opt/CASSIE/.cassie/kube/config || \
sed -i "/server: https:\/\/host\.docker\.internal:${API_PORT}/a\\    tls-server-name: localhost" \
    /opt/CASSIE/.cassie/kube/config
```

Add to `.env`:

```env
KUBE_CONFIG_DIR=/opt/CASSIE/.cassie/kube
KUBERNETES_NO_PROXY=localhost,127.0.0.1,host.docker.internal,kubernetes.docker.internal
```

### Step 7: Build and Load Tool Images

```bash
cd /opt/CASSIE/dockerized_tools && bash buildtools.sh && cd /opt/CASSIE

minikube image load fastqc:0.12.1 genomescope2 spades metaspades quast \
    hifiasm verkko liftoff cat-tool busco merqury
```

### Step 8: Production Compose File

Do not use `docker-compose.yml` directly for EC2 + S3 because it includes MinIO. Create `docker-compose.ec2-s3.yml`:

```yaml
services:
  postgres:
    image: postgres:15
    container_name: cassie-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: postgres
    volumes:
      - cassie_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d postgres"]
      interval: 10s
      timeout: 5s
      retries: 10
    networks:
      - cassie_internal

  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: cassie-backend
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DB_HOST: postgres
      DB_PORT: 5432
      DB_USER: ${DB_USER}
      DB_PASSWORD: ${DB_PASSWORD}
      DB_NAME: ${DB_NAME}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT}
      MINIO_PUBLIC_ENDPOINT: ${MINIO_PUBLIC_ENDPOINT}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_REGION: ${MINIO_REGION}
      MINIO_BUCKET_PREFIX: ${MINIO_BUCKET_PREFIX}
      CORS_ORIGINS: ${CORS_ORIGINS}
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      EXECUTION_BACKEND: ${EXECUTION_BACKEND}
      KUBERNETES_NAMESPACE: ${KUBERNETES_NAMESPACE}
      KUBERNETES_IMAGE_PULL_POLICY: ${KUBERNETES_IMAGE_PULL_POLICY}
      KUBERNETES_JOB_TIMEOUT_SECONDS: ${KUBERNETES_JOB_TIMEOUT_SECONDS}
      KUBERNETES_POLL_INTERVAL_SECONDS: ${KUBERNETES_POLL_INTERVAL_SECONDS}
      KUBECONFIG: /root/.kube/config
      ENABLE_LOCAL_INFRA_BOOTSTRAP: "false"
      NO_PROXY: ${KUBERNETES_NO_PROXY}
      no_proxy: ${KUBERNETES_NO_PROXY}
    volumes:
      - ${DOCKER_SOCK_PATH:-/var/run/docker.sock}:/var/run/docker.sock
      - ${KUBE_CONFIG_DIR}:/root/.kube:ro
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      - cassie_internal

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      args:
        VITE_API_URL: ${VITE_API_URL}
        VITE_GOOGLE_DRIVE_CLIENT_ID: ${VITE_GOOGLE_DRIVE_CLIENT_ID}
        VITE_GOOGLE_DRIVE_API_KEY: ${VITE_GOOGLE_DRIVE_API_KEY}
        VITE_GOOGLE_DRIVE_APP_ID: ${VITE_GOOGLE_DRIVE_APP_ID}
    container_name: cassie-frontend
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_started
    ports:
      - "3000:80"
    networks:
      - cassie_internal

volumes:
  cassie_postgres_data:

networks:
  cassie_internal:
```

### Step 9: Start the Stack

```bash
cd /opt/CASSIE
docker compose -f docker-compose.ec2-s3.yml up -d --build
```

### Step 10: Publish Over HTTPS

Recommended: ALB + ACM + Route 53.

1. Request an ACM certificate for your public domain.
2. Create an Application Load Balancer with HTTP (80) redirecting to HTTPS (443) using the ACM certificate.
3. Create a target group: HTTP, port 3000, instance target type.
4. Register the EC2 instance in the target group.
5. Create a Route 53 alias record pointing your domain to the ALB.

Simpler alternative: install nginx on the host, proxy port 443 to 127.0.0.1:3000, and use Let's Encrypt for TLS.

### Systemd Service

To auto-restart CASSIE after reboots, create `/etc/systemd/system/cassie.service`:

```ini
[Unit]
Description=CASSIE stack
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/CASSIE
ExecStart=/usr/bin/docker compose -f /opt/CASSIE/docker-compose.ec2-s3.yml up -d --build
ExecStop=/usr/bin/docker compose -f /opt/CASSIE/docker-compose.ec2-s3.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable cassie
sudo systemctl start cassie
```

Start Minikube separately before the app on each fresh boot. Add a second systemd unit for Minikube if full automation is required.

### Updating CASSIE

```bash
cd /opt/CASSIE
git pull
cd dockerized_tools && bash buildtools.sh && cd ..
minikube image load fastqc:0.12.1 genomescope2 spades metaspades quast \
    hifiasm verkko liftoff cat-tool busco merqury
docker compose -f docker-compose.ec2-s3.yml up -d --build
```

---

## Operational Checklist

Before calling a deployment complete:

1. `docker compose ps` — all services healthy
2. `minikube status` — cluster running
3. `kubectl get pods -A` — no crash loops
4. `curl http://127.0.0.1:8000/health` — backend responds
5. Open the frontend URL in a browser
6. Register a user and log in
7. Upload a file to the storage library
8. Create a job and confirm it reaches PENDING status
9. Run a job end-to-end and confirm output files appear
10. Download an output file

---

## Troubleshooting

### Database connection error

```
psycopg2.OperationalError: could not connect to server
```

- Confirm PostgreSQL is running: `sudo systemctl status postgresql` (Linux) or check Docker Desktop.
- Verify the port in `.env` (CASSIE uses 5433 by default for local dev, 5432 inside Docker Compose).

### Port already in use

```
Address already in use
```

- Find the process: `lsof -i :8000` (Linux/macOS) or `netstat -ano | findstr :8000` (Windows).
- Kill it or change the port: `uvicorn backend.api.main:app --port 8001`.

### Docker daemon unreachable

- Start Docker Desktop.
- On Linux: `sudo systemctl start docker`.

### npm install fails

- Clear cache: `npm cache clean --force`.
- Delete `node_modules` and `package-lock.json`, then `npm install`.
- Use `npm install --legacy-peer-deps` if peer dependency conflicts appear.

### Python module not found

```
ModuleNotFoundError: No module named 'backend'
```

- Activate the virtual environment before running uvicorn.
- Run uvicorn from the repository root, not from inside the `backend` directory.

### Backend still connects to MinIO instead of S3

- Confirm `MINIO_ENDPOINT` is blank in `.env`.
- Confirm you are running `docker-compose.ec2-s3.yml`, not `docker-compose.yml`.

### Shared S3 bucket fails to create

- Verify the bucket name is globally unique.
- Confirm the IAM policy includes `s3:CreateBucket` and the correct bucket ARN.

### App works locally on EC2 but not publicly

- ALB target group must point to port 3000.
- EC2 security group must allow 3000 from the ALB security group.
- Route 53 record must point to the ALB.
- ACM certificate must be issued, not pending.

### Jobs do not run

- `minikube status` — confirm the cluster is up.
- `kubectl get pods -A` — look for failed or crash-looping pods.
- Verify all tool images were built and loaded into Minikube.
- Confirm the backend container can read `/root/.kube/config`.

---

## Security

Current implementation:
- JWT-based authentication
- Bcrypt password hashing
- Per-user data isolation via S3 prefixes
- HTTPS-ready via nginx proxy

Production recommendations:
- Change all default credentials immediately (DB password, JWT secret, admin panel).
- Use Docker or Kubernetes secrets for sensitive values; do not commit `.env` to version control.
- Enable HTTPS with a valid certificate (ACM on AWS or Let's Encrypt).
- Restrict S3 bucket policies to the minimum required.
- Keep backend and database ports private; expose only the frontend port through the load balancer.
- Rotate AWS access keys regularly if using static credentials.
- Limit SSH access to known IP addresses.

---

## Support

Contact the CASSIE team at cassiecloudcnoreply@gmail.com.

Include your job ID, the page where the problem occurred, and a short description of what happened so the issue can be investigated quickly.

For collaboration requests (benchmarking, teaching use cases, workflow evaluation), include your organism, sequencing data type, and expected project scale.

---

**Maintained by the CASSIE Development Team**
