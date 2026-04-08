#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required but was not found in PATH."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Docker Compose is required but was not found."
  exit 1
fi

if [[ -z "${KUBE_CONFIG_DIR:-}" ]]; then
  DEFAULT_KUBE_DIR="${HOME}/.kube"
  if [[ -f "${DEFAULT_KUBE_DIR}/config" ]]; then
    export KUBE_CONFIG_DIR="${DEFAULT_KUBE_DIR}"
  fi
fi

export EXECUTION_BACKEND="${EXECUTION_BACKEND:-kubernetes}"
export HTTP_PROXY=""
export HTTPS_PROXY=""
export http_proxy=""
export https_proxy=""

MINIO_API_PORT="${MINIO_API_PORT:-9010}"
NO_PROXY_ITEMS=(
  "localhost"
  "127.0.0.1"
  "host.docker.internal"
  "kubernetes.docker.internal"
)

if [[ "$(uname -s)" == "Linux" ]]; then
  CASSIE_HOST_IP="${CASSIE_HOST_IP:-}"
  if [[ -z "${CASSIE_HOST_IP}" ]] && command -v ip >/dev/null 2>&1; then
    CASSIE_HOST_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')"
  fi
  if [[ -z "${CASSIE_HOST_IP}" ]] && command -v hostname >/dev/null 2>&1; then
    CASSIE_HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [[ -n "${CASSIE_HOST_IP}" ]]; then
    export CASSIE_HOST_IP
    NO_PROXY_ITEMS+=("${CASSIE_HOST_IP}")
    export KUBERNETES_MINIO_ENDPOINT="${KUBERNETES_MINIO_ENDPOINT:-http://${CASSIE_HOST_IP}:${MINIO_API_PORT}}"
  fi
fi

preflight_minikube() {
  local current_context=""
  local status_output=""

  if ! command -v kubectl >/dev/null 2>&1; then
    return 0
  fi

  current_context="$(kubectl config current-context 2>/dev/null || true)"
  if [[ "${current_context}" != "minikube" ]]; then
    return 0
  fi

  if ! command -v minikube >/dev/null 2>&1; then
    echo "Current Kubernetes context is minikube, but the minikube CLI is not installed."
    return 0
  fi

  status_output="$(minikube status 2>&1 || true)"

  if grep -q "kubeconfig: Misconfigured" <<<"${status_output}"; then
    echo "Detected stale Minikube kubeconfig. Running: minikube update-context"
    minikube update-context
    status_output="$(minikube status 2>&1 || true)"
  fi

  if grep -q "apiserver: Stopped" <<<"${status_output}"; then
    echo "Minikube API server is stopped. Start the cluster first with:"
    echo "  minikube start"
    echo "Then rerun ./scripts/start-cassie.sh"
    exit 1
  fi
}

preflight_minikube

load_images_into_minikube() {
  local current_context=""

  if ! command -v kubectl >/dev/null 2>&1 || ! command -v minikube >/dev/null 2>&1; then
    return 0
  fi

  current_context="$(kubectl config current-context 2>/dev/null || true)"
  if [[ "${current_context}" != "minikube" ]]; then
    return 0
  fi

  for tool_spec in "${TOOL_IMAGES[@]}"; do
    image_name="${tool_spec%% *}"
    echo "Loading ${image_name} into Minikube ..."
    minikube image load "${image_name}"
  done
}

