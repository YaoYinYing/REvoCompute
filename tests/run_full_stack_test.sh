#!/usr/bin/env bash

set -euo pipefail

SERVER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${SERVER_ROOT}"
DEPLOY_SCRIPT="${SERVER_ROOT}/run/restart.sh"
QUERY_FASTA="${REPO_ROOT}/tests/data/msa/2KL8.fasta"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/revodesign-full-stack.XXXXXX")"
ENV_FILE="${WORK_DIR}/server-test.env"
RUN_ID="$(basename "${WORK_DIR}" | tr '[:upper:]' '[:lower:]' | tr '.' '-')"
export COMPOSE_PROJECT_NAME="${RUN_ID}"

SERVER_IMAGE="revodesign-gremlin-server-${RUN_ID}"
STACK_STARTED=0

cleanup() {
  local status=$?
  set +e
  if [[ ${status} -ne 0 && ${STACK_STARTED} -eq 1 ]]; then
    docker compose -f "${SERVER_ROOT}/docker-compose.yml" -f "${SERVER_ROOT}/docker-compose.slurm.yml" --env-file "${ENV_FILE}" logs --no-color --tail=200
  fi
  if [[ -f "${ENV_FILE}" ]]; then
    REVODESIGN_SERVER_ENV="${ENV_FILE}" bash "${DEPLOY_SCRIPT}" down
    docker compose -f "${SERVER_ROOT}/docker-compose.yml" -f "${SERVER_ROOT}/docker-compose.slurm.yml" --env-file "${ENV_FILE}" \
      down --volumes --remove-orphans
  fi
  docker image rm --force "${SERVER_IMAGE}" >/dev/null 2>&1
  rm -rf "${WORK_DIR}"
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ ! -f "${QUERY_FASTA}" ]]; then
  echo "Full-stack query fixture not found: ${QUERY_FASTA}" >&2
  exit 1
fi

mkdir -p \
  "${WORK_DIR}/state/server" \
  "${WORK_DIR}/state/auth" \
  "${WORK_DIR}/state/logs" \
  "${WORK_DIR}/state/images" \
  "${WORK_DIR}/hpc/lib" \
  "${WORK_DIR}/hpc/slurm-config" \
  "${WORK_DIR}/hpc/munge"
touch "${WORK_DIR}/state/images/gremlin_v1.sif" "${WORK_DIR}/hpc/libmunge.so.2"
cp "${SERVER_ROOT}/tests/hpc_command_shim.sh" "${WORK_DIR}/hpc/command-shim"
chmod 0755 "${WORK_DIR}/hpc/command-shim"

cp "${SERVER_ROOT}/.env.example" "${ENV_FILE}"
PORT="$(python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
SLURM_REDIS_PORT="$(python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
RUNNER_UID="$(id -u)"
RUNNER_GID="$(id -g)"
if [[ "${RUNNER_UID}" == "0" ]]; then
  RUNNER_UID=1000
  RUNNER_GID=1000
  chown -R "${RUNNER_UID}:${RUNNER_GID}" "${WORK_DIR}"
elif [[ "${RUNNER_GID}" == "0" ]]; then
  RUNNER_GID="${RUNNER_UID}"
fi
export RUNNER_UID RUNNER_GID
mkdir -p "${WORK_DIR}/state/server/docker/runners"
cp -r "${SERVER_ROOT}/docker/runners/pssm_gremlin" "${WORK_DIR}/state/server/docker/runners/"
python - "${WORK_DIR}/state/server/docker/runners/pssm_gremlin/runner.yaml" "${WORK_DIR}" <<'PY'
from pathlib import Path
import sys

import yaml

path = Path(sys.argv[1])
work_dir = sys.argv[2]
runner = yaml.safe_load(path.read_text(encoding="utf-8"))
runner["mounts"][0]["host_path"] = f"{work_dir}/hpc/mock-uniref30"
runner["mounts"][1]["host_path"] = f"{work_dir}/hpc/mock-uniref90"
path.write_text(yaml.safe_dump(runner, sort_keys=False), encoding="utf-8")
PY
mkdir -p "${WORK_DIR}/hpc/mock-uniref30" "${WORK_DIR}/hpc/mock-uniref90"
cat >>"${ENV_FILE}" <<EOF

