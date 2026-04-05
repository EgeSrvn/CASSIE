# Kubernetes

This folder contains local Kubernetes experiments, image-push helpers, and job templates for running CASSIE tools in a cluster.

## Current Contents

- `test/`: local-registry and Docker Desktop oriented experiments.
- `templates/tool-job-template.yaml`: a minimal Job template for new tools.

## CASSIE Execution Backend

CASSIE can now execute pipelines through Kubernetes instead of the local Docker emulator.

Relevant environment variables:

- `EXECUTION_BACKEND=auto|kubernetes|emulator`
- `KUBERNETES_NAMESPACE=default`
- `KUBERNETES_IMAGE_PULL_POLICY=IfNotPresent`
- `KUBERNETES_JOB_TIMEOUT_SECONDS=3600`
- `KUBERNETES_POLL_INTERVAL_SECONDS=5`
- `KUBERNETES_MINIO_ENDPOINT=http://host.docker.internal:9000`

Recommended local setup:

1. Enable Kubernetes in Docker Desktop.
2. Make sure `kubectl config use-context docker-desktop` points to the Docker Desktop cluster.
3. Run [`scripts/start-cassie.ps1`](/C:/Users/Eren/Desktop/CASSIE/scripts/start-cassie.ps1) once to build the tool images and start the stack.
4. Set `EXECUTION_BACKEND=kubernetes` or leave `auto` to prefer Kubernetes when available.

## Tracking Pipeline Runs

You can track CASSIE pipeline stages in three ways:

1. In the CASSIE UI:
   Job Details now includes an `Execution Tracking` section with the backend, namespace, stage status, Kubernetes Job name, Pod name, and recent logs.
2. In Docker Desktop:
   Open the Kubernetes view and watch the namespace where CASSIE submits Jobs.
3. In the terminal:

```powershell
kubectl config use-context docker-desktop
kubectl get jobs -n default
kubectl get pods -n default
kubectl logs job/<cassie-job-name> -n default
```

CASSIE labels Jobs with:

- `cassie/job-id`
- `cassie/execution-id`
- `cassie/stage`
- `cassie/tool-id`

Example:

```powershell
kubectl get jobs -n default -l cassie/job-id=12
kubectl get pods -n default -l cassie/job-id=12
```

## Dashboard Notes

Docker Desktop already provides a Kubernetes view in its dashboard, which is the easiest local option.

If you want a separate in-cluster web UI, Kubernetes Dashboard exists but is deprecated upstream. For new installs, prefer Headlamp or stick with the Docker Desktop Kubernetes view plus `kubectl logs`.

## Recommended Workflow

1. Build the tool image under [`dockerized_tools`](/Users/Eren/Desktop/CASSIE/dockerized_tools).
2. Push it to a registry that your cluster can pull from.
3. Start from [`templates/tool-job-template.yaml`](/Users/Eren/Desktop/CASSIE/kubernetes/templates/tool-job-template.yaml).
4. Mount a shared input/output directory or object storage path.
5. Keep the tool command and expected outputs aligned with the entry you added in [`tool_registry.py`](/Users/Eren/Desktop/CASSIE/tool_registry.py).

## Local Testing Notes

The scripts under `kubernetes/test` are examples, not production controllers. They are useful for validating:

- image push to a local registry
- simple hostPath mounts
- generated Nextflow-on-Kubernetes experiments

They should stay import-safe, so test helpers should not automatically launch jobs just because a file was imported.
