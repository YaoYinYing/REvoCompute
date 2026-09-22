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

# shellcheck source=/dev/null
source "${MODEL_ASSET_VERIFY_SRC:-/app/revocompute/verify_model_asset.sh}"

[[ "${TASK_TYPE:-}" == p2rank ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
asset_root="${P2RANK_ASSET_ROOT:-/mnt/db/weights/revocompute/p2rank}"
asset_manifest="${P2RANK_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}"
[[ -s "$asset_manifest" ]] || { echo "P2Rank asset manifest is missing: $asset_manifest" >&2; exit 1; }
for relative in \
    default/model.zst \
    default/features.txt \
    _score_transform/default_ZscoreTpTransformer.json \
    _score_transform/default_ProbabilityScoreTransformer.json \
    _score_transform/residue/default_ZscoreTpTransformer.json \
    _score_transform/residue/default_ProbabilityScoreTransformer.json; do
    verify_model_asset "$asset_manifest" "$asset_root" "$relative" P2Rank || exit 1
done

structure=$(task_input structure)
[[ -f "$structure" ]] || { echo "P2Rank input structure not found: $structure" >&2; exit 1; }
case "${structure,,}" in
    *.pdb|*.cif|*.mmcif|*.ent) ;;
    *) echo "P2Rank accepts a protein PDB or mmCIF structure, not ${structure}" >&2; exit 1 ;;
esac

work_dir="$output_dir/work"
mkdir -p "$work_dir"
cp "$structure" "$work_dir/"
input_name=$(basename "$structure")

echo "REVODESIGN_STAGE:detect_pockets"
python3 /app/revocompute/predict.py \
    --structure "$work_dir/$input_name" \
    --name "$input_name" \
    --output-dir "$output_dir" \
    --asset-root "$asset_root"

echo "REVODESIGN_STAGE:normalize_results"
python3 /app/revocompute/normalize_results.py "$output_dir" --provenance "$output_dir/p2rank-run.json"
cp "$asset_manifest" "$output_dir/p2rank-model-assets.sha256"

test -s "$output_dir/pockets.csv" || { echo "P2Rank produced no normalized pocket table" >&2; exit 1; }
test -s "$output_dir/residue_scores.csv" || { echo "P2Rank produced no normalized residue table" >&2; exit 1; }
test -s "$output_dir/summary.json" || { echo "P2Rank produced no summary artifact" >&2; exit 1; }
touch "$output_dir/task_finished"
