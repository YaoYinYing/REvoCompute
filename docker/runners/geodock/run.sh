#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail

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

asset_root=${GEODOCK_ASSET_ROOT:-/mnt/db/weights/revocompute/geodock}
asset_manifest=${GEODOCK_ASSET_MANIFEST:-/app/revocompute/model-assets.sha256}
[[ -s "$asset_manifest" ]] || { echo "GeoDock asset manifest is missing: $asset_manifest" >&2; exit 1; }
for asset in dips_0.3.ckpt esm2_t33_650M_UR50D.pt esm2_t33_650M_UR50D-contact-regression.pt; do
  [[ -s "$asset_root/$asset" ]] || { echo "GeoDock asset is missing: $asset_root/$asset" >&2; exit 1; }
done
(cd "$asset_root" && sha256sum --strict --check --status "$asset_manifest") || {
  echo "GeoDock asset integrity verification failed: $asset_manifest" >&2
  exit 1
}
[[ "${TASK_TYPE:-}" == geodock ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }

echo "REVODESIGN_STAGE:geodock"
python_bin=${GEODOCK_PYTHON:-python3}
launcher=${GEODOCK_LAUNCHER:-/app/revocompute/launch.py}
"$python_bin" "$launcher" --manifest "$task_manifest" --output-dir "$output_dir" --asset-root "$asset_root"

[[ -s "$output_dir/geodock_raw.pdb" ]] || { echo "GeoDock produced no raw docked PDB" >&2; exit 1; }
[[ -s "$output_dir/geodock-confidence.json" ]] || { echo "GeoDock produced no confidence artifact" >&2; exit 1; }
[[ -s "$output_dir/geodock-run.json" ]] || { echo "GeoDock produced no provenance artifact" >&2; exit 1; }
cp "$asset_manifest" "$output_dir/geodock-model-assets.sha256"
touch "$output_dir/task_finished"
