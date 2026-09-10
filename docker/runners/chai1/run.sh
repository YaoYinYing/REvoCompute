#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
# shellcheck source=/dev/null
[[ -f "$task_context_src" ]] && source "$task_context_src"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 1; }
while getopts ":i:o:" opt; do
  case "$opt" in
    i) task_manifest=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${task_manifest:-}" && -n "${output_dir:-}" ]] || usage
[[ "${TASK_TYPE:-}" == "chai1_predict" ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }

task_manifest=$(readlink -f "$task_manifest")
output_dir=$(readlink -m "$output_dir")
[[ -f "$task_manifest" ]] || { echo "Task manifest not found: $task_manifest" >&2; exit 1; }
mkdir -p "$output_dir"
fasta_file=$(primary_input)
fasta_file=$(readlink -f "$fasta_file")

asset_root=${CHAI1_ASSET_ROOT:-/mnt/db/weights/revocompute/chai1}
asset_manifest=${CHAI1_ASSET_MANIFEST:-/app/revocompute/model-assets.json}
asset_validator=${CHAI1_ASSET_VALIDATOR:-/app/revocompute/validate_assets.py}
[[ -f "$asset_validator" ]] || { echo "Missing Chai-1 asset validator: $asset_validator" >&2; exit 1; }
python3 "$asset_validator" --root "$asset_root" --manifest "$asset_manifest"

use_esm_embeddings=$(_parse_param use_esm_embeddings)
use_msa=$(_parse_param use_msa)
use_restraints=$(_parse_param use_restraints)
recycle_msa_subsample=$(_parse_param recycle_msa_subsample)
num_trunk_recycles=$(_parse_param num_trunk_recycles)
num_diffusion_timesteps=$(_parse_param num_diffusion_timesteps)
num_diffusion_samples=$(_parse_param num_diffusion_samples)
num_trunk_samples=$(_parse_param num_trunk_samples)
seed=$(_parse_param seed)
low_memory=$(_parse_param low_memory)

mapfile -t all_inputs < <(
  task_input_files | python3 -c 'import json, sys; print("\n".join(item["path"] for item in json.load(sys.stdin)))'
)
args=(
  --fasta-file "$fasta_file"
  --output-dir "$output_dir"
  --asset-root "$asset_root"
  --recycle-msa-subsample "$recycle_msa_subsample"
  --num-trunk-recycles "$num_trunk_recycles"
  --num-diffusion-timesteps "$num_diffusion_timesteps"
  --num-diffusion-samples "$num_diffusion_samples"
  --num-trunk-samples "$num_trunk_samples"
  --seed "$seed"
)
[[ "$use_esm_embeddings" == "true" ]] && args+=(--use-esm-embeddings)
[[ "$low_memory" == "true" ]] && args+=(--low-memory)

if [[ "$use_msa" == "true" ]]; then
  msa_files=()
  for input_path in "${all_inputs[@]}"; do
    [[ "$input_path" == *.pqt ]] && msa_files+=("$input_path")
  done
  (( ${#msa_files[@]} > 0 )) || { echo "Local MSA use requires at least one uploaded .pqt file" >&2; exit 1; }
  msa_directory=$(dirname "${msa_files[0]}")
  for msa_file in "${msa_files[@]}"; do
    [[ $(dirname "$msa_file") == "$msa_directory" ]] || {
      echo "All uploaded Chai MSA files must share one directory" >&2
      exit 1
    }
  done
  args+=(--msa-directory "$msa_directory")
fi

if [[ "$use_restraints" == "true" ]]; then
  restraint_files=()
  for input_path in "${all_inputs[@]}"; do
    [[ "$input_path" == *.restraints || "$input_path" == *.csv ]] && restraint_files+=("$input_path")
  done
  (( ${#restraint_files[@]} == 1 )) || {
    echo "Restraints use requires exactly one uploaded .restraints or .csv file" >&2
    exit 1
  }
  args+=(--constraint-path "${restraint_files[0]}")
fi

chai_python=${CHAI1_PYTHON:-/opt/venv/bin/python}
chai_script=${CHAI1_SCRIPT:-/app/revocompute/predict.py}
command -v "$chai_python" >/dev/null || { echo "Chai-1 Python is not executable: $chai_python" >&2; exit 1; }
[[ -f "$chai_script" ]] || { echo "Missing Chai-1 prediction adapter: $chai_script" >&2; exit 1; }

runtime_dir=$(mktemp -d "${TMPDIR:-/tmp}/chai1-runtime.XXXXXX")
trap 'rm -rf "$runtime_dir"' EXIT
export HOME="$runtime_dir/home"
export XDG_CACHE_HOME="$runtime_dir/cache"
export NUMBA_CACHE_DIR="$runtime_dir/numba"
export MPLCONFIGDIR="$runtime_dir/matplotlib"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$NUMBA_CACHE_DIR" "$MPLCONFIGDIR"

echo "REVODESIGN_STAGE:chai1_predict"
"$chai_python" "$chai_script" "${args[@]}"

find "$output_dir/ranked" -type f -name 'rank_*.cif' -size +0c -print -quit | grep -q . || {
  echo "Chai-1 produced no ranked mmCIF structure" >&2
  exit 1
}
for pattern in 'confidence.rank_*.json' 'pae.rank_*.npy' 'pde.rank_*.npy' 'plddt.rank_*.npy'; do
  find "$output_dir" -maxdepth 1 -type f -name "$pattern" -size +0c -print -quit | grep -q . || {
    echo "Chai-1 produced no required artifact matching $pattern" >&2
    exit 1
  }
done
[[ -s "$output_dir/ranking.json" ]] || { echo "Chai-1 produced no ranking manifest" >&2; exit 1; }
[[ -s "$output_dir/run_metadata.json" ]] || { echo "Chai-1 produced no run metadata" >&2; exit 1; }
cp "$asset_manifest" "$output_dir/chai1-model-assets.json"
touch "$output_dir/task_finished"
