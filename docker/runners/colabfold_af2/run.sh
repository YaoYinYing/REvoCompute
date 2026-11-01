#!/bin/bash
# ColabFold/AlphaFold2 runner using the public MMseqs2 MSA service.
set -euo pipefail
runtime_root="${RUNNER_RUNTIME_ROOT:-/opt/revocompute/runtime}"
task_context_src="${TASK_CONTEXT_SRC:-$runtime_root/common/runtime/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir> [-s all|features|model]"; exit 1; }
run_stage=all
while getopts ":i:o:s:" opt; do case "${opt}" in i) input_file=$OPTARG ;; o) output_dir=$OPTARG ;; s) run_stage=$OPTARG ;; ?) usage ;; esac; done
[[ -z "${input_file:-}" || -z "${output_dir:-}" ]] && usage
[[ "$run_stage" =~ ^(all|features|model)$ ]] || usage
input_file=$(readlink -f "$input_file"); output_dir=$(readlink -f "$output_dir")
[[ -f "$input_file" ]] || { echo "Task manifest not found: $input_file" >&2; exit 1; }
mkdir -p "$output_dir"

model_type=$(_parse_param model_type)
msa_mode=$(_parse_param msa_mode)
num_recycle=$(_parse_param num_recycle)
num_models=$(_parse_param num_models)
num_seeds=$(_parse_param num_seeds)
random_seed=$(_parse_param random_seed)
num_relax=$(_parse_param num_relax)
fasta_path=$(task_input sequence)
msa_marker="${output_dir}/.colabfold-msa-complete"
colabfold_batch=${COLABFOLD_BATCH:-colabfold_batch}
normalizer=${COLABFOLD_NORMALIZER:-/app/revocompute/normalize_interface_scores.py}

# Each attempt clears the outputs of the stages it runs before any preflight
# check, because this Runner cannot bind the runtime image: a failed attempt
# must not leave an earlier attempt's tree publishable under this one. Upstream
# reuses an existing <job>.done.txt or <job>.pickle, so the features stage also
# clears the MSA cache and the model stage keeps only this attempt's features.
case "$run_stage" in
  features|all)
    find "$output_dir" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + ;;
  model)
    find "$output_dir" -mindepth 1 -maxdepth 1 \
      ! -name '*.a3m' ! -name '*.pickle' ! -name '.colabfold-msa-complete' \
      -exec rm -rf -- {} + ;;
esac

# The marker carries a digest of this attempt's MSA cache so the model stage
# consumes exactly the features the features stage published.
msa_digest() {
  find "$output_dir" -type f \( -name '*.a3m' -o -name '*.pickle' \) -print0 \
    | LC_ALL=C sort -z | xargs -0 -r sha256sum | sha256sum | cut -d ' ' -f 1
}

common_args=(
  "--data" "/mnt/colabfold"
  "--model-type" "$model_type"
  "--msa-mode" "$msa_mode"
  "--num-recycle" "$num_recycle"
  "--num-models" "$num_models"
  "--num-seeds" "$num_seeds"
  "--random-seed" "$random_seed"
  "--host-url" "https://api.colabfold.com"
)

run_msa() {
  echo "REVODESIGN_STAGE:msa_searching"
  "$colabfold_batch" "${common_args[@]}" --msa-only "$fasta_path" "$output_dir"
  find "$output_dir" -type f -name '*.a3m' -size +0c -print -quit | grep -q . || {
    echo "ColabFold produced no MSA" >&2; exit 1;
  }
  find "$output_dir" -type f -name '*.pickle' -size +0c -print -quit | grep -q . || {
    echo "ColabFold produced no MSA cache" >&2; exit 1;
  }
  msa_digest > "$msa_marker"
  echo "ColabFold MSA complete."
}

if [[ "$run_stage" =~ ^(all|features)$ ]]; then
  run_msa
  [[ "$run_stage" == features ]] && exit 0
fi

[[ -s "$msa_marker" ]] || { echo "Validated ColabFold MSA is missing" >&2; exit 1; }
expected_msa_sha=$(<"$msa_marker")
actual_msa_sha=$(msa_digest)
[[ "$expected_msa_sha" =~ ^[0-9a-f]{64}$ && "$actual_msa_sha" == "$expected_msa_sha" ]] || {
  echo "ColabFold MSA changed after feature validation" >&2; exit 1; }
echo "REVODESIGN_STAGE:modeling"
model_args=("${common_args[@]}")
# BooleanOptionalAction: the flag is a switch, so pass it only when requested.
[[ "$(_parse_param use_fast_kernels)" == "true" ]] && model_args+=(--use-fast-kernels)
model_args+=(
  "--kernel-backend" "$(_parse_param kernel_backend)"
  "--compile-mode" "$(_parse_param compile_mode)"
)
if (( num_relax > 0 )); then
  model_args+=(--amber --use-gpu-relax --num-relax "$num_relax")
fi
"$colabfold_batch" "${model_args[@]}" "$fasta_path" "$output_dir"
find "$output_dir" -type f -name '*.pdb' -size +0c -print -quit | grep -q . || {
  echo "ColabFold produced no structure" >&2; exit 1;
}
# Interface confidence is optional upstream: it is emitted only for complexes.
# Flatten the per-chain-pair values for the result protocol; absence is not a
# run failure and must not discard the predicted structures.
python3 "$normalizer" "$output_dir"
touch "${output_dir}/task_finished"
echo "ColabFold complete."
