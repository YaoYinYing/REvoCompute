#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
#
# TEST/REFERENCE-ONLY entrypoint. It hands the immutable task.json to
# mockfold.py, which normalizes the FASTA into one work item per record and runs
# the shared lifecycle: initialize once, commit each item, resume from
# work_items.json, continue after an item-level failure, and walk the declared
# bounded fallback ladder on a real (pseudo-device) OOM. No GPU is touched.
#
# This script is delivered in the Runtime Bundle at
# /opt/revocompute/runtime/mock_gpu_example/run.sh, not baked into the SIF. The
# tests point RUNNER_RUNTIME_ROOT / TASK_CONTEXT_SRC at the repository copies.

set -euo pipefail
runtime_root="${RUNNER_RUNTIME_ROOT:-/opt/revocompute/runtime}"
task_context_src="${TASK_CONTEXT_SRC:-$runtime_root/common/runtime/task_context.sh}"
# shellcheck source=/dev/null
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

input_file=$(task_input sequence)
output_dir=$(readlink -f "$output_dir")
[[ -f "$input_file" ]] || { echo "Input FASTA not found: $input_file" >&2; exit 1; }
mkdir -p "$output_dir"

folder="${MOCKFOLD_FOLDER:-$runtime_root/mock_gpu_example/mockfold.py}"
# The shared lifecycle modules sit beside the family script in the bundle.
shared_dir="${MOCKFOLD_SHARED_DIR:-$runtime_root/common/runtime}"
export PYTHONPATH="$shared_dir${PYTHONPATH:+:$PYTHONPATH}"

python3 "$folder" task "$task_file" "$output_dir"

[[ -s "$output_dir/work_items.json" ]] || { echo "Mock folding wrote no durable work-item manifest" >&2; exit 1; }
