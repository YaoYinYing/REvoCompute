#!/bin/bash
# AlphaFold 3 runner using pinned google-deepmind/alphafold3 upstream.
set -euo pipefail

task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir> [-s all|features|model]" >&2; exit 2; }
run_stage=all
while getopts ":i:o:s:" opt; do
  case "$opt" in
    i) input_file=$OPTARG ;;
    o) output_dir=$OPTARG ;;
    s) run_stage=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || usage
[[ "$run_stage" =~ ^(all|features|model)$ ]] || usage

input_file=$(readlink -f "$input_file")
output_dir=$(readlink -f "$output_dir")
[[ -f "$input_file" ]] || { echo "Task manifest not found: $input_file" >&2; exit 1; }
mkdir -p "$output_dir"

json_path=$(primary_input)
[[ -f "$json_path" ]] || { echo "AlphaFold 3 JSON input not found: $json_path" >&2; exit 1; }
[[ "${json_path,,}" == *.json ]] || { echo "AlphaFold 3 input must be a .json file" >&2; exit 1; }

features_dir="$output_dir/features"
modeling_dir="$output_dir/modeling"
feature_marker="$output_dir/.alphafold3-features-complete"
db_dir="${ALPHAFOLD3_DB_DIR:-/mnt/alphafold3/databases}"
small_bfd="${ALPHAFOLD3_SMALL_BFD_PATH:-/mnt/alphafold3/reduced_bfd/bfd-first_non_consensus_sequences.fasta}"
model_dir="${ALPHAFOLD3_MODEL_DIR:-/mnt/alphafold3/models}"
af3_python="${ALPHAFOLD3_PYTHON:-/alphafold3_venv/bin/python3}"
af3_script="${ALPHAFOLD3_SCRIPT:-/app/alphafold/run_alphafold.py}"

# AF3 launches four protein MSA searches concurrently (and three RNA searches).
# NPROC is the total scheduler allocation, so translate it into per-process
# budgets rather than allowing each upstream tool to consume the full total.
allocated_cpus="${NPROC:-4}"
case "$allocated_cpus" in
  (''|*[!0-9]*)
    echo "NPROC must be a positive integer (got: $allocated_cpus)" >&2
    exit 1
    ;;
esac
if (( allocated_cpus < 4 )); then
  echo "AlphaFold 3 requires at least 4 allocated CPUs (NPROC=$allocated_cpus)" >&2
  exit 1
fi
af3_jackhmmer_n_cpu=$(( allocated_cpus / 4 ))
af3_nhmmer_n_cpu=$(( allocated_cpus / 3 ))
(( af3_jackhmmer_n_cpu > 8 )) && af3_jackhmmer_n_cpu=8
(( af3_nhmmer_n_cpu > 8 )) && af3_nhmmer_n_cpu=8
af3_hmmsearch_n_cpu=$(( allocated_cpus < 8 ? allocated_cpus : 8 ))

find_processed_json() {
  local -a matches=()
  mapfile -d '' matches < <(find "$features_dir" -mindepth 2 -maxdepth 2 -type f -name '*_data.json' -size +0c -print0 2>/dev/null)
  [[ ${#matches[@]} -eq 1 ]] || {
    echo "Expected exactly one AlphaFold 3 processed *_data.json in the feature output; found ${#matches[@]}" >&2
    return 1
  }
  local job_name
  job_name=$(basename "$(dirname "${matches[0]}")")
  [[ "$(basename "${matches[0]}")" == "${job_name}_data.json" ]] || {
    echo "AlphaFold 3 processed JSON does not match its job output directory" >&2
    return 1
  }
  printf '%s\n' "${matches[0]}"
}

# Map user scientific controls to upstream flags. Four protein Jackhmmer
# searches run concurrently, so divide the total CPU allocation across them.
scientific_args() {
  local stage=$1
  local max_template_date resolve_msa_overlaps conformer_max_iterations fix_standalone_glycans
  local num_recycles num_diffusion_samples save_embeddings save_distogram
  normalize_bool() {
    case "${1,,}" in
      true|false) printf '%s\n' "${1,,}" ;;
      *) echo "AlphaFold 3 boolean parameter must be true or false (got: $1)" >&2; exit 1 ;;
    esac
  }
  if [[ "$stage" == features ]]; then
    max_template_date="$(_parse_param max_template_date 2021-09-30)"
    resolve_msa_overlaps=$(normalize_bool "$(_parse_param resolve_msa_overlaps true)")
    conformer_max_iterations="$(_parse_param conformer_max_iterations)"
    fix_standalone_glycans=$(normalize_bool "$(_parse_param fix_standalone_glycans false)")
    AF3_SCIENTIFIC_ARGS=(
      "--max_template_date=$max_template_date" "--resolve_msa_overlaps=$resolve_msa_overlaps"
      "--fix_standalone_glycans=$fix_standalone_glycans"
    )
    [[ -n "$conformer_max_iterations" ]] && AF3_SCIENTIFIC_ARGS+=("--conformer_max_iterations=$conformer_max_iterations")
    AF3_SCIENTIFIC_ARGS+=(
      "--jackhmmer_n_cpu=$af3_jackhmmer_n_cpu" "--jackhmmer_max_parallel_shards=1"
      "--nhmmer_n_cpu=$af3_nhmmer_n_cpu" "--nhmmer_max_parallel_shards=1"
      "--hmmsearch_n_cpu=$af3_hmmsearch_n_cpu"
    )
  else
    num_recycles="$(_parse_param num_recycles 10)"
    num_diffusion_samples="$(_parse_param num_diffusion_samples 5)"
    save_embeddings=$(normalize_bool "$(_parse_param save_embeddings false)")
    save_distogram=$(normalize_bool "$(_parse_param save_distogram false)")
    AF3_SCIENTIFIC_ARGS=(
      "--num_recycles=$num_recycles" "--num_diffusion_samples=$num_diffusion_samples"
      "--save_embeddings=$save_embeddings" "--save_distogram=$save_distogram"
    )
  fi
}

