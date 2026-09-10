#!/bin/bash
set -e
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"
usage() { echo "Usage: $0 -i <task.json> -o <output_dir>"; exit 1; }
while getopts ":i:o:" opt; do case "${opt}" in i) input_file=$OPTARG ;; o) output_dir=$OPTARG ;; ?) usage ;; esac; done
[[ -z "${input_file:-}" || -z "${output_dir:-}" ]] && usage
input_file=$(readlink -f "$input_file")
input_file=$(primary_input)

input_file=$(primary_input)
# ^ runner protocol v2: -i was the manifest; the real input comes from files[0].; output_dir=$(readlink -f "$output_dir")
[[ ! -f "$input_file" ]] && { echo "Input not found: $input_file"; exit 1; }
mkdir -p "$output_dir"

# BioEmu's upstream ColabFold helper derives its cache from pwd(3), which can
# vary with the scheduler account. Bridge that account-specific lookup to the
# stable, provisioned runtime path without naming a host user in the Runner.
runner_home=$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6 || true)
if [[ -n "$runner_home" && -d /mnt/models/.cache/colabfold ]]; then
  mkdir -p "$runner_home/.cache"
  ln -sfn /mnt/models/.cache/colabfold "$runner_home/.cache/colabfold"
fi

checkpoint_root=${BIOEMU_CHECKPOINT_ROOT:-/mnt/db/weights/bioemu/checkpoints/bioemu-v1.1}
checkpoint_path=${checkpoint_root}/checkpoint.ckpt
model_config_path=${checkpoint_root}/config.yaml
[[ -s "${checkpoint_path}" ]] || { echo "BioEmu checkpoint not found: ${checkpoint_path}" >&2; exit 1; }
[[ -s "${model_config_path}" ]] || { echo "BioEmu model config not found: ${model_config_path}" >&2; exit 1; }
runtime_cache=$(mktemp -d "${TMPDIR:-/tmp}/revodesign-bioemu.XXXXXX")
trap 'rm -rf -- "${runtime_cache}"' EXIT

NUM_SAMPLES="$(_parse_param num_samples)"
BATCH_SIZE_100="$(_parse_param batch_size_100)"
DENOISER_TYPE="$(_parse_param denoiser_type)"
FILTER_SAMPLES="$(_parse_param filter_samples)"

echo "REVODESIGN_STAGE:bioemu"
bioemu_args=(
  "$input_file"
  "$NUM_SAMPLES"
  "$output_dir"
  --batch_size_100="${BATCH_SIZE_100}"
  --model_name=None
  --ckpt_path="${checkpoint_path}"
  --model_config_path="${model_config_path}"
  --cache_embeds_dir="${runtime_cache}/embeds"
  --cache_so3_dir="${runtime_cache}/so3"
  --denoiser_type="${DENOISER_TYPE}"
  --filter_samples="${FILTER_SAMPLES}"
)
base_seed=$(_parse_param base_seed)
[[ -n "$base_seed" ]] && bioemu_args+=(--base_seed="$base_seed")
python3 -m bioemu.sample "${bioemu_args[@]}"

touch "${output_dir}/task_finished"
echo "BioEmu complete."
