#!/bin/bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

set -euo pipefail
runtime_root="${RUNNER_RUNTIME_ROOT:-/opt/revocompute/runtime}"
task_context_src="${TASK_CONTEXT_SRC:-$runtime_root/common/runtime/task_context.sh}"
[[ -f "$task_context_src" ]] || { echo "Task context helpers not found: $task_context_src" >&2; exit 1; }
source "$task_context_src"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 2; }
while getopts ":i:o:" opt; do
  case "$opt" in
    i) input_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || usage
[[ "${TASK_TYPE:-}" == "mol1_predict" ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
input_file=$(readlink -f "$input_file")
output_dir=$(readlink -m "$output_dir")
[[ -f "$input_file" ]] || { echo "Task manifest not found: $input_file" >&2; exit 1; }
mkdir -p "$output_dir"

mol_root=${MOL_ROOT_DIR:-/mnt/db/mol1}
checkpoint=${MOL1_CHECKPOINT:-$mol_root/checkpoint/mol-1-base.pt}
mol_cli=${MOL_CLI:-/opt/venv/bin/mol}
prepare_input=${MOL1_PREPARE_INPUT:-$runtime_root/mol1/prepare_input.py}
upstream=${MOL1_UPSTREAM:-/app/revocompute/upstream.json}
model_manifest=${MOL1_MODEL_MANIFEST:-/app/revocompute/model-assets.sha256}
search_manifest=${MOL1_SEARCH_MANIFEST:-/app/revocompute/search-assets.sha256}
search_timeout=${MOL1_SEARCH_TIMEOUT:-3600}

msa_mode=$(_parse_param msa_mode)
template_mode=$(_parse_param template_mode)
rna_msa_mode=$(_parse_param rna_msa_mode)
num_samples=$(_parse_param num_samples)
num_recycles=$(_parse_param num_recycles)
diffusion_steps=$(_parse_param diffusion_steps)
seeds=$(_parse_param sample_seeds)
need_atom_confidence=$(_parse_param need_atom_confidence)

[[ -x "$mol_cli" ]] || { echo "Mol-1 CLI is not executable: $mol_cli" >&2; exit 1; }
[[ -s "$checkpoint" ]] || { echo "Mol-1 checkpoint is missing: $checkpoint" >&2; exit 1; }
[[ -s "$upstream" ]] || { echo "Mol-1 upstream identity is missing: $upstream" >&2; exit 1; }
[[ -s "$model_manifest" ]] || { echo "Mol-1 asset manifest is missing: $model_manifest" >&2; exit 1; }

# Every always-required asset is verified before any model work. Template
# reference data is verified whenever templates are enabled, because supplied
# templates also read the release-date and obsolete-PDB indexes.
(cd "$mol_root" && sha256sum --strict --check --status "$model_manifest") || {
  echo "Mol-1 model asset integrity verification failed" >&2; exit 1
}
if [[ "$template_mode" != "none" ]]; then
  [[ -s "$search_manifest" ]] || { echo "Mol-1 template asset manifest is missing: $search_manifest" >&2; exit 1; }
  (cd "$mol_root" && sha256sum --strict --check --status "$search_manifest") || {
    echo "Mol-1 template asset integrity verification failed" >&2; exit 1
  }
fi

# Template feasibility downloads hit structures from PDBe into
# $MOL_ROOT_DIR/mmcif. The operator's mount is read-only, so expose it through
# a task-private writable root whose other entries are symlinks to the mount.
# The task scratch (/tmp) disappears with the allocation.
writable_root=$(mktemp -d "${TMPDIR:-/tmp}/mol1-runtime.XXXXXX")
trap 'rm -rf -- "$writable_root"' EXIT
mkdir -p "$writable_root/mmcif"
for entry in checkpoint common search_database; do
  [[ -e "$mol_root/$entry" ]] && ln -s "$mol_root/$entry" "$writable_root/$entry"
done
export MOL_ROOT_DIR="$writable_root"
export LAYERNORM_TYPE="${LAYERNORM_TYPE:-torch}"
export PYTHONNOUSERSITE=1 WANDB_MODE=disabled HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export XDG_CACHE_HOME=/tmp/.cache TORCH_EXTENSIONS_DIR=/tmp/.torch-extensions

echo "REVODESIGN_STAGE:input_preparation"
prepared=$(python3 "$prepare_input" prepare "$TASK_MANIFEST" "$output_dir/normalized_inputs")
current=$prepared

# The upstream MSA client retries a connection error forever, so search is a
# bounded step and its service is probed first. Prediction then runs only on an
# input whose paths are all present, which keeps it off every search path.
preflight_msa() {
  local service
  service=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["msa_service"])' "$upstream")
  python3 - "$service" <<'PY'
import sys
import urllib.error
import urllib.request

try:
    urllib.request.urlopen(sys.argv[1], timeout=15)
except urllib.error.HTTPError:
    pass
except Exception as exc:
    print(f"Mol-1 MSA service is unreachable: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
}

if [[ "$msa_mode" == "search" || "$template_mode" == "search" ]]; then
  echo "REVODESIGN_STAGE:msa_template_preparation"
fi
if [[ "$msa_mode" == "search" ]]; then
  preflight_msa || { echo "Mol-1 MSA search refused: the service is unreachable" >&2; exit 1; }
  if ! timeout --signal=TERM --kill-after=60 "$search_timeout" \
      "$mol_cli" msa -i "$current" -o "$output_dir/mol1_preparation/msa"; then
    echo "Mol-1 MSA search failed or exceeded ${search_timeout}s" >&2; exit 1
  fi
  # Upstream writes an updated JSON only when at least one chain needed a
  # search; an input that already carries every MSA stays as it is.
  if [[ -s "$output_dir/normalized_inputs/normalized-input-update-msa.json" ]]; then
    current="$output_dir/normalized_inputs/normalized-input-update-msa.json"
  else
    echo "No protein chain needed an MSA search."
  fi
fi
if [[ "$template_mode" == "search" ]]; then
  if ! timeout --signal=TERM --kill-after=60 "$search_timeout" \
      "$mol_cli" prep -i "$current" -o "$output_dir/mol1_preparation/templates"; then
    echo "Mol-1 template search failed or exceeded ${search_timeout}s" >&2; exit 1
  fi
  if [[ -s "$output_dir/normalized_inputs/normalized-input-final-updated.json" ]]; then
    current="$output_dir/normalized_inputs/normalized-input-final-updated.json"
  else
    echo "No protein chain needed a template search."
  fi
fi

python3 "$prepare_input" verify "$current" \
  --msa-mode "$msa_mode" --template-mode "$template_mode" --rna-msa-mode "$rna_msa_mode"

use_msa=false
[[ "$msa_mode" != "none" ]] && use_msa=true
use_template=false
[[ "$template_mode" != "none" ]] && use_template=true
use_rna_msa=false
[[ "$rna_msa_mode" == "supply" ]] && use_rna_msa=true

echo "REVODESIGN_STAGE:inference"
mol_args=(
  pred -i "$current" -o "$output_dir"
  --load_checkpoint_path "$checkpoint"
  --seeds "$seeds"
  --cycle "$num_recycles"
  --step "$diffusion_steps"
  --sample "$num_samples"
  --device cuda
  --need_atom_confidence "$need_atom_confidence"
  --use_msa "$use_msa"
  --use_template "$use_template"
  --use_rna_msa "$use_rna_msa"
)
"$mol_cli" "${mol_args[@]}"

echo "REVODESIGN_STAGE:output_validation"
find "$output_dir" -path '*/seed_*/predictions/*_sample_*.cif' -type f -size +0c -print -quit | grep -q . || {
  echo "Mol-1 produced no mmCIF structure" >&2; exit 1
}
find "$output_dir" -path '*/seed_*/predictions/*_summary_confidence_sample_*.json' -type f -size +0c -print -quit | grep -q . || {
  echo "Mol-1 produced no summary confidence" >&2; exit 1
}
if [[ "$need_atom_confidence" == "true" ]]; then
  find "$output_dir" -path '*/seed_*/predictions/*_full_data_sample_*.json' -type f -size +0c -print -quit | grep -q . || {
    echo "Mol-1 produced no requested full confidence data" >&2; exit 1
  }
fi
if [[ -d "$output_dir/ERR" ]] && find "$output_dir/ERR" -type f -size +0c -print -quit | grep -q .; then
  echo "Mol-1 reported an internal inference error" >&2; exit 1
fi

python3 "$prepare_input" finalize "$TASK_MANIFEST" "$output_dir" >/dev/null
touch "$output_dir/task_finished"
echo "Mol-1 inference complete."
