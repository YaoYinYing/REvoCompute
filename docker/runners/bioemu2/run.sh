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
steering_ccd="${BIOEMU2_STEERING_CCD:-$asset_root/steering/boltz-1-ccd.pkl}"
steering_manifest="${BIOEMU2_STEERING_CCD_MANIFEST:-$runtime_root/bioemu2/steering-ccd.sha256}"
export BIOEMU2_STEERING_CCD="$steering_ccd"
export BIOEMU2_STEERING_CCD_MANIFEST="$steering_manifest"

# shellcheck source=/dev/null
source "${MODEL_ASSET_VERIFY_SRC:-$runtime_root/common/runtime/verify_model_asset.sh}"
for relative in checkpoints/bioemu2-preview/checkpoint.ckpt checkpoints/bioemu2-preview/config.yaml; do
  verify_model_asset "$asset_manifest" "$asset_root" "$relative" BioEmu2 || exit 1
done

# The Task's scientific mode is a parameter, not a Task identity. Reading it
# from the immutable manifest keeps one dispatch path for all three modes.
task_type="${TASK_TYPE:-bioemu2}"
if [[ "$task_type" != "bioemu2" ]]; then
  # The legacy equilibrium/structure/propagation descriptors stay registered
  # only so historical results resolve. They carry no `mode` parameter, so
  # executing one would silently guess its science; refuse instead.
  echo "BioEmu2 Task ${task_type} is retired; resubmit it as bioemu2" >&2
  exit 2
fi
mode=$("${BIOEMU2_PYTHON:-python}" -c '
import json, sys
params = json.load(open(sys.argv[1])).get("params", {})
mode = params.get("mode")
if mode not in ("equilibrium", "structure_prediction", "propagate"):
    raise SystemExit(f"BioEmu2 Task manifest declares no valid mode: {mode!r}")
print(mode)
' "$task_file") || { echo "BioEmu2 could not read the Task mode" >&2; exit 1; }
case "$mode" in
  equilibrium|structure_prediction|propagate) ;;
  *) echo "Unknown BioEmu2 mode: $mode" >&2; exit 2 ;;
esac

echo "REVODESIGN_STAGE:${task_type}"
"${BIOEMU2_PYTHON:-python}" "${BIOEMU2_SAMPLE_SCRIPT:-$runtime_root/bioemu2/sample.py}" \
  --task-manifest "$task_file" \
  --output-dir "$output_dir" \
  --checkpoint-dir "$checkpoint_dir"

# The task's own contract is the single list of required outputs; the server
# repeats this check, so a success here must mean the server's check will pass.
# A Task-scoped contract wins; every mode of the unified Task shares it.
contract="${runtime_root}/bioemu2/tasks/${task_type}/expected_files.yaml"
[[ -f "$contract" ]] || contract="${runtime_root}/bioemu2/expected_files.yaml"
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
