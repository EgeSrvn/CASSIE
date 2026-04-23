# CASSIE on EC2 with AWS S3

This document is a repo-specific deployment runbook for running **CASSIE fully on an Amazon EC2 instance** and publishing it on the web.

This version is written for **AWS S3-backed storage**, not MinIO.

## Goal

Deploy CASSIE with:

- `frontend` container
- `backend` container
- `postgres` container
- `minikube` on the EC2 host for the Kubernetes execution backend
- **AWS S3** for object storage
- public website access over HTTPS

## Important Repo-Specific Facts

These points are based on the current codebase and matter for production:

1. The frontend container already proxies `/api/` requests to the backend.
   File: [frontend/nginx.conf](/home/ege/Desktop/CS491/CASSIE/frontend/nginx.conf:1)

   This means the public entrypoint can be just the frontend service. You do **not** need to expose the backend directly to the internet for normal app usage.

2. The storage client supports **AWS S3** when `MINIO_ENDPOINT` is left empty/unset.
   File: [backend/api/services/minio_client.py](/home/ege/Desktop/CS491/CASSIE/backend/api/services/minio_client.py:1)

3. The current default `docker-compose.yml` is local/dev oriented and includes a `minio` service.
   File: [docker-compose.yml](/home/ege/Desktop/CS491/CASSIE/docker-compose.yml:1)

   For EC2 + S3, do **not** use that file directly as your production compose manifest.

4. CASSIE creates **per-user buckets** with this pattern:

   - `${MINIO_BUCKET_PREFIX}-user-{user_id}`

   File: [backend/api/services/minio_client.py](/home/ege/Desktop/CS491/CASSIE/backend/api/services/minio_client.py:111)

   On AWS S3, bucket names are globally unique, so choose a globally unique prefix such as:

   - `cassie-prod-123456789012`

5. The storage client currently expects explicit `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` style credentials.
   In practice, for AWS S3, these should be your AWS access key and secret key.

6. The current AWS bucket-creation path is safest outside `us-east-1`.
   The code creates AWS buckets with `CreateBucketConfiguration`, so use a region like:

   - `us-east-2`
   - `eu-west-1`
   - `eu-central-1`

7. Do **not** use [scripts/start-cassie.sh](/home/ege/Desktop/CS491/CASSIE/scripts/start-cassie.sh:1) as your normal EC2 start command.
   It resets Minikube and is destructive for an existing cluster.

## Recommended Architecture

### Inside EC2

- Ubuntu 22.04 or 24.04
- Docker Engine + Docker Compose
- Minikube
- Kubectl
- CASSIE source tree under `/opt/CASSIE`

### Public Access

Recommended AWS-native publishing path:

- `cassie.example.com` -> **AWS Application Load Balancer**
- ALB forwards to EC2 instance port `3000`
- the frontend nginx serves the app and proxies `/api/` to backend internally

### Storage

- AWS S3 replaces MinIO entirely
- the backend stores files in S3
- generated ZIP download links also come from S3 presigned URLs

## Recommended EC2 Size

For a realistic single-instance deployment:

- **Minimum for demo/testing:** `4 vCPU`, `16 GiB RAM`, `100 GiB gp3`
- **Recommended starting point:** `8 vCPU`, `32 GiB RAM`, `200+ GiB gp3`

Why:

- Minikube itself needs a meaningful share of CPU/RAM
- backend, frontend, Postgres, and Docker all run on the same instance
- genomics tools are heavy

## AWS Resources To Create

Create these first:

1. An EC2 instance
2. An Elastic IP
3. An S3-backed IAM principal for CASSIE
4. A domain name
5. Optionally Route 53 hosted zone
6. An ACM certificate for your public hostname
7. An Application Load Balancer

## Security Groups

### ALB Security Group

Allow inbound:

- `80/tcp` from `0.0.0.0/0`
- `443/tcp` from `0.0.0.0/0`

### EC2 Security Group

Allow inbound:

- `22/tcp` from **your IP only**
- `3000/tcp` from the **ALB security group only**

Do **not** expose these publicly:

- `8000` backend
- `5432` Postgres
- `9010` MinIO-style storage port (not used in S3 deployment)
- `9011` MinIO console (not used in S3 deployment)

## IAM Permissions For S3

Because CASSIE creates per-user buckets dynamically, the IAM principal used by the backend must be able to:

- list buckets
- create buckets
- read bucket location
- list objects in user buckets
- upload/download/delete objects in user buckets

