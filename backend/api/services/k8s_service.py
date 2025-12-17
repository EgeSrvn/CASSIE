import os
import time
from kubernetes import client, config
from backend.api.models.job_model import Job

# Configure K8s Client
try:
    config.load_incluster_config() # Works when running inside the cluster
except:
    try:
        config.load_kube_config() # Fallback for local dev
    except:
        print("Warning: Could not load K8s config")

batch_api = client.BatchV1Api()
NAMESPACE = os.getenv("KUBE_NAMESPACE", "default")
PVC_NAME = "cassie-pvc"
MOUNT_PATH = "/workspace"

def create_nextflow_job(job_record: Job, pipeline_script: str):
    """
    1. Writes the pipeline script to the shared PVC (via local mount).
    2. Submits a K8s Job that runs Nextflow.
    """
    
    # 1. Write script to shared storage
    # Since the backend mounts the PVC at MOUNT_PATH, we write directly.
    job_dir = os.path.join(MOUNT_PATH, f"job_{job_record.id}")
    os.makedirs(job_dir, exist_ok=True)
    
    script_path = os.path.join(job_dir, "main.nf")
    with open(script_path, "w") as f:
        f.write(pipeline_script)

    # 2. Create nextflow.config
    # Crucial: Tells Nextflow to use K8s and the Shared PVC
    config_content = f"""
    process {{
        executor = 'k8s'
        container = 'nextflow/nextflow:23.10.0' 
    }}
    k8s {{
        namespace = '{NAMESPACE}'
        serviceAccount = 'nextflow-sa'
        storageClaimName = '{PVC_NAME}'
        storageMountPath = '{MOUNT_PATH}'
        launchDir = '{job_dir}'
    }}
    """
    config_path = os.path.join(job_dir, "nextflow.config")
    with open(config_path, "w") as f:
        f.write(config_content)

    # 3. Define the K8s Job (The Driver Pod)
    job_name = f"nf-driver-{job_record.id}-{int(time.time())}"
    
    container = client.V1Container(
        name="nextflow-runner",
        image="nextflow/nextflow:23.10.0",
        # Run Nextflow using the config and script we just wrote
        command=["nextflow", "run", "main.nf", "-c", "nextflow.config"],
        working_dir=job_dir,
        volume_mounts=[
            client.V1VolumeMount(name="workdir", mount_path=MOUNT_PATH)
        ],
        image_pull_policy="IfNotPresent"
    )

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": "nextflow-driver", "job_id": str(job_record.id)}),
        spec=client.V1PodSpec(
            service_account_name="nextflow-sa",
            restart_policy="Never",
            containers=[container],
            volumes=[
                client.V1Volume(
                    name="workdir",
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=PVC_NAME)
                )
            ]
        )
    )

    job_spec = client.V1JobSpec(
        template=template,
        backoff_limit=0,
        ttl_seconds_after_finished=3600 # Auto-cleanup after 1 hour
    )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=job_name),
        spec=job_spec
    )

    # 4. Submit
    print(f"Submitting Job {job_name}...")
    batch_api.create_namespaced_job(namespace=NAMESPACE, body=job)
    return job_name
