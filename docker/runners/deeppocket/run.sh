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

[[ "${TASK_TYPE:-}" == deeppocket ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }

asset_root="${DEEPPOCKET_ASSET_ROOT:-/mnt/db/weights/deeppocket}"
asset_manifest="${DEEPPOCKET_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}"
[[ -s "$asset_manifest" ]] || { echo "DeepPocket asset manifest is missing: $asset_manifest" >&2; exit 1; }
for relative in \
    checkpoints/classification_models/first_model_fold1_best_test_auc_85001.pth.tar \
    checkpoints/segmentation_models/seg0_best_test_IOU_91.pth.tar; do
    verify_model_asset "$asset_manifest" "$asset_root" "$relative" DeepPocket || exit 1
done

structure=$(task_input structure)
[[ -f "$structure" ]] || { echo "DeepPocket input structure not found: $structure" >&2; exit 1; }
case "${structure,,}" in
    *.pdb|*.ent) ;;
    *) echo "DeepPocket accepts a protein PDB structure, not ${structure}" >&2; exit 1 ;;
esac

# DeepPocket's upstream scripts resolve their neighbours and write beside their
# input file, so all work happens inside the task workspace.
work_dir="$output_dir/work"
mkdir -p "$work_dir"
cp "$structure" "$work_dir/"
input_name=$(basename "$structure")

echo "REVODESIGN_STAGE:detect_pockets"
python3 /app/revocompute/predict.py \
    --structure "$work_dir/$input_name" \
    --name "$input_name" \
    --workspace "$work_dir" \
    --output-dir "$output_dir" \
    --asset-root "$asset_root"

echo "REVODESIGN_STAGE:normalize_results"
python3 /app/revocompute/normalize_results.py "$output_dir" --provenance "$output_dir/deeppocket-run.json"
cp "$asset_manifest" "$output_dir/deeppocket-model-assets.sha256"

test -s "$output_dir/pockets.csv" || { echo "DeepPocket produced no reranked pocket table" >&2; exit 1; }
test -s "$output_dir/residues.csv" || { echo "DeepPocket produced no segmented residue table" >&2; exit 1; }
test -s "$output_dir/summary.json" || { echo "DeepPocket produced no summary artifact" >&2; exit 1; }
touch "$output_dir/task_finished"
