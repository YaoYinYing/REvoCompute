#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
# shellcheck source=/dev/null
[[ -f "$task_context_src" ]] && source "$task_context_src"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 2; }
while getopts ":i:o:" opt; do
  case "$opt" in
    i) input_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || usage
input_file=$(readlink -f "$input_file")
[[ -f "$input_file" ]] || { echo "Task manifest not found: $input_file" >&2; exit 1; }
output_dir=$(readlink -m "$output_dir")
fasta_path=$(readlink -f "$(primary_input)")
[[ -f "$fasta_path" ]] || { echo "SimpleFold FASTA not found: $fasta_path" >&2; exit 1; }

model=$(_parse_param model)
num_steps=$(_parse_param num_steps)
tau=$(_parse_param tau)
num_samples=$(_parse_param num_samples)
predict_plddt=$(_parse_param predict_plddt)
output_format=$(_parse_param output_format)
seed=$(_parse_param seed)

weight_dir=${SIMPLEFOLD_WEIGHT_DIR:-/mnt/db/weights/simplefold}
ccd_path=${SIMPLEFOLD_CCD_PATH:-/mnt/db/boltz/ccd.pkl}
esm_weight_dir=${SIMPLEFOLD_ESM_WEIGHT_DIR:-/mnt/db/weights/esm/checkpoints}
esm_hub_source=${SIMPLEFOLD_ESM_HUB_SOURCE:-/opt/torch-hub/facebookresearch_esm_main}
model_checkpoint="${weight_dir}/${model}.ckpt"
plddt_checkpoint="${weight_dir}/plddt.ckpt"
esm_checkpoint="${esm_weight_dir}/esm2_t36_3B_UR50D.pt"
esm_regression="${esm_weight_dir}/esm2_t36_3B_UR50D-contact-regression.pt"
simplefold_16b_sha256=${SIMPLEFOLD_16B_SHA256:-aaac2d73dcc59c61153c58a1d56e74a8ada9d6057d67000f7836f3c87325312b}
simplefold_3b_sha256=${SIMPLEFOLD_3B_SHA256:-88d4c7a240bf3815cb35342b4ddc1128ac243a2ea0256eb8a4df1209125868b5}
plddt_sha256=${SIMPLEFOLD_PLDDT_SHA256:-cb32fa9cdc9e80406b793a8c09a929077534d9991a1d08f4c159d2e4ed81315f}
ccd_sha256=${SIMPLEFOLD_CCD_SHA256:-2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4}
esm_model_sha256=${SIMPLEFOLD_ESM_MODEL_SHA256:-7de8b4082ba15891959ab368b77ce3886697af1efb16d3c9e9e7b0c5d3f07500}
esm_regression_sha256=${SIMPLEFOLD_ESM_REGRESSION_SHA256:-4da500eab246481dc9c8c95bc7b1d02f2803d761c380b0e95186d4a07d0fc84e}

verify_asset() {
  local path=$1 expected=$2 actual
  actual=$(sha256sum "$path" | cut -d' ' -f1)
  [[ "$actual" == "$expected" ]] || {
    echo "Unexpected model asset fingerprint for $path: expected $expected, got $actual" >&2
    exit 1
  }
}

echo "REVODESIGN_STAGE:input_validation"
"${SIMPLEFOLD_PYTHON:-python3}" "${SIMPLEFOLD_VALIDATE:-/app/revocompute/validate_fasta.py}" "$fasta_path" >/dev/null
[[ "$model" == "simplefold_1.6B" || "$model" == "simplefold_3B" ]] || { echo "Unsupported SimpleFold model: $model" >&2; exit 1; }
[[ -s "$model_checkpoint" ]] || { echo "Missing SimpleFold checkpoint: $model_checkpoint" >&2; exit 1; }
[[ -s "$ccd_path" ]] || { echo "Missing Boltz CCD asset: $ccd_path" >&2; exit 1; }
[[ -s "$esm_checkpoint" ]] || { echo "Missing ESM-2 checkpoint: $esm_checkpoint" >&2; exit 1; }
[[ -s "$esm_regression" ]] || { echo "Missing ESM-2 regression weights: $esm_regression" >&2; exit 1; }
[[ -f "$esm_hub_source/hubconf.py" ]] || { echo "Missing pinned ESM torch.hub source: $esm_hub_source" >&2; exit 1; }
if [[ "$model" == "simplefold_1.6B" ]]; then
  verify_asset "$model_checkpoint" "$simplefold_16b_sha256"
else
  verify_asset "$model_checkpoint" "$simplefold_3b_sha256"
fi
verify_asset "$ccd_path" "$ccd_sha256"
verify_asset "$esm_checkpoint" "$esm_model_sha256"
verify_asset "$esm_regression" "$esm_regression_sha256"
if [[ "$predict_plddt" == "true" ]]; then
  [[ -s "$plddt_checkpoint" ]] || { echo "Missing SimpleFold pLDDT checkpoint: $plddt_checkpoint" >&2; exit 1; }
  [[ -s "$weight_dir/simplefold_1.6B.ckpt" ]] || { echo "Missing SimpleFold pLDDT latent checkpoint" >&2; exit 1; }
  verify_asset "$plddt_checkpoint" "$plddt_sha256"
  [[ "$model" == "simplefold_1.6B" ]] || verify_asset "$weight_dir/simplefold_1.6B.ckpt" "$simplefold_16b_sha256"
elif [[ "$predict_plddt" != "false" ]]; then
  echo "Invalid predict_plddt value: $predict_plddt" >&2
  exit 1
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/revocompute-simplefold.XXXXXX")
cleanup() { rm -rf -- "$scratch"; }
trap cleanup EXIT
mkdir -p "$scratch/torch/hub" "$scratch/cache" "$output_dir"
ln -s "$esm_hub_source" "$scratch/torch/hub/facebookresearch_esm_main"
ln -s "$esm_weight_dir" "$scratch/torch/hub/checkpoints"
export TORCH_HOME="$scratch/torch"
export XDG_CACHE_HOME="$scratch/cache"
export HF_HOME="$scratch/cache/huggingface"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export HTTP_PROXY="" HTTPS_PROXY="" ALL_PROXY="" http_proxy="" https_proxy="" all_proxy="" NO_PROXY="" no_proxy=""

echo "REVODESIGN_STAGE:model_loading"
predict_args=(
  --fasta-path "$fasta_path"
  --output-dir "$output_dir"
  --checkpoint-dir "$weight_dir"
  --ccd-path "$ccd_path"
  --model "$model"
  --num-steps "$num_steps"
  --tau "$tau"
  --num-samples "$num_samples"
  --output-format "$output_format"
  --seed "$seed"
)
[[ "$predict_plddt" == "true" ]] && predict_args+=(--plddt)
echo "REVODESIGN_STAGE:structure_sampling"
"${SIMPLEFOLD_PYTHON:-python3}" "${SIMPLEFOLD_PREDICT:-/app/revocompute/offline_predict.py}" "${predict_args[@]}"

echo "REVODESIGN_STAGE:output_validation"
"${SIMPLEFOLD_PYTHON:-python3}" "${SIMPLEFOLD_FINALIZE:-/app/revocompute/finalize.py}" \
  --output-dir "$output_dir" --model "$model" --num-steps "$num_steps" --tau "$tau" \
  --num-samples "$num_samples" --output-format "$output_format" --seed "$seed" \
  --predict-plddt "$predict_plddt" \
  --esm-model-sha256 "$esm_model_sha256" \
  --esm-regression-sha256 "$esm_regression_sha256"
touch "$output_dir/task_finished"
echo "SimpleFold prediction complete."
