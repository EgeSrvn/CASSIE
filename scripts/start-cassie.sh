#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

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

reset_minikube_cluster() {
  if ! command -v minikube >/dev/null 2>&1; then
    return
  fi

  echo "Removing existing Minikube clusters to avoid stale state ..."
  minikube delete --all --purge

  if [[ -d "${ROOT_DIR}/.cassie/kube" ]]; then
    rm -rf "${ROOT_DIR}/.cassie/kube"
  fi
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
    echo "Ensuring Minikube is sized at ${cpu_count} CPU, ${memory_mb}MB RAM, disk ${disk_size} ..."
  fi

  minikube start --driver=docker --cpus="${cpu_count}" --memory="${memory_mb}mb" --disk-size="${disk_size}"
  minikube update-context
  kubectl config use-context minikube
}

ensure_metrics_server() {
  echo "Enabling Minikube metrics-server addon for live pod CPU/memory usage ..."
  retry_command "${CASSIE_DOCKER_RETRY_ATTEMPTS}" "${CASSIE_DOCKER_RETRY_DELAY_SECONDS}" \
    "enabling metrics-server addon" minikube addons enable metrics-server
  kubectl wait --for=condition=available deployment/metrics-server -n kube-system --timeout=180s || true
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

ensure_tool_image() {
  local image="$1"
  local context="$2"
  local rebuild_images="${CASSIE_REBUILD_TOOL_IMAGES:-0}"

  if [[ "${rebuild_images,,}" == "1" || "${rebuild_images,,}" == "true" || "${rebuild_images,,}" == "yes" ]]; then
    echo "Rebuilding tool image ${image} because CASSIE_REBUILD_TOOL_IMAGES=${rebuild_images} ..."
    retry_command "${CASSIE_DOCKER_RETRY_ATTEMPTS}" "${CASSIE_DOCKER_RETRY_DELAY_SECONDS}" \
      "building tool image ${image}" docker build -t "${image}" "${context}"
  elif ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "Building tool image ${image} ..."
    retry_command "${CASSIE_DOCKER_RETRY_ATTEMPTS}" "${CASSIE_DOCKER_RETRY_DELAY_SECONDS}" \
      "building tool image ${image}" docker build -t "${image}" "${context}"
  fi
}

load_tool_images_into_minikube() {
  local tool_spec=""
  local image_name=""

  for tool_spec in "$@"; do
    image_name="${tool_spec%% *}"
    echo "Loading ${image_name} into Minikube ..."
    minikube image load "${image_name}"
  done
}

ensure_registry_image() {
  local image="$1"

  if docker image inspect "${image}" >/dev/null 2>&1; then
    return
  fi

  echo "Pulling ${image} ..."
  if ! retry_command "${CASSIE_DOCKER_RETRY_ATTEMPTS}" "${CASSIE_DOCKER_RETRY_DELAY_SECONDS}" \
    "pulling ${image} from a registry" docker pull "${image}"; then
    cat <<EOF
Unable to pull ${image}.
This usually means Docker could not reach the registry reliably (for example a Docker Hub TLS handshake timeout).
You can retry the script, or point the base images at a mirror/private registry with:
  CASSIE_BACKEND_BASE_IMAGE
  CASSIE_FRONTEND_BUILD_BASE_IMAGE
  CASSIE_FRONTEND_NGINX_BASE_IMAGE
  CASSIE_POSTGRES_IMAGE
  CASSIE_MINIO_IMAGE
EOF
    exit 1
  fi
}

prepull_compose_images() {
  local images=(
    "${CASSIE_BACKEND_BASE_IMAGE}"
    "${CASSIE_FRONTEND_BUILD_BASE_IMAGE}"
    "${CASSIE_FRONTEND_NGINX_BASE_IMAGE}"
    "${CASSIE_POSTGRES_IMAGE}"
    "${CASSIE_MINIO_IMAGE}"
  )
  local image=""

  for image in "${images[@]}"; do
    ensure_registry_image "${image}"
  done
}

require_command "docker" "Docker is required but was not found in PATH."

if test_docker_compose_v2; then
  COMPOSE_CMD=(docker compose)
else
  require_command "docker-compose" "Docker Compose is required but was not found."
  COMPOSE_CMD=(docker-compose)
fi

export CASSIE_MINIKUBE_CPUS="$(get_env_value_or_default "CASSIE_MINIKUBE_CPUS" "4")"
export CASSIE_MINIKUBE_MEMORY="$(get_env_value_or_default "CASSIE_MINIKUBE_MEMORY" "7800")"
export CASSIE_MINIKUBE_DISK_SIZE="$(get_env_value_or_default "CASSIE_MINIKUBE_DISK_SIZE" "15g")"
export CASSIE_REBUILD_TOOL_IMAGES="$(get_env_value_or_default "CASSIE_REBUILD_TOOL_IMAGES" "0")"
export CASSIE_DOCKER_RETRY_ATTEMPTS="$(get_env_value_or_default "CASSIE_DOCKER_RETRY_ATTEMPTS" "3")"
export CASSIE_DOCKER_RETRY_DELAY_SECONDS="$(get_env_value_or_default "CASSIE_DOCKER_RETRY_DELAY_SECONDS" "5")"
export CASSIE_BACKEND_BASE_IMAGE="$(get_env_value_or_default "CASSIE_BACKEND_BASE_IMAGE" "python:3.12-slim")"
export CASSIE_FRONTEND_BUILD_BASE_IMAGE="$(get_env_value_or_default "CASSIE_FRONTEND_BUILD_BASE_IMAGE" "node:20-alpine")"
export CASSIE_FRONTEND_NGINX_BASE_IMAGE="$(get_env_value_or_default "CASSIE_FRONTEND_NGINX_BASE_IMAGE" "nginx:1.27-alpine")"
export CASSIE_POSTGRES_IMAGE="$(get_env_value_or_default "CASSIE_POSTGRES_IMAGE" "postgres:15")"
export CASSIE_MINIO_IMAGE="$(get_env_value_or_default "CASSIE_MINIO_IMAGE" "minio/minio:RELEASE.2025-02-28T09-55-16Z")"
export CASSIE_KUBECTL_VERSION="$(get_env_value_or_default "CASSIE_KUBECTL_VERSION" "v1.35.1")"

reset_minikube_cluster
ensure_minikube_running "${CASSIE_MINIKUBE_CPUS}" "${CASSIE_MINIKUBE_MEMORY}" "${CASSIE_MINIKUBE_DISK_SIZE}"
ensure_metrics_server

export EXECUTION_BACKEND="${EXECUTION_BACKEND:-kubernetes}"
export KUBERNETES_JOB_TIMEOUT_SECONDS="$(get_env_value_or_default "KUBERNETES_JOB_TIMEOUT_SECONDS" "0")"

MINIO_API_PORT="${MINIO_API_PORT:-9010}"
MINIO_CONSOLE_PORT="${MINIO_CONSOLE_PORT:-9011}"

export HTTP_PROXY=""
export HTTPS_PROXY=""
export http_proxy=""
export https_proxy=""
export NO_PROXY="localhost,127.0.0.1,host.docker.internal,kubernetes.docker.internal"
export no_proxy="${NO_PROXY}"
export KUBERNETES_NO_PROXY="${NO_PROXY}"
export KUBERNETES_MINIO_ENDPOINT="http://host.docker.internal:${MINIO_API_PORT}"
export KUBE_CONFIG_DIR="$(prepare_container_kubeconfig)"
export CASSIE_CLUSTER_STORAGE_RESERVE_MIB="$(get_env_value_or_default "CASSIE_CLUSTER_STORAGE_RESERVE_MIB" "2048")"
export FASTQC_THREADS="$(get_env_value_or_default "FASTQC_THREADS" "auto")"
export GENOMESCOPE2_THREADS="$(get_env_value_or_default "GENOMESCOPE2_THREADS" "auto")"
export SPADES_THREADS="$(get_env_value_or_default "SPADES_THREADS" "auto")"
export SPADES_MEMORY_GB="$(get_env_value_or_default "SPADES_MEMORY_GB" "auto")"
export SPADES_LOW_RESOURCE="$(get_env_value_or_default "SPADES_LOW_RESOURCE" "auto")"
export SPADES_KMERS="$(get_env_value_or_default "SPADES_KMERS" "auto")"
export SPADES_MEMORY_LIMIT="$(get_env_value_or_default "SPADES_MEMORY_LIMIT" "auto")"
export METASPADES_THREADS="$(get_env_value_or_default "METASPADES_THREADS" "auto")"
export METASPADES_MEMORY_GB="$(get_env_value_or_default "METASPADES_MEMORY_GB" "auto")"
export HIFIASM_THREADS="$(get_env_value_or_default "HIFIASM_THREADS" "auto")"
export HIFIASM_MEMORY_GB="$(get_env_value_or_default "HIFIASM_MEMORY_GB" "auto")"
export VERKKO_THREADS="$(get_env_value_or_default "VERKKO_THREADS" "auto")"
export VERKKO_MEMORY_GB="$(get_env_value_or_default "VERKKO_MEMORY_GB" "auto")"
export LIFTOFF_THREADS="$(get_env_value_or_default "LIFTOFF_THREADS" "auto")"
export CAT_THREADS="$(get_env_value_or_default "CAT_THREADS" "auto")"
export CAT_MEMORY_GB="$(get_env_value_or_default "CAT_MEMORY_GB" "auto")"
export BUSCO_THREADS="$(get_env_value_or_default "BUSCO_THREADS" "auto")"
export BUSCO_MEMORY_GB="$(get_env_value_or_default "BUSCO_MEMORY_GB" "auto")"
export MERYL_THREADS="$(get_env_value_or_default "MERYL_THREADS" "auto")"
export MERYL_MEMORY_GB="$(get_env_value_or_default "MERYL_MEMORY_GB" "auto")"
export MERQURY_THREADS="$(get_env_value_or_default "MERQURY_THREADS" "auto")"
export MERQURY_MEMORY_GB="$(get_env_value_or_default "MERQURY_MEMORY_GB" "auto")"
export QUAST_THREADS="$(get_env_value_or_default "QUAST_THREADS" "auto")"

TOOL_IMAGES=(
  "fastqc:0.12.1 dockerized_tools/fastqc"
  "spades:latest dockerized_tools/spades"
  "metaspades:latest dockerized_tools/metaspades"
  "quast:latest dockerized_tools/quast"
  "genomescope2:latest dockerized_tools/genomescope2"
  "hifiasm:latest dockerized_tools/hifiasm"
  "verkko:latest dockerized_tools/verkko"
  "liftoff:latest dockerized_tools/liftoff"
  "cat-tool:latest dockerized_tools/cat"
  "busco:latest dockerized_tools/busco"
  "meryl:latest dockerized_tools/meryl"
  "merqury:latest dockerized_tools/merqury"
)

for tool_spec in "${TOOL_IMAGES[@]}"; do
  ensure_tool_image "${tool_spec%% *}" "${tool_spec#* }"
done

load_tool_images_into_minikube "${TOOL_IMAGES[@]}"

prepull_compose_images

"${COMPOSE_CMD[@]}" up --build -d --force-recreate --remove-orphans

echo
echo "CASSIE is starting."
echo "Frontend:   http://localhost:3000"
echo "Backend:    http://localhost:8000"
echo "Docs:       http://localhost:8000/docs"
echo "MinIO API:  http://localhost:${MINIO_API_PORT}"
echo "MinIO UI:   http://localhost:${MINIO_CONSOLE_PORT}"
echo "Backend:    ${EXECUTION_BACKEND} execution backend"
echo "Kubeconfig: ${KUBE_CONFIG_DIR}"
echo "K8s MinIO:  ${KUBERNETES_MINIO_ENDPOINT}"
echo "Minikube:   ${CASSIE_MINIKUBE_CPUS} CPU, ${CASSIE_MINIKUBE_MEMORY}MB RAM, disk ${CASSIE_MINIKUBE_DISK_SIZE}"