Example policy skeleton:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListAllBucketsForStartupCheck",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ManageCassieBuckets",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:HeadBucket"
      ],
      "Resource": [
        "arn:aws:s3:::cassie-prod-123456789012-user-*"
      ]
    },
    {
      "Sid": "ManageCassieObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::cassie-prod-123456789012-user-*/*"
      ]
    }
  ]
}
```

Replace `cassie-prod-123456789012` with your real globally unique prefix.

## Step 1: Launch The EC2 Instance

Recommended:

- Ubuntu Server 22.04 LTS or 24.04 LTS
- x86_64
- `t3a.2xlarge` or larger for a serious test deployment
- root EBS volume: `200 GiB gp3`

Attach:

- Elastic IP
- EC2 security group

## Step 2: Connect To EC2

You can use SSH or EC2 Instance Connect.

Official AWS references:

- EC2 Instance Connect:
  https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-linux-inst-eic.html
- EC2 security groups:
  https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html

## Step 3: Install Host Dependencies

Run on the EC2 instance:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git unzip jq docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker

curl -fsSL https://dl.k8s.io/release/stable.txt -o /tmp/kubectl-version
curl -fsSL "https://dl.k8s.io/release/$(cat /tmp/kubectl-version)/bin/linux/amd64/kubectl" -o kubectl
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
rm -f minikube-linux-amd64
```

Verify:

```bash
docker --version
docker compose version
kubectl version --client
minikube version
```

## Step 4: Clone The Repository

```bash
cd /opt
sudo git clone <YOUR_REPOSITORY_URL> CASSIE
sudo chown -R $USER:$USER /opt/CASSIE
cd /opt/CASSIE
```

## Step 5: Create The Production Environment File

Start from the example:

```bash
cp .env.example .env
```

Use values similar to the following:

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

EMAIL_ENABLED=true
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USERNAME=YOUR_SMTP_USERNAME
EMAIL_PASSWORD=YOUR_SMTP_PASSWORD
EMAIL_FROM_ADDRESS=no-reply@example.com
EMAIL_FROM_NAME=CASSIE
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false

EXECUTION_BACKEND=kubernetes
KUBERNETES_NAMESPACE=default
KUBERNETES_IMAGE_PULL_POLICY=IfNotPresent
KUBERNETES_JOB_TIMEOUT_SECONDS=0
KUBERNETES_POLL_INTERVAL_SECONDS=5

ENABLE_LOCAL_INFRA_BOOTSTRAP=false

VITE_API_URL=
VITE_GOOGLE_DRIVE_CLIENT_ID=YOUR_GOOGLE_DRIVE_CLIENT_ID
VITE_GOOGLE_DRIVE_API_KEY=YOUR_GOOGLE_DRIVE_API_KEY
VITE_GOOGLE_DRIVE_APP_ID=YOUR_GOOGLE_DRIVE_APP_ID

DOCKER_SOCK_PATH=/var/run/docker.sock
```

Notes:

- `MINIO_ENDPOINT` must be blank for native AWS S3 mode
- `MINIO_PUBLIC_ENDPOINT` should also be blank for native S3 mode
- `VITE_API_URL` should stay blank if you use the frontend nginx proxy
- `CORS_ORIGINS` should match your public site origin

## Step 6: Start Minikube

```bash
minikube start --driver=docker --cpus=4 --memory=7800mb --disk-size=40g
kubectl config use-context minikube
```

Verify:

```bash
minikube status
kubectl get nodes
```

## Step 7: Prepare Kubeconfig For The Backend Container

The backend container expects a kubeconfig mounted inside it.

```bash
mkdir -p /opt/CASSIE/.cassie/kube
kubectl config view --raw --minify --flatten > /opt/CASSIE/.cassie/kube/config

API_PORT=$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}' | sed -E 's#.*:([0-9]+)$#\\1#')
sed -i -E "s#server: https://(127\\.0\\.0\\.1|localhost):[0-9]+#server: https://host.docker.internal:${API_PORT}#g" /opt/CASSIE/.cassie/kube/config