run_features() {
  [[ -d "$db_dir" ]] || { echo "AlphaFold 3 database directory is missing: $db_dir" >&2; exit 1; }
  [[ -s "$small_bfd" ]] || { echo "AlphaFold 3 reduced BFD database is missing: $small_bfd" >&2; exit 1; }
  if [[ -d "$features_dir" && -s "$feature_marker" ]]; then
    local completed_json expected_hash actual_hash
    completed_json=$(find_processed_json)
    expected_hash=$(<"$feature_marker")
    actual_hash=$(sha256sum "$completed_json" | cut -d ' ' -f 1)
    if [[ "$expected_hash" =~ ^[0-9a-f]{64}$ && "$actual_hash" == "$expected_hash" ]]; then
      echo "AlphaFold 3 data pipeline already complete."
      return
    fi
  fi
  rm -rf "$features_dir" "$feature_marker"
  mkdir -p "$features_dir"
  echo "REVODESIGN_STAGE:data_pipeline"
  scientific_args features
  "$af3_python" "$af3_script" \
    "--json_path=$json_path" \
    "--output_dir=$features_dir" \
    --run_data_pipeline=true \
    --run_inference=false \
    "--db_dir=$db_dir" \
    "--small_bfd_database_path=$small_bfd" \
    "${AF3_SCIENTIFIC_ARGS[@]}"
  echo "REVODESIGN_STAGE:feature_validation"
  local processed_json
  processed_json=$(find_processed_json)
  sha256sum "$processed_json" | cut -d ' ' -f 1 > "$feature_marker"
  echo "AlphaFold 3 data pipeline complete."
}

run_model() {
  [[ -s "$feature_marker" ]] || { echo "Validated AlphaFold 3 processed JSON is missing" >&2; exit 1; }
  local processed_json expected_hash actual_hash
  processed_json=$(find_processed_json)
  expected_hash=$(<"$feature_marker")
  actual_hash=$(sha256sum "$processed_json" | cut -d ' ' -f 1)
  [[ "$expected_hash" =~ ^[0-9a-f]{64}$ && "$actual_hash" == "$expected_hash" ]] || {
    echo "AlphaFold 3 processed JSON changed after feature validation" >&2
    exit 1
  }
  [[ -d "$model_dir" ]] || { echo "AlphaFold 3 model parameter directory is missing: $model_dir" >&2; exit 1; }
  find "$model_dir" -maxdepth 1 -type f -name '*.bin.zst' -size +0c -print -quit | grep -q . || {
    echo "AlphaFold 3 model parameters are missing from: $model_dir" >&2
    exit 1
  }
  if [[ -f "$output_dir/task_finished" ]] &&
     find "$modeling_dir" -mindepth 2 -maxdepth 2 -type f -name '*_model.cif' -size +0c -print -quit | grep -q . &&
     find "$modeling_dir" -mindepth 2 -maxdepth 2 -type f -name '*_ranking_scores.csv' -size +0c -print -quit | grep -q .; then
    echo "AlphaFold 3 inference already complete."
    return
  fi
  rm -rf "$modeling_dir" "$output_dir/task_finished"
  mkdir -p "$modeling_dir"
  echo "REVODESIGN_STAGE:inference"
  scientific_args model
  "$af3_python" "$af3_script" \
    "--json_path=$processed_json" \
    "--output_dir=$modeling_dir" \
    --run_data_pipeline=false \
    --run_inference=true \
    "--model_dir=$model_dir" \
    "${AF3_SCIENTIFIC_ARGS[@]}"
  echo "REVODESIGN_STAGE:output_validation"
  find "$modeling_dir" -mindepth 2 -maxdepth 2 -type f -name '*_model.cif' -size +0c -print -quit | grep -q . || {
    echo "AlphaFold 3 produced no expected mmCIF structure output" >&2
    exit 1
  }
  find "$modeling_dir" -mindepth 2 -maxdepth 2 -type f -name '*_ranking_scores.csv' -size +0c -print -quit | grep -q . || {
    echo "AlphaFold 3 produced no ranking scores" >&2
    exit 1
  }
  touch "$output_dir/task_finished"
  echo "AlphaFold 3 inference complete."
}

if [[ "$run_stage" =~ ^(all|features)$ ]]; then
  run_features
  [[ "$run_stage" == features ]] && exit 0
fi
run_model
