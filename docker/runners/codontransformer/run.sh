#!/bin/bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

usage() {
    echo "Usage: $0 -i <task.json> -o <output_dir>" >&2
    exit 1
}

while getopts ":i:o:" opt; do
    case "$opt" in
        i) task_file=$OPTARG ;;
        o) output_dir=$OPTARG ;;
        *) usage ;;
    esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || usage

input_file=$(primary_input)
output_dir=$(readlink -f "$output_dir")
model_dir=${CODONTRANSFORMER_MODEL_DIR:-/mnt/db/weights/revocompute/codontransformer/model}
[[ -f "$input_file" ]] || { echo "Input FASTA not found: $input_file" >&2; exit 1; }
[[ -f "$model_dir/model.safetensors" ]] || { echo "CodonTransformer model is not provisioned at $model_dir" >&2; exit 1; }
mkdir -p "$output_dir"

args=(
    --input "$input_file"
    --output-dir "$output_dir"
    --model-dir "$model_dir"
    --organism "$(_parse_param organism)"
    --attention-type "$(_parse_param attention_type)"
    --temperature "$(_parse_param temperature)"
    --top-p "$(_parse_param top_p)"
    --num-sequences "$(_parse_param num_sequences)"
    --seed "$(_parse_param seed)"
)
[[ "$(_parse_param deterministic)" == "true" ]] && args+=(--deterministic)
[[ "$(_parse_param match_protein)" == "true" ]] && args+=(--match-protein)

echo "REVODESIGN_STAGE:codon_optimize"
python /app/revocompute/predict.py "${args[@]}"
test -s "$output_dir/optimized_sequences.fasta"
test -s "$output_dir/results.json"
touch "$output_dir/task_finished"