grep -q 'tls-server-name:' /opt/CASSIE/.cassie/kube/config || \
sed -i "/server: https:\\/\\/host\\.docker\\.internal:${API_PORT}/a\\    tls-server-name: localhost" /opt/CASSIE/.cassie/kube/config
```

Then add these values to `.env` if they are not already set:

```env
KUBE_CONFIG_DIR=/opt/CASSIE/.cassie/kube
KUBERNETES_NO_PROXY=localhost,127.0.0.1,host.docker.internal,kubernetes.docker.internal
```

## Step 8: Build All Tool Images

This repository already has a build script for the full tool set.

```bash
cd /opt/CASSIE/dockerized_tools
bash buildtools.sh
cd /opt/CASSIE
```

This currently builds:

- FastQC
- GenomeScope2
- SPAdes
- metaSPAdes
- QUAST
- Hifiasm
- Verkko
- Liftoff
- CAT
- BUSCO
- Merqury

## Step 9: Load Tool Images Into Minikube

```bash
minikube image load fastqc:0.12.1
minikube image load genomescope2
minikube image load spades
minikube image load metaspades
minikube image load quast
minikube image load hifiasm
minikube image load verkko
minikube image load liftoff
minikube image load cat-tool
minikube image load busco
minikube image load merqury
```

## Step 10: Create A Production Compose File For EC2 + S3

Do **not** use the stock [docker-compose.yml](/home/ege/Desktop/CS491/CASSIE/docker-compose.yml:1) directly, because it includes MinIO.

Create `/opt/CASSIE/docker-compose.ec2-s3.yml` with this content:

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
      - ./data/runtime_training:/app/training_data
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

## Step 11: Start CASSIE

```bash
cd /opt/CASSIE
docker compose -f docker-compose.ec2-s3.yml up -d --build
```

Verify:

```bash
docker compose -f docker-compose.ec2-s3.yml ps
curl http://127.0.0.1:3000
curl http://127.0.0.1:8000/health
kubectl get pods -A
```

## Step 12: Publish CASSIE On The Web

### Recommended Method: ALB + ACM + Route 53

This is the cleanest AWS-native approach.

### Create An ACM Certificate

Request a public certificate for:

- `cassie.example.com`

Reference:

- https://docs.aws.amazon.com/acm/latest/userguide/acm-public-certificates.html

### Create An Application Load Balancer

Create one ALB with:

- listener `80` -> redirect to HTTPS
- listener `443` -> use the ACM certificate

Reference:

- https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-listeners.html

### Create One Target Group

Target group:

- protocol: HTTP
- port: `3000`
- target type: instance
- health check path: `/`

Register your EC2 instance in that target group.

### Add DNS

If you use Route 53:

- create an alias record:
  - `cassie.example.com` -> ALB

References:

- https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/routing-to-elb-load-balancer.html
- https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resource-record-sets-choosing-alias-non-alias.html

### Why Only Port 3000 Is Public

The frontend nginx already proxies:

- `/api/` -> backend container

So the ALB only needs to reach:

- EC2 instance port `3000`

Backend and Postgres remain private.

## Optional Simpler Publishing Method

If you do not want ALB yet, you can:

- point DNS A record directly to the EC2 Elastic IP
- install nginx on the host
- proxy `443` -> `127.0.0.1:3000`
- use Let’s Encrypt for TLS

This is simpler but less AWS-native and less flexible than ALB + ACM.

## Suggested systemd Service

If you want CASSIE to restart automatically after reboots, create a systemd unit on the EC2 host.

Example:

`/etc/systemd/system/cassie.service`

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

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cassie
sudo systemctl start cassie
```

Important:

- start Minikube separately before the app after a fresh reboot
- if you want full automation, add a second systemd unit for Minikube

## Operational Checklist

Before calling the deployment complete, verify:

1. `docker compose -f docker-compose.ec2-s3.yml ps`
2. `minikube status`
3. `kubectl get pods -A`
4. `curl http://127.0.0.1:8000/health`
5. open `https://cassie.example.com`
6. register a user
7. log in
8. upload a file
9. create a job
10. confirm output files land in S3

## Backups

Back up:

- Postgres Docker volume: `cassie_postgres_data`
- `/opt/CASSIE/.env`
- `/opt/CASSIE/.cassie/kube/config`
- your S3 data

## Updating CASSIE

```bash
cd /opt/CASSIE
git pull
cd dockerized_tools && bash buildtools.sh && cd ..
minikube image load fastqc:0.12.1 genomescope2 spades metaspades quast hifiasm verkko liftoff cat-tool busco merqury
docker compose -f docker-compose.ec2-s3.yml up -d --build
```

## Troubleshooting

### Problem: Backend still tries to use MinIO

Check:

- `MINIO_ENDPOINT` is blank in `.env`
- you are running `docker-compose.ec2-s3.yml`, not the stock `docker-compose.yml`

### Problem: S3 buckets fail to create

Check:

- bucket prefix is globally unique
- IAM policy allows `s3:CreateBucket`
- region is not `us-east-1`

### Problem: App works locally on EC2 but not publicly

Check:

- ALB target group points to port `3000`
- EC2 security group allows `3000` from ALB SG
- Route 53 record points to the ALB
- ACM certificate is issued, not pending

### Problem: Jobs do not run

Check:

- `minikube status`
- `kubectl get pods -A`
- tool images were built and loaded
- backend container sees `/root/.kube/config`

### Problem: ZIP output downloads fail

Check:

- backend can generate presigned S3 URLs
- the IAM principal can `GetObject`
- generated archives are being written to S3

## Security Recommendations

- Change all default secrets:
  - DB password
  - JWT secret
  - admin credentials if used
  - SMTP credentials
- Keep backend private
- Keep Postgres private
- Limit SSH to your IP
- Rotate AWS access keys if you use static credentials

## Final Recommendation

For this repository as it exists today, the best production path is:

1. EC2 host
2. Docker Compose for frontend/backend/postgres
3. Minikube on the same EC2 host for job execution
4. AWS S3 for storage
5. ALB + ACM + Route 53 for public publishing

That is the cleanest way to run CASSIE fully on EC2 while ensuring storage uses **AWS S3 instead of MinIO**.
