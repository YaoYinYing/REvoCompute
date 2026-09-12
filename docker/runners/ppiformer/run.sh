#!/bin/bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 1; }
while getopts ":i:o:" opt; do
    case "$opt" in i) task_file=$OPTARG ;; o) output_dir=$OPTARG ;; *) usage ;; esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || usage
task_file=$(readlink -f "$task_file")
output_dir=$(readlink -m "$output_dir")
[[ -f "$task_file" ]] || { echo "Task manifest not found: $task_file" >&2; exit 1; }
export TASK_MANIFEST="${TASK_MANIFEST:-$task_file}"
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

input_file=$(primary_input)
[[ -f "$input_file" ]] || { echo "PPI structure not found: $input_file" >&2; exit 1; }
asset_root=${PPIFORMER_ASSET_ROOT:-/mnt/db/weights/revocompute/ppiformer}
mkdir -p "$output_dir"
scratch_dir=$(mktemp -d "${TMPDIR:-/tmp}/ppiformer.XXXXXX")
trap 'rm -rf "$scratch_dir"' EXIT

export HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= http_proxy= https_proxy= all_proxy= NO_PROXY= no_proxy=
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 WANDB_MODE=disabled
echo "REVODESIGN_STAGE:${TASK_TYPE:-unset}"
common=(--input "$input_file" --output-dir "$output_dir" --asset-root "$asset_root" --scratch-dir "$scratch_dir")
case "${TASK_TYPE:-}" in
    ppiformer_ddg)
        "${PPIFORMER_PYTHON:-python3}" "${PPIFORMER_PREDICT_SCRIPT:-/app/revocompute/predict.py}" \
            ddg "${common[@]}" --mutations "$(_parse_param mutations)" --impute-missing "$(_parse_param impute_missing)"
        test -s "$output_dir/ddg_predictions.csv"
        ;;
    ppiformer_embed)
        "${PPIFORMER_PYTHON:-python3}" "${PPIFORMER_PREDICT_SCRIPT:-/app/revocompute/predict.py}" embed "${common[@]}"
        test -s "$output_dir/residue_embeddings.npy"
        test -s "$output_dir/interface_embedding.npy"
        test -s "$output_dir/residue_index.csv"
        test -s "$output_dir/embedding_summary.json"
        ;;
    *) echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1 ;;
esac
test -s "$output_dir/run_metadata.json"
touch "$output_dir/task_finished"
