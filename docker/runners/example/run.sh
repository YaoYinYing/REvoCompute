#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
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
[[ -f "$input_file" ]] || { echo "Input FASTA not found" >&2; exit 1; }
mkdir -p "$output_dir"

echo "REVODESIGN_STAGE:sequence_statistics"
python3 "${EXAMPLE_ANALYZER:-/app/revocompute/analyze.py}" \
    --input "$input_file" \
    --output-dir "$output_dir" \
    --mass-precision "$(_parse_param mass_precision)"
test -s "$output_dir/sequence_statistics.tsv"
test -s "$output_dir/summary.json"
touch "$output_dir/task_finished"
