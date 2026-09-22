#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 1; }
while getopts ":i:o:" opt; do
    case "$opt" in
        i) task_file=$OPTARG ;;
        o) output_dir=$OPTARG ;;
        *) usage ;;
    esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || usage

task_file=$(readlink -f "$task_file")
output_dir=$(readlink -m "$output_dir")
[[ -f "$task_file" ]] || { echo "Task manifest not found: $task_file" >&2; exit 1; }
mkdir -p "$output_dir"
export TASK_MANIFEST=$task_file

task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
# shellcheck source=/dev/null
[[ -f "$task_context_src" ]] && source "$task_context_src"

[[ "${TASK_TYPE:-}" == fpocket ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }

structure=$(task_input structure)
[[ -f "$structure" ]] || { echo "fpocket input structure not found: $structure" >&2; exit 1; }
case "${structure,,}" in
    *.pdb|*.cif|*.mmcif|*.ent) ;;
    *) echo "fpocket accepts a protein PDB or mmCIF structure, not ${structure}" >&2; exit 1 ;;
esac

# fpocket writes <stem>_out/ beside its input and has no output-directory flag.
work_dir="$output_dir/work"
mkdir -p "$work_dir"
cp "$structure" "$work_dir/"
input_name=$(basename "$structure")
stem="${input_name%.*}"

echo "REVODESIGN_STAGE:detect_pockets"
python3 /app/revocompute/detect.py \
    --input "$input_name" \
    --workspace "$work_dir" \
    --output-dir "$output_dir"

run_dir="$work_dir/${stem}_out"
[[ -d "$run_dir" ]] || { echo "fpocket produced no output directory: ${stem}_out" >&2; exit 1; }
[[ -s "$run_dir/${stem}_info.txt" ]] || { echo "fpocket produced no pocket info file" >&2; exit 1; }
[[ -d "$run_dir/pockets" ]] || { echo "fpocket produced no pocket directory" >&2; exit 1; }

echo "REVODESIGN_STAGE:normalize_results"
python3 /app/revocompute/normalize_results.py "$output_dir" --provenance "$output_dir/fpocket-run.json"
test -s "$output_dir/pockets.csv" || { echo "fpocket produced no normalized pocket table" >&2; exit 1; }
test -s "$output_dir/summary.json" || { echo "fpocket produced no summary artifact" >&2; exit 1; }
touch "$output_dir/task_finished"
