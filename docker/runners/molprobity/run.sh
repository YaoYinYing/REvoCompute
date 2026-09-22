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

[[ "${TASK_TYPE:-}" == molprobity_validate ]] || {
    echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2
    exit 1
}

asset_root="${MOLPROBITY_ASSET_ROOT:-/mnt/db/weights/revocompute/molprobity}"
asset_manifest="${MOLPROBITY_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}"
[[ -s "$asset_manifest" ]] || { echo "MolProbity asset manifest is missing: $asset_manifest" >&2; exit 1; }
for directory in chem_data/rotarama_data chem_data/geostd; do
    [[ -d "$asset_root/$directory" ]] || { echo "MolProbity reference data is missing: $directory" >&2; exit 1; }
done
(cd "$asset_root/chem_data" && sha256sum --strict --check --status --quiet "$asset_manifest") || {
    echo "MolProbity reference data integrity verification failed" >&2
    exit 1
}

structure=$(task_input structure)
[[ -f "$structure" ]] || { echo "MolProbity input structure not found: $structure" >&2; exit 1; }
case "${structure,,}" in
    *.pdb|*.ent|*.cif|*.mmcif) ;;
    *) echo "MolProbity accepts a protein PDB or mmCIF structure, not ${structure}" >&2; exit 1 ;;
esac

echo "REVODESIGN_STAGE:validate_structure"
python3 /app/revocompute/validate.py \
    --input "$structure" \
    --output-dir "$output_dir" \
    --asset-root "$asset_root" \
    --asset-manifest "$asset_manifest" \
    --source-revision a978d97aad5efd33b594591fb1cfb0f7fa4f5b24

test -s "$output_dir/molprobity.json" || { echo "MolProbity produced no validation summary" >&2; exit 1; }
test -s "$output_dir/validation_residues.csv" || { echo "MolProbity produced no per-residue table" >&2; exit 1; }
touch "$output_dir/task_finished"
