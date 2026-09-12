#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
source "${MODEL_ASSET_VERIFY_SRC:-/app/revocompute/verify_model_asset.sh}"

# RFdiffusion2's upstream config interpolates USER for its W&B path.  The
# isolated SLURM environment may omit it, so provide a non-sensitive fallback.
export USER="${USER:-revodesign}"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 1; }
while getopts ":i:o:" opt; do
  case "$opt" in
    i) task_manifest=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${task_manifest:-}" && -n "${output_dir:-}" ]] || usage

task_manifest=$(readlink -f "$task_manifest")
output_dir=$(readlink -m "$output_dir")
[[ -f "$task_manifest" ]] || { echo "Task manifest not found: $task_manifest" >&2; exit 1; }
mkdir -p "$output_dir"

asset_root=${RFDIFFUSION2_ASSET_ROOT:-/mnt/db/weights/revocompute/rfdiffusion2}
asset_manifest=${RFDIFFUSION2_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}
checkpoint="${asset_root}/RFD_173.pt"
verify_model_asset "$asset_manifest" "$asset_root" "RFD_173.pt" RFdiffusion2

case "${TASK_TYPE:-}" in
  rfdiffusion2_motif_scaffold|rfdiffusion2_ligand_binder) ;;
  *) echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1 ;;
esac

echo "REVODESIGN_STAGE:${TASK_TYPE}"
python_bin=${RFDIFFUSION2_PYTHON:-python3}
launcher=${RFDIFFUSION2_LAUNCHER:-/app/revocompute/launch.py}
"$python_bin" "$launcher" \
  --task-type "$TASK_TYPE" \
  --manifest "$task_manifest" \
  --output-dir "$output_dir" \
  --checkpoint "$checkpoint"

find "$output_dir" -maxdepth 1 -type f -name 'design_*.pdb' -size +0c -print -quit | grep -q . || {
  echo "RFdiffusion2 produced no designed PDB structure" >&2
  exit 1
}
find "$output_dir" -maxdepth 1 -type f -name 'design_*.trb' -size +0c -print -quit | grep -q . || {
  echo "RFdiffusion2 produced no TRB provenance output" >&2
  exit 1
}
cp "$asset_manifest" "$output_dir/rfdiffusion2-model-assets.sha256"
touch "$output_dir/task_finished"
