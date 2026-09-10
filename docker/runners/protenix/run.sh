#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 2; }
while getopts ":i:o:" opt; do
  case "$opt" in
    i) task_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || usage
[[ -f "$task_file" ]] || { echo "Task manifest not found: $task_file" >&2; exit 1; }

output_dir=$(readlink -f "$output_dir")
asset_root="${PROTENIX_ASSET_ROOT:-/mnt/db/weights/revocompute/protenix}"
mkdir -p "$output_dir"

echo "REVODESIGN_STAGE:protenix_predict"
"${PROTENIX_PYTHON:-python3}" "${PROTENIX_PREDICT_SCRIPT:-/app/revocompute/predict.py}" \
  --task-manifest "$task_file" \
  --output-dir "$output_dir" \
  --asset-root "$asset_root"

test -s "$output_dir/prediction.json"
test -s "$output_dir/normalized_input.json"
find "$output_dir" -mindepth 3 -maxdepth 3 -type f -name '*_sample_*.cif' -size +0c -print -quit | grep -q . || {
  echo "Protenix-v2 produced no mmCIF structure artifact" >&2
  exit 1
}
find "$output_dir" -mindepth 3 -maxdepth 3 -type f -name '*_summary_confidence_sample_*.json' -size +0c -print -quit | grep -q . || {
  echo "Protenix-v2 produced no summary-confidence artifact" >&2
  exit 1
}
touch "$output_dir/task_finished"
