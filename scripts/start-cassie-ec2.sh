#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE_FILE="${ROOT_DIR}/docker-compose.ec2-s3.yml"

load_env_file() {
  local env_file="${ROOT_DIR}/.env"
  if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
  fi
}

get_env_value_or_default() {
  local name="$1"
  local default_value="$2"
  local value="${!name:-}"

  if [[ -z "${value}" ]]; then
    printf '%s\n' "${default_value}"
    return
  fi

  printf '%s\n' "${value}"
}

require_command() {
  local name="$1"
  local install_hint="$2"

  if ! command -v "${name}" >/dev/null 2>&1; then
    printf '%s is required but was not found in PATH.\n%s\n' "${name}" "${install_hint}"
    exit 1
  fi
}

test_docker_compose_v2() {
  docker compose version >/dev/null 2>&1
}

retry_command() {
  local attempts="$1"
  local delay_seconds="$2"
  local description="$3"
  shift 3

  local attempt=1
  while true; do
    if "$@"; then
      return 0
    fi

    if (( attempt >= attempts )); then
      echo "Failed ${description} after ${attempts} attempt(s)."
      return 1
    fi

    echo "Attempt ${attempt}/${attempts} failed while ${description}. Retrying in ${delay_seconds}s ..."
    attempt=$((attempt + 1))
    sleep "${delay_seconds}"
  done
}

ensure_minikube_running() {
  local cpu_count="$1"
  local memory_mb="$2"
  local disk_size="$3"
  local status_output=""

  require_command "kubectl" "Install kubectl using your package manager or from https://kubernetes.io/docs/tasks/tools/."
  require_command "minikube" "Install minikube using your package manager or from https://minikube.sigs.k8s.io/docs/start/."

  status_output="$(minikube status 2>&1 || true)"

  if grep -q "kubeconfig: Misconfigured" <<<"${status_output}"; then
    echo "Detected stale Minikube kubeconfig. Running: minikube update-context"
    minikube update-context
    status_output="$(minikube status 2>&1 || true)"
  fi

  if grep -Eq "host: Stopped|kubelet: Stopped|apiserver: Stopped|minikube does not exist|Profile \"minikube\" not found|No such container: minikube|unknown state|GUEST_STATUS" <<<"${status_output}"; then
    echo "Starting Minikube with the Docker driver (${cpu_count} CPU, ${memory_mb}MB RAM, disk ${disk_size}) ..."
  else
    echo "Ensuring Minikube is running with target sizing ${cpu_count} CPU, ${memory_mb}MB RAM, disk ${disk_size} ..."
  fi

  minikube start --driver=docker --cpus="${cpu_count}" --memory="${memory_mb}mb" --disk-size="${disk_size}"
  minikube update-context
  kubectl config use-context minikube
}

prepare_container_kubeconfig() {
  local runtime_dir="${ROOT_DIR}/.cassie/kube"
  local runtime_config="${runtime_dir}/config"
  local cluster_server=""
  local server_port=""
  local runtime_contents=""

  mkdir -p "${runtime_dir}"

  if ! kubectl config view --raw --minify --flatten > "${runtime_config}"; then
    echo "Failed to generate a flattened kubeconfig for the backend container."
    exit 1
  fi

  cluster_server="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}' | tr -d '\r')"
  if [[ "${cluster_server}" =~ :([0-9]+)$ ]]; then
    server_port="${BASH_REMATCH[1]}"
  fi

  if [[ -n "${server_port}" ]]; then
    runtime_contents="$(cat "${runtime_config}")"
    runtime_contents="$(printf '%s\n' "${runtime_contents}" | sed -E "s#server: https://(127\\.0\\.0\\.1|localhost):[0-9]+#server: https://host.docker.internal:${server_port}#")"
    if ! grep -Eq '^[[:space:]]*tls-server-name:[[:space:]]+localhost[[:space:]]*$' <<<"${runtime_contents}"; then
      runtime_contents="$(printf '%s\n' "${runtime_contents}" | sed -E "/^[[:space:]]*server: https:\/\/host\.docker\.internal:${server_port}[[:space:]]*$/a\\
    tls-server-name: localhost")"
    fi
    printf '%s\n' "${runtime_contents}" > "${runtime_config}"
  fi

  printf '%s\n' "${runtime_dir}"
}

ensure_tool_images() {
  echo "Building or verifying tool images with dockerized_tools/buildtools.sh ..."
  (
    cd "${ROOT_DIR}/dockerized_tools"
    bash buildtools.sh
  )
}

load_tool_images_into_minikube() {
  local images=(
    "fastqc:0.12.1"
    "genomescope2"
    "spades"
    "metaspades"
    "quast"
    "hifiasm"
    "verkko"
    "liftoff"
    "cat-tool"
    "busco"
    "merqury"
  )
  local image=""
  for image in "${images[@]}"; do
    echo "Loading ${image} into Minikube ..."
    minikube image load "${image}"
  done
}

