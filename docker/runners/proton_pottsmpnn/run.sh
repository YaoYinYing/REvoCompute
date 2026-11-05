#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
runtime_root="${RUNNER_RUNTIME_ROOT:-/opt/revocompute/runtime}"
source "${TASK_CONTEXT_SRC:-$runtime_root/common/runtime/task_context.sh}"
while getopts ':i:o:' opt; do
  case "$opt" in i) task_file=$OPTARG ;; o) output_dir=$OPTARG ;; *) exit 2 ;; esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || { echo 'Usage: run.sh -i task.json -o output_dir' >&2; exit 2; }
complex=$(task_input complex)
[[ -f "$complex" ]] || { echo 'complex role input missing' >&2; exit 1; }
mkdir -p "$output_dir"
echo 'REVODESIGN_STAGE:model_loading'
echo 'REVODESIGN_STAGE:design'
python3 "$runtime_root/proton_pottsmpnn/adapter.py" "$complex" "$output_dir" "$task_file"
