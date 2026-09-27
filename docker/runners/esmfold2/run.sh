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
task_file=$(readlink -f "$task_file")
[[ -f "$task_file" ]] || { echo "Task manifest not found: $task_file" >&2; exit 1; }
output_dir=$(readlink -m "$output_dir")
asset_root="${ESMFOLD2_ASSET_ROOT:-/mnt/db/weights/revocompute/esmfold2}"
mkdir -p "$output_dir"

# One entrypoint invocation drives every work item: the entrypoint reads the
# named roles from the immutable task.json itself, so nothing here parses
# parameters or inputs. Each FASTA record is folded into its own work-item
# directory and committed atomically; per-item artifacts are validated in Python
# before the commit, so only the durable manifest is checked here.
echo "REVODESIGN_STAGE:esmfold2_predict"
"${ESMFOLD2_PYTHON:-python}" "${ESMFOLD2_PREDICT_SCRIPT:-/app/revocompute/predict.py}" \
  --task-manifest "$task_file" \
  --output-dir "$output_dir" \
  --asset-root "$asset_root"

[[ -s "$output_dir/work_items.json" ]] || { echo "ESMFold 2 wrote no durable work-item manifest" >&2; exit 1; }
touch "$output_dir/task_finished"
echo "ESMFold 2 prediction complete."
