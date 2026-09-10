#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 1; }
while getopts ":i:o:" opt; do
  case "$opt" in
    i) input_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || usage
[[ "${TASK_TYPE:-}" == "boltz_predict" ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }

input_file=$(readlink -f "$input_file")
output_dir=$(readlink -m "$output_dir")
[[ -f "$input_file" ]] || { echo "Task manifest not found: $input_file" >&2; exit 1; }
mkdir -p "$output_dir"
input_file=$(primary_input)
input_file=$(readlink -f "$input_file")

asset_root=${BOLTZ_ASSET_ROOT:-/mnt/db/boltz}
asset_manifest=${BOLTZ_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}
checkpoint="${asset_root}/boltz1_conf.ckpt"
ccd="${asset_root}/ccd.pkl"
[[ -s "$checkpoint" ]] || { echo "Missing Boltz-1 checkpoint: $checkpoint" >&2; exit 1; }
[[ -s "$ccd" ]] || { echo "Missing Boltz CCD dictionary: $ccd" >&2; exit 1; }
[[ -s "$asset_manifest" ]] || { echo "Missing Boltz asset manifest: $asset_manifest" >&2; exit 1; }
sha256sum --strict --check --status "$asset_manifest" || {
  echo "Boltz asset integrity verification failed: $asset_manifest" >&2
  exit 1
}

recycling_steps=$(_parse_param recycling_steps)
sampling_steps=$(_parse_param sampling_steps)
diffusion_samples=$(_parse_param diffusion_samples)
preprocessing_workers=$(_parse_param preprocessing_workers)
seed=$(_parse_param seed)
write_full_pae=$(_parse_param write_full_pae)
write_full_pde=$(_parse_param write_full_pde)

boltz_cli=${BOLTZ_CLI:-/opt/venv/bin/boltz}
[[ -x "$boltz_cli" ]] || { echo "Boltz CLI is not executable: $boltz_cli" >&2; exit 1; }
args=(
  predict "$input_file"
  --out_dir "$output_dir"
  --cache "$asset_root"
  --checkpoint "$checkpoint"
  --devices 1
  --accelerator gpu
  --recycling_steps "$recycling_steps"
  --sampling_steps "$sampling_steps"
  --diffusion_samples "$diffusion_samples"
  --output_format mmcif
  --num_workers "$preprocessing_workers"
  --seed "$seed"
  --override
)
[[ "$write_full_pae" == "true" ]] && args+=(--write_full_pae)
[[ "$write_full_pde" == "true" ]] && args+=(--write_full_pde)

echo "REVODESIGN_STAGE:boltz_predict"
(
  cd "$(dirname "$input_file")"
  "$boltz_cli" "${args[@]}"
)

prediction_root="${output_dir}/boltz_results_$(basename "${input_file%.*}")"
find "$prediction_root/predictions" -type f -name '*_model_*.cif' -size +0c -print -quit | grep -q . || {
  echo "Boltz produced no mmCIF structure" >&2
  exit 1
}
find "$prediction_root/predictions" -type f -name 'confidence_*_model_*.json' -size +0c -print -quit | grep -q . || {
  echo "Boltz produced no confidence summary" >&2
  exit 1
}
find "$prediction_root/predictions" -type f -name 'plddt_*_model_*.npz' -size +0c -print -quit | grep -q . || {
  echo "Boltz produced no per-token pLDDT output" >&2
  exit 1
}
[[ -s "$prediction_root/processed/manifest.json" ]] || {
  echo "Boltz produced no processed input manifest" >&2
  exit 1
}
if [[ "$write_full_pae" == "true" ]]; then
  find "$prediction_root/predictions" -type f -name 'pae_*_model_*.npz' -size +0c -print -quit | grep -q . || {
    echo "Boltz produced no requested PAE output" >&2
    exit 1
  }
fi
if [[ "$write_full_pde" == "true" ]]; then
  find "$prediction_root/predictions" -type f -name 'pde_*_model_*.npz' -size +0c -print -quit | grep -q . || {
    echo "Boltz produced no requested PDE output" >&2
    exit 1
  }
fi
cp "$asset_manifest" "$output_dir/boltz-model-assets.sha256"
touch "$output_dir/task_finished"
