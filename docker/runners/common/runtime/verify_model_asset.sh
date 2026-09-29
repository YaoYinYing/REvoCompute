#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

verify_model_asset() {
  local manifest=$1 root=$2 relative=$3 label=$4 expected checkpoint
  checkpoint="${root}/${relative}"
  [[ -s "$manifest" ]] || { echo "${label} asset manifest is missing" >&2; return 1; }
  [[ -s "$checkpoint" ]] || { echo "${label} asset is missing: ${relative}" >&2; return 1; }
  expected=$(awk -v file="$relative" '$2 == file { print $1 }' "$manifest")
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || { echo "${label} asset identity is undeclared: ${relative}" >&2; return 1; }
  printf '%s  %s\n' "$expected" "$checkpoint" | sha256sum --strict --check --status || {
    echo "${label} asset integrity verification failed: ${relative}" >&2
    return 1
  }
}
