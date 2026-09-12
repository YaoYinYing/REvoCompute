#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 2; }
while getopts ":i:o:" opt; do
  case "$opt" in i) task_manifest=$OPTARG ;; o) output_dir=$OPTARG ;; *) usage ;; esac
done
[[ -n "${task_manifest:-}" && -n "${output_dir:-}" ]] || usage
task_manifest=$(readlink -f "$task_manifest")
output_dir=$(readlink -m "$output_dir")
mkdir -p "$output_dir"

case "${TASK_TYPE:-}" in
  foundry_rfd3_design) asset_id=rfd3 ;;
  foundry_rfd3na_design) asset_id=rfd3na ;;
  foundry_rf3_fold) asset_id=rf3 ;;
  *) echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1 ;;
esac

asset_root=${FOUNDRY_ASSET_ROOT:-/mnt/db/weights/revocompute/foundry}
registry=${FOUNDRY_CHECKPOINT_REGISTRY:-/app/revocompute/checkpoint-registry.json}
operator_manifest=${FOUNDRY_OPERATOR_ASSET_MANIFEST:-${asset_root}/model-assets.json}
validator=${FOUNDRY_ASSET_VALIDATOR:-/app/revocompute/validate_assets.py}
checkpoint=$(python3 "$validator" --asset-id "$asset_id" --asset-root "$asset_root" --registry "$registry" --operator-manifest "$operator_manifest")

export FOUNDRY_CHECKPOINT_DIRS="$asset_root"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 WANDB_MODE=disabled
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
echo "REVODESIGN_STAGE:${TASK_TYPE}"
python3 "${FOUNDRY_LAUNCHER:-/app/revocompute/launch.py}" --task-type "$TASK_TYPE" --manifest "$task_manifest" --output-dir "$output_dir" --checkpoint "$checkpoint"

if [[ "$TASK_TYPE" == "foundry_rf3_fold" ]]; then
  find "$output_dir" -type f \( -name '*.cif' -o -name '*.cif.gz' -o -name '*.pdb' \
    -o -name '*_ranking_scores.csv' \) -size +0c -print -quit | grep -q . || {
    echo "Foundry RF3 produced neither a structure nor early-stopping metrics" >&2; exit 1;
  }
else
  find "$output_dir" -type f \( -name '*.cif' -o -name '*.cif.gz' -o -name '*.pdb' \) -size +0c -print -quit | grep -q . || {
    echo "Foundry produced no structure artifact" >&2; exit 1;
  }
fi
test -s "$output_dir/foundry-run.json"
cp "$operator_manifest" "$output_dir/foundry-model-assets.json"
touch "$output_dir/task_finished"
