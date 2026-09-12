#!/usr/bin/env bash
# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
# shellcheck disable=SC1090
[[ -f "$task_context_src" ]] && source "$task_context_src"

while getopts ":i:o:" opt; do
  case "$opt" in
    i) input_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) exit 1 ;;
  esac
done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || { echo "Usage: run.sh -i MSA -o OUTPUT_DIR" >&2; exit 1; }
input_file=$(readlink -f "$input_file")
input_file=$(primary_input)
output_dir=$(readlink -f "$output_dir")
mkdir -p "$output_dir"

[[ "${TASK_TYPE:-}" == "gremlin_lh_fit" ]] || { echo "Unknown TASK_TYPE: ${TASK_TYPE:-}" >&2; exit 1; }
echo "REVODESIGN_STAGE:gremlin_lh_fit"
python3 /app/revocompute/fit_model.py \
  --input "$input_file" \
  --output-dir "$output_dir" \
  --regularization "$(_parse_param regularization)" \
  --lambda-l2 "$(_parse_param lambda_l2)" \
  --lambda-lh "$(_parse_param lambda_lh)" \
  --lambda-lb "$(_parse_param lambda_lb)" \
  --iterations "$(_parse_param iterations)" \
  --batch-size "$(_parse_param batch_size)" \
  --learning-rate "$(_parse_param learning_rate)" \
  --identity-cutoff "$(_parse_param identity_cutoff)" \
  --gap-cutoff "$(_parse_param gap_cutoff)" \
  --use-bias "$(_parse_param use_bias)" \
  --inverse-covariance-init "$(_parse_param inverse_covariance_init)" \
  --exact-lh-eigenvalue "$(_parse_param exact_lh_eigenvalue)" \
  --a3m "$(_parse_param a3m)" \
  --seed "$(_parse_param seed)"

for artifact in potts_model.npz coupling_raw.csv coupling_apc.csv coupling_pairs.csv position_frequencies.csv \
  sequence_scores.csv training_history.csv normalized_alignment.fasta summary.json coupling_apc.png; do
  [[ -s "$output_dir/$artifact" ]] || { echo "GREMLIN_LH did not produce required artifact: $artifact" >&2; exit 1; }
done
touch "$output_dir/task_finished"
