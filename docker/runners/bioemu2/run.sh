#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
#
# BioEmu2 entrypoint. Delivered in the Runtime Bundle at
# /opt/revocompute/runtime/bioemu2/run.sh; the SIF is the environment only.

set -euo pipefail
runtime_root="${RUNNER_RUNTIME_ROOT:-/opt/revocompute/runtime}"

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
mkdir -p "$output_dir"

asset_root="${BIOEMU2_ASSET_ROOT:-/mnt/db/weights/bioemu2}"
checkpoint_dir="${BIOEMU2_CHECKPOINT_ROOT:-$asset_root/checkpoints/bioemu2-preview}"
asset_manifest="${BIOEMU2_ASSET_MANIFEST:-$runtime_root/bioemu2/model-assets.sha256}"

# shellcheck source=/dev/null
source "${MODEL_ASSET_VERIFY_SRC:-$runtime_root/common/runtime/verify_model_asset.sh}"
for relative in checkpoints/bioemu2-preview/checkpoint.ckpt checkpoints/bioemu2-preview/config.yaml; do
  verify_model_asset "$asset_manifest" "$asset_root" "$relative" BioEmu2 || exit 1
done

echo "REVODESIGN_STAGE:bioemu2_equilibrium"
"${BIOEMU2_PYTHON:-python}" "${BIOEMU2_SAMPLE_SCRIPT:-$runtime_root/bioemu2/sample.py}" \
  --task-manifest "$task_file" \
  --output-dir "$output_dir" \
  --checkpoint-dir "$checkpoint_dir"

# The task's own contract is the single list of required outputs; the server
# repeats this check, so a success here must mean the server's check will pass.
contract="${runtime_root}/bioemu2/tasks/bioemu2_equilibrium/expected_files.yaml"
required=$("${BIOEMU2_PYTHON:-python}" -c '
import sys, yaml
for entry in yaml.safe_load(open(sys.argv[1]))["result"]["files"].values():
    if entry.get("required"):
        print(entry["path"])
' "$contract") || { echo "BioEmu2 could not read the result contract: $contract" >&2; exit 1; }
[[ -n "$required" ]] || { echo "BioEmu2 contract declares no required output: $contract" >&2; exit 1; }
for published in $required; do
  [[ -s "$output_dir/$published" ]] || { echo "BioEmu2 did not publish $published" >&2; exit 1; }
done
touch "$output_dir/task_finished"
echo "BioEmu2 sampling complete."