# Full-stack test overrides
SERVER_IMAGE=${SERVER_IMAGE}
SERVER_DIR=${WORK_DIR}/state/server
RUNNER_HOST_ROOT=${WORK_DIR}/state
REVOCOMPUTE_IMAGE_DIR=${WORK_DIR}/state/images
LOG_DIR=${WORK_DIR}/state/logs
AUTH_DIR=${WORK_DIR}/state/auth
ADMIN_USERS=admin
RUNNER_UID=${RUNNER_UID}
RUNNER_GID=${RUNNER_GID}
NPROC=2
MAXMEM=1
WORKER_CONCURRENCY=1
PORT=${PORT}
SLURM_REDIS_PORT=${SLURM_REDIS_PORT}
GUNICORN_WORKERS=1
CONFIG_DIR=${WORK_DIR}/state/server/docker/runners
RUNNER_SOURCE_ROOT=${WORK_DIR}/state/server/docker/runners
ENABLED_TASKRUNNERS=gremlin
SLURM_ENABLED=true
SBATCH_BIN=${WORK_DIR}/hpc/command-shim
SQUEUE_BIN=${WORK_DIR}/hpc/command-shim
SCANCEL_BIN=${WORK_DIR}/hpc/command-shim
SACCT_BIN=${WORK_DIR}/hpc/command-shim
SINFO_BIN=${WORK_DIR}/hpc/command-shim
SRUN_BIN=${WORK_DIR}/hpc/command-shim
APPTAINER_BIN=${WORK_DIR}/hpc/command-shim
SLURM_LIB_DIR=${WORK_DIR}/hpc/lib
SLURM_CONFIG_DIR=${WORK_DIR}/hpc/slurm-config
MUNGE_RUN_DIR=${WORK_DIR}/hpc/munge
MUNGE_LIB=${WORK_DIR}/hpc/libmunge.so.2
TZ=UTC
EOF

echo "Building the GREMLIN server image..."
docker build \
  --build-arg "RUNNER_UID=${RUNNER_UID}" \
  --build-arg "RUNNER_GID=${RUNNER_GID}" \
  --build-arg RUNNER_USERNAME=revodesign \
  --build-arg RUNNER_GROUP=revodesign_appgroup \
  --build-arg "PORT=${PORT}" \
  --file "${SERVER_ROOT}/docker/server/Dockerfile" \
  --tag "${SERVER_IMAGE}" \
  "${SERVER_ROOT}"

echo "Launching the full server stack from the generated test environment..."
if ! UP_OUTPUT="$(REVODESIGN_SERVER_ENV="${ENV_FILE}" bash "${DEPLOY_SCRIPT}" up 2>&1)"; then
  printf '%s\n' "${UP_OUTPUT}" | sed 's/password: .*/password: [REDACTED]/'
  echo "The server stack failed to launch." >&2
  exit 1
fi
STACK_STARTED=1
ADMIN_CREDENTIAL_FILE="$(printf '%s\n' "${UP_OUTPUT}" | sed -n 's/^Bootstrap admin credentials written to: \([^ ]*\) (mode 0600)$/\1/p' | tail -n 1)"
if [[ -z "${ADMIN_CREDENTIAL_FILE}" || ! -f "${ADMIN_CREDENTIAL_FILE}" ]]; then
  echo "The launch output did not identify the protected admin credential file." >&2
  exit 1
fi
ADMIN_PASSWORD="$(awk -F '\t' '$1 == "admin" { print $2; exit }' "${ADMIN_CREDENTIAL_FILE}")"
if [[ -z "${ADMIN_PASSWORD}" ]]; then
  echo "The protected credential file did not contain the test admin account." >&2
  exit 1
fi
echo "Loaded the generated admin password from the protected credential file."

echo "Running API, web-page, and production Slurm/Apptainer orchestration checks..."
FULL_STACK_ADMIN_PASSWORD="${ADMIN_PASSWORD}" python "${SERVER_ROOT}/tests/full_stack_smoke.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --fasta "${QUERY_FASTA}"
echo "Full-stack mocked-HPC test passed."
