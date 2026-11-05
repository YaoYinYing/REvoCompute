#!/usr/bin/env bash
set -euo pipefail
usage() { echo 'Usage: run.sh -i task.json -o output_dir' >&2; exit 1; }
while getopts ':i:o:' opt; do case "$opt" in i) input=$OPTARG;; o) output=$OPTARG;; *) usage;; esac; done
[[ -n "${input:-}" && -n "${output:-}" ]] || usage
mkdir -p "$output"
mode=structure
[[ "${TASK_TYPE:-}" == boltz2_affinity ]] && mode=affinity
[[ "${TASK_TYPE:-}" == boltz2_predict || "${TASK_TYPE:-}" == boltz2_affinity ]] || { echo "unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
exec /opt/venv/bin/python /app/revocompute/adapter.py "$mode" "$input" "$output"
