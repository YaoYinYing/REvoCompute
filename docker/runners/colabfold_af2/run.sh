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
# This Runner owns one result subtree. Clearing never touches a sibling
# producer's files at the Task output root, even one whose name happens to
# start with a ColabFold job prefix.
result_dir="${output_dir}/colabfold"
msa_marker="${result_dir}/.colabfold-msa-complete"
colabfold_batch=${COLABFOLD_BATCH:-colabfold_batch}
normalizer=${COLABFOLD_NORMALIZER:-/app/revocompute/normalize_interface_scores.py}

# Upstream creates one job per FASTA record and names its files after
# safe_filename(header) (batch.py:1458; input.py:302-309). Every record needs a
# distinct, non-empty job, so reject both an empty header and two headers that
# sanitize alike before any output mutation or upstream invocation: otherwise
# a record's outputs are hidden under an empty name or one record's MSA
# overwrites the other, and the Task settles with fewer predictions than
# records. The Server validator guarantees at least one header line. Scope
# clearing and the handoff digest to these jobs so another producer's files in
# the same output tree survive a re-attempt.
job_list=$(python3 - "$fasta_path" <<'PY'
import sys

names = {}
record = 0
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line.startswith(">"):
        continue
    record += 1
    header = line[1:]
    if not header.strip():
        print(
            f"ColabFold requires non-empty FASTA headers: record {record} has an empty header",
            file=sys.stderr,
        )
        sys.exit(1)
    name = "".join(c if c.isalnum() or c in "_.-" else "_" for c in header)
    if name in names:
        print(
            f"ColabFold cannot distinguish FASTA records: headers "
            f"{names[name]!r} and {header!r} both map to job {name!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    names[name] = header
if not record:
    print("FASTA file must contain a '>' header line", file=sys.stderr)
    sys.exit(1)
for name in sorted(names):
    print(name)
PY
) || exit 1
mapfile -t job_names <<< "$job_list"

# A ranked structure or score file carries its job as a greedy prefix followed
# by a complete role suffix. Role-anchored suffixes alone are not enough: the
# suffix token can itself be the beginning of another legal sanitized job name
# (for example "query_scores_rank_foo"), and that sibling's files must not be
# mistaken for this job's. Ownership therefore comes from the end-anchored
# identity parse compared to the exact job. "require-scores" also rejects a
# published rank whose score file is missing or unreadable, because the result
# contract needs one score per structure. Usage: colabfold_ranked_files
# <job> delete|present|require-scores.
colabfold_ranked_files() {
  python3 - "$result_dir" "$1" "$2" <<'PY'
import json
import re
import sys
from pathlib import Path

result_dir, job, action = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
structure = re.compile(r"^(.*)_(unrelaxed|relaxed)_rank_(\d+)_[^/]+\.pdb$")
scores = re.compile(r"^(.*)_scores_rank_(\d+)_[^/]+\.json$")
if not result_dir.is_dir():
    sys.exit(0)
if action == "delete":
    for path in result_dir.iterdir():
        if not path.is_file():
            continue
        for pattern in (structure, scores):
            match = pattern.match(path.name)
            if not match or match.group(1) != job:
                continue
            path.unlink()
            break
    sys.exit(0)
if action == "present":
    for path in result_dir.iterdir():
        match = structure.match(path.name)
        if match and match.group(1) == job and path.is_file() and path.stat().st_size > 0:
            print(path.name)
            break
    sys.exit(0)
structure_ranks = set()
score_ranks = set()
for path in result_dir.iterdir():
    if not path.is_file() or path.stat().st_size == 0:
        continue
    match = structure.match(path.name)
    if match and match.group(1) == job:
        structure_ranks.add(int(match.group(3)))
        continue
    match = scores.match(path.name)
    if not match or match.group(1) != job:
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        continue
    score_ranks.add(int(match.group(2)))
for rank in sorted(structure_ranks - score_ranks):
    print(f"ColabFold produced no score for job {job!r} rank {rank}", file=sys.stderr)
    sys.exit(1)
PY
}

# Each attempt clears the outputs of the stages it runs before any preflight
# check, because this Runner cannot bind the runtime image: a failed attempt
# must not leave an earlier attempt's tree publishable under this one. Upstream
# reuses an existing <job>.done.txt or <job>.pickle, so the features stage also
# clears the MSA cache and the model stage keeps only this attempt's features.
# Every removal stays inside result_dir; only the generic root task_finished
# marker is touched outside it.
case "$run_stage" in
  features|all)
    rm -rf -- "$result_dir"
    mkdir -p "$result_dir"
    rm -f -- "$output_dir/task_finished" ;;
  model)
    for job_name in "${job_names[@]}"; do
      rm -f -- "$result_dir/${job_name}.done.txt" \
        "$result_dir/${job_name}_predicted_aligned_error_v1.json" \
        "$result_dir/${job_name}_coverage.png" "$result_dir/${job_name}_pae.png" \
        "$result_dir/${job_name}_plddt.png" "$result_dir/${job_name}_ext_metrics.png" \
        "$result_dir/${job_name}_template_domain_names.json"
      colabfold_ranked_files "$job_name" delete
    done
    rm -f -- "$result_dir/interface_scores.json" "$output_dir/task_finished" ;;
esac

# The marker carries a digest of every job's MSA cache so the model stage
# consumes exactly the features the features stage published.
msa_digest() {
  local job_name file
  for job_name in "${job_names[@]}"; do
    for file in "$result_dir/${job_name}.a3m" "$result_dir/${job_name}.pickle"; do
      if [[ -f "$file" ]]; then
        printf '%s  %s\n' "$(sha256sum "$file" | cut -d ' ' -f 1)" "$(basename "$file")"
      fi
    done
  done | sha256sum | cut -d ' ' -f 1
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
  "$colabfold_batch" "${common_args[@]}" --msa-only "$fasta_path" "$result_dir"
  for job_name in "${job_names[@]}"; do
    [[ -s "$result_dir/${job_name}.a3m" ]] || {
      echo "ColabFold produced no MSA for $job_name" >&2; exit 1; }
    [[ -s "$result_dir/${job_name}.pickle" ]] || {
      echo "ColabFold produced no MSA cache for $job_name" >&2; exit 1; }
  done
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
"$colabfold_batch" "${model_args[@]}" "$fasta_path" "$result_dir"
for job_name in "${job_names[@]}"; do
  [[ -n "$(colabfold_ranked_files "$job_name" present)" ]] || {
    echo "ColabFold produced no structure for $job_name" >&2; exit 1; }
  colabfold_ranked_files "$job_name" require-scores
done
# Interface confidence is optional upstream: it is emitted only for complexes.
# Flatten the per-chain-pair values for the result protocol; absence is not a
# run failure and must not discard the predicted structures.
python3 "$normalizer" "$result_dir"
touch "${output_dir}/task_finished"
echo "ColabFold complete."
