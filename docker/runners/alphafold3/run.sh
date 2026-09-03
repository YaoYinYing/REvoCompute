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
  "$af3_python" "$af3_script" \
    "--json_path=$json_path" \
    "--output_dir=$features_dir" \
    --run_data_pipeline=true \
    --run_inference=false \
    "--db_dir=$db_dir" \
    "--small_bfd_database_path=$small_bfd"
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
  "$af3_python" "$af3_script" \
    "--json_path=$processed_json" \
    "--output_dir=$modeling_dir" \
    --run_data_pipeline=false \
    --run_inference=true \
    "--model_dir=$model_dir"
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
