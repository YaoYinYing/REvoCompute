#!/bin/bash
set -e
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"
while getopts ":i:o:" opt; do case "$opt" in i) input_file=$OPTARG;; o) output_dir=$OPTARG;; *) exit 1;; esac; done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || exit 1
input_file=$(readlink -f "$input_file"); input_file=$(primary_input)
output_dir=$(readlink -f "$output_dir"); mkdir -p "$output_dir"
checkpoint_name=$(_parse_param checkpoint)
case "$checkpoint_name" in
  fireprot) checkpoint="${FRUSTRAMPNN_WEIGHT_DIR}/fireprot_train_weights.ckpt";;
  megascale) checkpoint="${FRUSTRAMPNN_WEIGHT_DIR}/megascale_train_weights.ckpt";;
  *) echo "Unknown frustraMPNN checkpoint: $checkpoint_name" >&2; exit 1;;
esac
[[ -s "$checkpoint" ]] || { echo "Missing frustraMPNN checkpoint: $checkpoint" >&2; exit 1; }
args=(predict --pdb "$input_file" --checkpoint "$checkpoint" --output "$output_dir/frustration_predictions.csv" --device cpu)
for key in chains positions; do value=$(_parse_param "$key"); [[ -z "$value" ]] || args+=(--"$key" "$value"); done
[[ "$(_parse_param quiet)" == true ]] && args+=(--quiet)
echo "REVODESIGN_STAGE:frustrampnn"
frustrampnn "${args[@]}"
[[ -s "$output_dir/frustration_predictions.csv" ]] || { echo "frustraMPNN produced no prediction table" >&2; exit 1; }
touch "$output_dir/task_finished"