prepare_container_kubeconfig() {
  local source_dir="${KUBE_CONFIG_DIR:-}"
  local source_config=""
  local runtime_dir=""
  local runtime_config=""
  local current_context=""
  local cluster_server=""
  local server_host=""
  local server_port=""
  local minikube_profile=""
  local minikube_ip=""
  local minikube_port=""

  if [[ -z "${source_dir}" ]]; then
    return 0
  fi

  source_config="${source_dir}/config"
  if [[ ! -f "${source_config}" ]]; then
    return 0
  fi

  if ! command -v kubectl >/dev/null 2>&1; then
    return 0
  fi

  runtime_dir="${ROOT_DIR}/.cassie/kube"
  runtime_config="${runtime_dir}/config"
  mkdir -p "${runtime_dir}"

  current_context="$(kubectl config current-context 2>/dev/null || true)"
  cluster_server="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)"

  if ! kubectl config view --raw --minify --flatten > "${runtime_config}"; then
    echo "Failed to generate a flattened kubeconfig for the backend container."
    exit 1
  fi

  if [[ -n "${cluster_server}" ]]; then
    server_host="$(printf '%s\n' "${cluster_server}" | sed -E 's#^https?://([^:/]+).*$#\1#')"
    server_port="$(printf '%s\n' "${cluster_server}" | sed -nE 's#^https?://[^:/]+:([0-9]+).*$#\1#p')"
  fi

  if [[ "${current_context}" == "minikube" && ( "${server_host}" == "127.0.0.1" || "${server_host}" == "localhost" ) ]]; then
    minikube_profile="${HOME}/.minikube/profiles/minikube/config.json"
    if [[ -f "${minikube_profile}" ]]; then
      minikube_ip="$(sed -nE 's/.*"IP": "([^"]+)".*/\1/p' "${minikube_profile}" | head -n 1)"
      minikube_port="$(sed -nE 's/.*"APIServerPort": ([0-9]+).*/\1/p' "${minikube_profile}" | head -n 1)"
    fi
    if [[ -n "${minikube_ip}" && -n "${minikube_port}" ]]; then
      sed -i -E "s#server: https://(127\\.0\\.0\\.1|localhost):[0-9]+#server: https://${minikube_ip}:${minikube_port}#" "${runtime_config}"
      NO_PROXY_ITEMS+=("${minikube_ip}")
      echo "Using Minikube API server ${minikube_ip}:${minikube_port} for the backend container."
    fi
  elif [[ -n "${CASSIE_HOST_IP:-}" && ( "${server_host}" == "127.0.0.1" || "${server_host}" == "localhost" ) && -n "${server_port}" ]]; then
    sed -i -E "s#server: https://(127\\.0\\.0\\.1|localhost):${server_port}#server: https://${CASSIE_HOST_IP}:${server_port}#" "${runtime_config}"
    NO_PROXY_ITEMS+=("${CASSIE_HOST_IP}")
    echo "Rewriting localhost Kubernetes API server to ${CASSIE_HOST_IP}:${server_port} for the backend container."
  fi

  export KUBE_CONFIG_DIR="${runtime_dir}"
}

prepare_container_kubeconfig

NO_PROXY_VALUE="$(IFS=,; echo "${NO_PROXY_ITEMS[*]}")"
export NO_PROXY="${KUBERNETES_NO_PROXY:-$NO_PROXY_VALUE}"
export no_proxy="${NO_PROXY}"

TOOL_IMAGES=(
  "fastqc:0.12.1 dockerized_tools/fastqc"
  "spades:latest dockerized_tools/spades"
  "quast:latest dockerized_tools/quast"
  "genomescope2:latest dockerized_tools/genomescope2"
)

for tool_spec in "${TOOL_IMAGES[@]}"; do
  image_name="${tool_spec%% *}"
  build_context="${tool_spec#* }"
  if ! docker image inspect "${image_name}" >/dev/null 2>&1; then
    echo "Building tool image ${image_name} ..."
    docker build -t "${image_name}" "${build_context}"
  fi
done

load_images_into_minikube

"${COMPOSE_CMD[@]}" up --build -d --force-recreate --remove-orphans

echo
echo "CASSIE is starting."
echo "Frontend:   http://localhost:3000"
echo "Backend:    http://localhost:8000"
echo "Docs:       http://localhost:8000/docs"
echo "MinIO API:  http://localhost:${MINIO_API_PORT}"
echo "MinIO UI:   http://localhost:${MINIO_CONSOLE_PORT:-9011}"
echo "Backend:    ${EXECUTION_BACKEND} execution backend"
if [[ -n "${KUBE_CONFIG_DIR:-}" ]]; then
  echo "Kubeconfig: ${KUBE_CONFIG_DIR}"
fi
if [[ -n "${KUBERNETES_MINIO_ENDPOINT:-}" ]]; then
  echo "K8s MinIO:  ${KUBERNETES_MINIO_ENDPOINT}"
fi
