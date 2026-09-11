#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
case "${1:-}" in
  muformer_encoder|musearch_tem1_muformer) asset_id=$1 ;;
  *) echo "Usage: $0 {muformer_encoder|musearch_tem1_muformer}" >&2; exit 2 ;;
esac
family_dir=$(cd -- "$(dirname -- "$0")" && pwd)
raw_root=${MU_PROTEIN_RAW_ROOT:-/mnt/db/weights/revocompute/mu_protein}
sanitized_root=${MU_PROTEIN_SANITIZED_ROOT:-/mnt/db/weights/revocompute/mu_protein/sanitized}
converter=${MU_PROTEIN_CONVERTER_SIF:-${family_dir}/mu_protein_converter_v1.sif}
[[ -f "$converter" ]] || { echo "Converter SIF not found: $converter" >&2; exit 1; }
mkdir -p "$sanitized_root"
exec apptainer exec --containall --cleanenv --no-home --net --network none --security no-new-privs \
  --bind "${raw_root}:/input:ro" --bind "${sanitized_root}:/output:rw" \
  "$converter" "$asset_id"
