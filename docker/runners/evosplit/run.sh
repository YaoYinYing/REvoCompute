#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

while getopts ":i:o:" opt; do
  case "$opt" in
    i) task_manifest=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) exit 1 ;;
  esac
done
[[ -n "${task_manifest:-}" && -n "${output_dir:-}" ]] || {
  echo "Usage: run.sh -i TASK_MANIFEST -o OUTPUT_DIR" >&2
  exit 1
}
[[ "${TASK_TYPE:-}" == "evosplit_cluster" ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }

task_manifest=$(readlink -f "$task_manifest")
output_dir=$(readlink -f "$output_dir")
[[ -f "$task_manifest" ]] || { echo "Task manifest not found: $task_manifest" >&2; exit 1; }
mkdir -p "$output_dir"

runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/revocompute-evosplit.XXXXXX")
trap 'rm -rf -- "$runtime_dir"' EXIT
export TMPDIR="$runtime_dir/tmp"
export XDG_CACHE_HOME="$runtime_dir/cache"
export TORCH_HOME="$runtime_dir/torch"
export MPLCONFIGDIR="$runtime_dir/matplotlib"
export PYTHONNOUSERSITE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
# The pinned upstream loader predates Torch's weights_only=True default. This
# is enabled only after the adapter verifies the official model fingerprints.
export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$TORCH_HOME" "$MPLCONFIGDIR"

echo "REVODESIGN_STAGE:evosplit_cluster"
"${EVOSPLIT_PYTHON:-python3}" "${EVOSPLIT_SCRIPT:-/app/revocompute/predict.py}" \
  --task-manifest "$task_manifest" \
  --output-dir "$output_dir" \
  --asset-root "${EVOSPLIT_ASSET_ROOT:-/mnt/db/weights/esm}" \
  --asset-manifest "${EVOSPLIT_ASSET_MANIFEST:-/app/revocompute/model-assets.json}"

for artifact in processed_alignment.a3m sequence_assignments.csv contact_probabilities.csv contact_probabilities.png \
  summary.json evosplit-model-assets.json; do
  [[ -s "$output_dir/$artifact" ]] || { echo "EvoSplit did not produce required artifact: $artifact" >&2; exit 1; }
done
compgen -G "$output_dir/clusters/cluster_*.a3m" >/dev/null || {
  echo "EvoSplit produced no clustered MSA" >&2
  exit 1
}
touch "$output_dir/task_finished"
