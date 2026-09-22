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

[[ "${TASK_TYPE:-}" == frodock ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
asset_root="${FRODOCK_ASSET_ROOT:-/mnt/db/weights/revocompute/frodock}"
asset_manifest="${FRODOCK_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}"
[[ -s "$asset_manifest" ]] || { echo "FRODOCK asset manifest is missing: $asset_manifest" >&2; exit 1; }
verify_model_asset "$asset_manifest" "$asset_root" "soap.bin" FRODOCK || exit 1

receptor=$(task_input receptor)
ligand=$(task_input ligand)
for partner in "$receptor" "$ligand"; do
    [[ -f "$partner" ]] || { echo "FRODOCK partner structure not found: $partner" >&2; exit 1; }
    case "${partner,,}" in
        *.pdb|*.ent) ;;
        *) echo "FRODOCK accepts PDB partner structures, not ${partner}" >&2; exit 1 ;;
    esac
done
[[ "$receptor" != "$ligand" ]] || { echo "FRODOCK receptor and ligand must be different files" >&2; exit 1; }

ligand_name="$(basename "${ligand%.*}")"

echo "REVODESIGN_STAGE:prepare_potentials"
echo "REVODESIGN_STAGE:dock"
python3 /app/revocompute/dock.py \
    --receptor "$receptor" \
    --ligand "$ligand" \
    --workspace "$output_dir/work" \
    --output-dir "$output_dir" \
    --ligand-name "$ligand_name"

echo "REVODESIGN_STAGE:normalize_results"
python3 /app/revocompute/normalize_results.py "$output_dir" --provenance "$output_dir/frodock-run.json"
test -s "$output_dir/poses.csv" || { echo "FRODOCK produced no ranked pose table" >&2; exit 1; }
test -s "$output_dir/summary.json" || { echo "FRODOCK produced no summary artifact" >&2; exit 1; }
test -s "$output_dir/clustered_solutions.dat" || { echo "FRODOCK produced no clustered solution file" >&2; exit 1; }
touch "$output_dir/task_finished"
