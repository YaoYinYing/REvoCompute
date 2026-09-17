#!/usr/bin/env bash
# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

while getopts ":i:o:" opt; do
  case "$opt" in
    i) task_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) exit 1 ;;
  esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || { echo "Usage: run.sh -i task.json -o OUTPUT_DIR" >&2; exit 1; }

# Runner protocol v3: the scheduler exports TASK_MANIFEST. Keep -i as a
# documented fallback so the Runner is runnable outside the scheduler too.
export TASK_MANIFEST="${TASK_MANIFEST:-$task_file}"
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
# shellcheck disable=SC1090
[[ -f "$task_context_src" ]] && source "$task_context_src"

input_file=$(task_input alignment)
[[ -f "$input_file" ]] || { echo "GREMLIN_LH alignment input not found: $input_file" >&2; exit 1; }
mkdir -p "$output_dir"
output_dir=$(readlink -f "$output_dir")

[[ "${TASK_TYPE:-}" == "gremlin_lh_fit" ]] || { echo "Unknown TASK_TYPE: ${TASK_TYPE:-}" >&2; exit 1; }
echo "REVODESIGN_STAGE:gremlin_lh_fit"
"${GREMLIN_LH_PYTHON:-python3}" "${GREMLIN_LH_FIT_MODEL:-/app/revocompute/fit_model.py}" \
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

for artifact in \
  summary.json \
  query.fasta \
  alignment/filtered_alignment.a3m \
  alignment/statistics.json \
  alignment/sequence_weights.tsv \
  model/gremlin_mrf.npz \
  model/metadata.json \
  model/training_history.csv \
  model/sequence_scores.tsv \
  profiles/profile.tsv \
  couplings/pairwise_scores.tsv \
  couplings/raw_scores.csv \
  couplings/apc_scores.csv \
  plots/coupling_apc.png; do
  [[ -s "$output_dir/$artifact" ]] || { echo "GREMLIN_LH did not produce required artifact: $artifact" >&2; exit 1; }
done
touch "$output_dir/task_finished"