validate_ec2_s3_mode() {
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    echo "Missing ${COMPOSE_FILE}."
    exit 1
  fi

  if [[ -n "${MINIO_ENDPOINT:-}" ]]; then
    echo "MINIO_ENDPOINT must be blank for AWS S3 mode in EC2 deployment."
    exit 1
  fi

  if [[ -n "${MINIO_PUBLIC_ENDPOINT:-}" ]]; then
    echo "MINIO_PUBLIC_ENDPOINT must be blank for AWS S3 mode in EC2 deployment."
    exit 1
  fi

  if [[ -z "${MINIO_BUCKET_PREFIX:-}" ]]; then
    echo "MINIO_BUCKET_PREFIX must be set to your real shared S3 bucket name."
    exit 1
  fi

  if [[ -z "${MINIO_ACCESS_KEY:-}" || -z "${MINIO_SECRET_KEY:-}" ]]; then
    cat <<'EOF'
MINIO_ACCESS_KEY and MINIO_SECRET_KEY must currently be set for EC2 + S3 startup.
This repo's Kubernetes init container passes S3 credentials explicitly into the pod,
so EC2 instance-role-only auth is not enough for pipeline input download yet.
EOF
    exit 1
  fi
}

print_summary() {
  echo
  echo "CASSIE EC2 stack is starting."
  echo "Frontend:    http://localhost:3000"
  echo "Backend:     http://localhost:8000"
  echo "Docs:        http://localhost:8000/docs"
  echo "Storage:     AWS S3 bucket ${MINIO_BUCKET_PREFIX}"
  echo "Kubeconfig:  ${KUBE_CONFIG_DIR}"
  echo "Compose:     ${COMPOSE_FILE}"
  echo "Minikube:    ${CASSIE_MINIKUBE_CPUS} CPU, ${CASSIE_MINIKUBE_MEMORY}MB RAM, disk ${CASSIE_MINIKUBE_DISK_SIZE}"
}

load_env_file

require_command "docker" "Docker is required but was not found in PATH."
require_command "bash" "bash is required but was not found in PATH."

if test_docker_compose_v2; then
  COMPOSE_CMD=(docker compose)
else
  require_command "docker-compose" "Docker Compose is required but was not found."
  COMPOSE_CMD=(docker-compose)
fi

export CASSIE_MINIKUBE_CPUS="$(get_env_value_or_default "CASSIE_MINIKUBE_CPUS" "4")"
export CASSIE_MINIKUBE_MEMORY="$(get_env_value_or_default "CASSIE_MINIKUBE_MEMORY" "7800")"
export CASSIE_MINIKUBE_DISK_SIZE="$(get_env_value_or_default "CASSIE_MINIKUBE_DISK_SIZE" "40g")"
export CASSIE_DOCKER_RETRY_ATTEMPTS="$(get_env_value_or_default "CASSIE_DOCKER_RETRY_ATTEMPTS" "3")"
export CASSIE_DOCKER_RETRY_DELAY_SECONDS="$(get_env_value_or_default "CASSIE_DOCKER_RETRY_DELAY_SECONDS" "5")"
export EXECUTION_BACKEND="${EXECUTION_BACKEND:-kubernetes}"
export KUBERNETES_JOB_TIMEOUT_SECONDS="$(get_env_value_or_default "KUBERNETES_JOB_TIMEOUT_SECONDS" "0")"
export HTTP_PROXY=""
export HTTPS_PROXY=""
export http_proxy=""
export https_proxy=""
export NO_PROXY="${KUBERNETES_NO_PROXY:-localhost,127.0.0.1,host.docker.internal,kubernetes.docker.internal}"
export no_proxy="${NO_PROXY}"
export KUBERNETES_NO_PROXY="${NO_PROXY}"
export KUBERNETES_MINIO_ENDPOINT="${KUBERNETES_MINIO_ENDPOINT:-}"
export CASSIE_CLUSTER_STORAGE_RESERVE_MIB="$(get_env_value_or_default "CASSIE_CLUSTER_STORAGE_RESERVE_MIB" "2048")"

validate_ec2_s3_mode
ensure_minikube_running "${CASSIE_MINIKUBE_CPUS}" "${CASSIE_MINIKUBE_MEMORY}" "${CASSIE_MINIKUBE_DISK_SIZE}"
export KUBE_CONFIG_DIR="$(prepare_container_kubeconfig)"
ensure_tool_images
load_tool_images_into_minikube

retry_command "${CASSIE_DOCKER_RETRY_ATTEMPTS}" "${CASSIE_DOCKER_RETRY_DELAY_SECONDS}" \
  "starting the EC2 compose stack" \
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" up -d --build --remove-orphans

print_summary
