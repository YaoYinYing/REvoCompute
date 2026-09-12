#!/usr/bin/env bash
# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
# shellcheck disable=SC1090
[[ -f "$task_context_src" ]] && source "$task_context_src"
model_verify_src="${MODEL_ASSET_VERIFY_SRC:-/app/revocompute/verify_model_asset.sh}"
# shellcheck disable=SC1090
source "$model_verify_src"

while getopts ":i:o:" opt; do
  case "$opt" in
    i) input_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) exit 1 ;;
  esac
done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || { echo "Usage: run.sh -i PDB -o OUTPUT_DIR" >&2; exit 1; }
input_file=$(readlink -f "$input_file")
input_file=$(primary_input)
output_dir=$(readlink -f "$output_dir")
mkdir -p "$output_dir"

[[ "${TASK_TYPE:-}" == "dynamicmpnn" ]] || { echo "Unknown TASK_TYPE: ${TASK_TYPE:-}" >&2; exit 1; }
checkpoint="${DYNAMICMPNN_MODEL_PARAMS}/proteinmpnn_v_48_020.pt"
manifest="${DYNAMICMPNN_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}"
verify_model_asset "$manifest" "$DYNAMICMPNN_MODEL_PARAMS" "proteinmpnn_v_48_020.pt" "dynamicMPNN"

append_parameter() {
  local -n target=$1
  local key=$2
  local value
  value=$(_parse_param "$key")
  [[ -z "$value" || "$value" == "None" || "$value" == "null" ]] || target+=("--$key" "$value")
}

args=(
  --model_type protein_mpnn
  --checkpoint_protein_mpnn "$checkpoint"
  --pdb_path "$input_file"
  --out_folder "$output_dir"
  --number_of_batches "$(_parse_param number_of_batches)"
  --batch_size "$(_parse_param batch_size)"
  --temperature "$(_parse_param sampling_temp)"
  --seed "$(_parse_param seed)"
)
for key in pI_target pI_strength pI_urgency pI_dead_zone surface_patch_type surface_patch_center \
  surface_patch_center_jitter surface_search_radius avoid_motifs; do
  append_parameter args "$key"
done
[[ "$(_parse_param surface_patch_lock)" == "true" ]] && args+=(--surface_patch_lock)

echo "REVODESIGN_STAGE:dynamicmpnn"
python3 "${DYNAMICMPNN_PATH}/run.py" "${args[@]}"
compgen -G "$output_dir/seqs/*.fa" >/dev/null || { echo "dynamicMPNN produced no designed sequences" >&2; exit 1; }
touch "$output_dir/task_finished"
