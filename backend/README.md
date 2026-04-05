# Backend

This folder contains the FastAPI API, job orchestration logic, and the registry-driven tool metadata used across CASSIE.

## Run Locally

```bash
python -m venv backend/venv
backend\venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

## One-Command Docker Startup

From the repo root on Windows PowerShell:

```powershell
.\scripts\start-cassie.ps1
```

That script:

- copies `.env.example` to `.env` if needed
- builds the bioinformatics tool images if they are missing
- starts PostgreSQL, MinIO, backend, and frontend with Docker Compose

The frontend is then available at `http://localhost:3000` and the backend at `http://localhost:8000`.

## Docker

Build the API image from the repo root:

```bash
docker build -f backend/Dockerfile -t cassie-backend .
docker run --rm -p 8000:8000 cassie-backend
```

Note:
If you want emulator-backed execution inside the container, mount the Docker socket and project workspace so the backend can still reach the tool definitions and Docker daemon.

## Execution Backends

Pipeline execution is controlled with:

```bash
EXECUTION_BACKEND=auto
```

Supported values:

- `auto`: prefer Kubernetes when `kubectl` can reach a cluster, otherwise fall back to the emulator
- `kubernetes`: require Kubernetes-backed execution
- `emulator`: require the local Docker emulator

Kubernetes-specific settings:

```bash
KUBERNETES_NAMESPACE=default
KUBERNETES_IMAGE_PULL_POLICY=IfNotPresent
KUBERNETES_JOB_TIMEOUT_SECONDS=3600
KUBERNETES_POLL_INTERVAL_SECONDS=5
KUBERNETES_MINIO_ENDPOINT=http://host.docker.internal:9000
```

## Key Directories

- `backend/api/routes`: HTTP endpoints.
- `backend/api/services`: job execution, workflow conversion, storage, and helper services.
- `backend/api/models`: Pydantic models shared by the routes and services.
- `backend/templates`: implementation templates that are not wired into production yet.

## Tool Registry

Tool metadata is now centralized in [`tool_registry.py`](/Users/Eren/Desktop/CASSIE/tool_registry.py).

That registry is used by:

- `backend/api/routes/tools.py`
- `backend/api/services/pipeline_analyzer.py`
- `backend/api/services/pipeline_converter.py`
- `backend/api/services/workflow_service.py`
- `emulation/nextflow_manager.py`

When you add a new bioinformatics tool, update the registry first, then add the matching Docker assets under [`dockerized_tools`](/Users/Eren/Desktop/CASSIE/dockerized_tools).

Each tool entry should define:

- stable `id`
- display `name`
- `type`
- `description`
- `node_labels`
- `input_requirements`
- `docker` metadata
- `kubernetes` hints
- `process_template`

## Adding A New Tool

1. Create the image and wrapper from the templates in [`dockerized_tools/templates/new-tool`](/Users/Eren/Desktop/CASSIE/dockerized_tools/templates/new-tool).
2. Add the tool entry to [`tool_registry.py`](/Users/Eren/Desktop/CASSIE/tool_registry.py).
3. Build the image with [`dockerized_tools/buildtools.sh`](/Users/Eren/Desktop/CASSIE/dockerized_tools/buildtools.sh) or your tool-specific build command.
4. If the tool needs a Kubernetes example, start from [`kubernetes/templates/tool-job-template.yaml`](/Users/Eren/Desktop/CASSIE/kubernetes/templates/tool-job-template.yaml).
5. If the tool produces new file types or special requirements, keep the registry as the single source of truth instead of hard-coding those rules elsewhere.

## Runtime Estimation Template

A starter ML template for runtime prediction lives at [`backend/templates/runtime_estimator_template.py`](/Users/Eren/Desktop/CASSIE/backend/templates/runtime_estimator_template.py).

It is designed for features such as:

- data size and read counts
- selected tool chain
- pod CPU / memory / ephemeral storage
- cloud and instance class metadata
- observed runtime in seconds
