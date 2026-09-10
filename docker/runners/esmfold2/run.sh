#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 2; }
while getopts ":i:o:" opt; do
  case "$opt" in
    i) task_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || usage
[[ -f "$task_file" ]] || { echo "Task manifest not found: $task_file" >&2; exit 1; }
output_dir=$(readlink -f "$output_dir")
asset_root="${ESMFOLD2_ASSET_ROOT:-/mnt/db/weights/revocompute/esmfold2}"
mkdir -p "$output_dir"

args=(
  --task-manifest "$task_file"
  --output-dir "$output_dir"
  --asset-root "$asset_root"
  --model-variant "$(_parse_param model_variant)"
  --num-loops "$(_parse_param num_loops)"
  --num-sampling-steps "$(_parse_param num_sampling_steps)"
  --num-diffusion-samples "$(_parse_param num_diffusion_samples)"
  --seed "$(_parse_param seed)"
  --lm-dropout "$(_parse_param lm_dropout)"
  --lm-mask-pct "$(_parse_param lm_mask_pct)"
  --msa-max-depth "$(_parse_param msa_max_depth)"
  --msa-column-mask-rate "$(_parse_param msa_column_mask_rate)"
  --kernel-backend "$(_parse_param kernel_backend)"
)
[[ "$(_parse_param include_embeddings)" == "true" ]] && args+=(--include-embeddings)

echo "REVODESIGN_STAGE:esmfold2_predict"
"${ESMFOLD2_PYTHON:-python}" "${ESMFOLD2_PREDICT_SCRIPT:-/app/revocompute/predict.py}" "${args[@]}"
test -s "$output_dir/prediction.json"
find "$output_dir" -maxdepth 1 -type f -name 'sample_*.cif' -size +0c -print -quit | grep -q . || {
  echo "ESMFold 2 produced no mmCIF structure artifact" >&2
  exit 1
}
find "$output_dir" -maxdepth 1 -type f -name 'sample_*_confidence.json' -size +0c -print -quit | grep -q . || {
  echo "ESMFold 2 produced no confidence artifact" >&2
  exit 1
}
touch "$output_dir/task_finished"
