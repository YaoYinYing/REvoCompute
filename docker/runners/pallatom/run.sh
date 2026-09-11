#!/bin/bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail

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
[[ "${TASK_TYPE:-}" == "pallatom_generate" ]] || {
    echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2
    exit 1
}
task_file=$(readlink -f "$task_file")
output_dir=$(readlink -m "$output_dir")
[[ -f "$task_file" ]] || { echo "Task manifest not found: $task_file" >&2; exit 1; }
export TASK_MANIFEST="${TASK_MANIFEST:-$task_file}"
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

asset_root=${PALLATOM_ASSET_ROOT:-/mnt/db/weights/revocompute/pallatom}
checkpoint="${asset_root}/params/params_Pallatom.npz"
[[ -s "$checkpoint" ]] || { echo "Pallatom checkpoint is not provisioned at $checkpoint" >&2; exit 1; }
mkdir -p "$output_dir"

echo "REVODESIGN_STAGE:pallatom_generate"
"${PALLATOM_PYTHON:-python3}" "${PALLATOM_GENERATE_SCRIPT:-/app/revocompute/generate.py}" \
    --checkpoint "$checkpoint" \
    --output-dir "$output_dir" \
    --length "$(_parse_param length)" \
    --num-samples "$(_parse_param num_samples)" \
    --seed "$(_parse_param seed)" \
    --diffusion-steps "$(_parse_param diffusion_steps)" \
    --t-min "$(_parse_param t_min)" \
    --t-max "$(_parse_param t_max)" \
    --gamma "$(_parse_param gamma)" \
    --step-scale "$(_parse_param step_scale)"

test -s "$output_dir/sample_seq.fasta" || { echo "Pallatom produced no FASTA sequences" >&2; exit 1; }
compgen -G "$output_dir/design_*.pdb" >/dev/null || { echo "Pallatom produced no all-atom structures" >&2; exit 1; }
test -s "$output_dir/generation_metadata.json" || { echo "Pallatom produced no generation metadata" >&2; exit 1; }
touch "$output_dir/task_finished"
