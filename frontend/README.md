# Frontend

React + TypeScript + Vite UI for job creation, pipeline building, and execution monitoring.

## Run Locally

```bash
cd frontend
npm install
npm run dev
```

The default dev URL is `http://localhost:3000`.

## Build

```bash
cd frontend
npm run build
```

Notes:

- `tsc` currently type-checks cleanly in the repo.
- In restricted sandbox environments, Vite or esbuild may fail to spawn worker processes even when the code is valid.

## Docker

Build from the repository root:

```bash
docker build -f frontend/Dockerfile -t cassie-frontend .
docker run --rm -p 3000:80 cassie-frontend
```

## Important Files

- `src/pages/CreateJob.tsx`: job creation flow.
- `src/pages/PipelineBuilder.tsx`: React Flow builder for custom pipelines.
- `src/services/toolService.ts`: loads registry-backed tool metadata from the backend.
- `src/services/apiClient.ts`: Axios client and auth handling.

## Environment

You can override the API base URL with:

```bash
VITE_API_URL=http://localhost:8000
```

## Tool Metadata Flow

The UI expects tool definitions from the backend route:

- `GET /api/tools`
- `GET /api/tools/requirements`

Those routes now read from the shared registry in [`tool_registry.py`](/Users/Eren/Desktop/CASSIE/tool_registry.py), which means new tools appear in the frontend without a separate hard-coded list.
