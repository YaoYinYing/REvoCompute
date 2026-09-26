#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
#
# Reference persistent Runner entrypoint. It hands the immutable task.json to
# analyze.py, which normalizes the FASTA into one work item per record and runs
# the shared lifecycle: initialize once, commit each item, resume from
# work_items.json, continue after an item-level failure. Everything the runner
# needs from the manifest is read through the named-role helpers below.

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

# The named input role, not a positional file; analyze.py reads the
# server-resolved parameters from the same immutable manifest.
input_file=$(task_input sequence)
output_dir=$(readlink -f "$output_dir")
[[ -f "$input_file" ]] || { echo "Input FASTA not found: $input_file" >&2; exit 1; }
mkdir -p "$output_dir"

analyzer="${EXAMPLE_ANALYZER:-/app/revocompute/analyze.py}"
# In the image the shared lifecycle modules sit beside the family script; the
# tests point this at the repository's `common/` directory instead.
shared_dir="${EXAMPLE_SHARED_DIR:-$(dirname "$analyzer")}"
export PYTHONPATH="$shared_dir${PYTHONPATH:+:$PYTHONPATH}"

python3 "$analyzer" task "$task_file" "$output_dir"
