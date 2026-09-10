#!/bin/bash
set -e
task_context_src="${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"
while getopts ":i:o:" opt; do case "$opt" in i) input_file=$OPTARG;; o) output_dir=$OPTARG;; *) exit 1;; esac; done
[[ -n "${input_file:-}" && -n "${output_dir:-}" ]] || exit 1
input_file=$(readlink -f "$input_file"); input_file=$(primary_input)
output_dir=$(readlink -f "$output_dir"); mkdir -p "$output_dir"
weights=${FAMPNN_WEIGHT_DIR:-/mnt/db/weights/revocompute/fampnn}
echo "REVODESIGN_STAGE:${TASK_TYPE}"
case "${TASK_TYPE}" in
  fampnn_design)
    checkpoint="${weights}/fampnn_0_3.pt"; [[ -s "$checkpoint" ]] || { echo "Missing FAMPNN checkpoint: $checkpoint" >&2; exit 1; }
    input_dir=$(dirname "$input_file")
    python3 "${FAMPNN_PATH}/fampnn/inference/seq_design.py" checkpoint_path="$checkpoint" pdb_dir="$input_dir" \
      pdb_key_list=null out_dir="$output_dir" num_seqs_per_pdb="$(_parse_param num_seqs_per_pdb)" batch_size="$(_parse_param batch_size)" \
      seed="$(_parse_param seed)" temperature="$(_parse_param temperature)" seq_only=false \
      timestep_schedule.num_steps="$(_parse_param sequence_steps)" scn_diffusion.num_steps="$(_parse_param sidechain_steps)" \
      scn_diffusion.timestep_schedule.num_steps="$(_parse_param sidechain_steps)"
    compgen -G "$output_dir/samples/*.pdb" >/dev/null || { echo "FAMPNN produced no design structures" >&2; exit 1; }
    compgen -G "$output_dir/fastas/*.fasta" >/dev/null || { echo "FAMPNN produced no designed sequences" >&2; exit 1; }
    ;;
  fampnn_pack)
    checkpoint="${weights}/fampnn_0_0.pt"; [[ -s "$checkpoint" ]] || { echo "Missing FAMPNN checkpoint: $checkpoint" >&2; exit 1; }
    python3 "${FAMPNN_PATH}/fampnn/inference/pack.py" checkpoint_path="$checkpoint" pdb_dir="$(dirname "$input_file")" \
      pdb_key_list=null out_dir="$output_dir" num_samples_per_pdb="$(_parse_param num_samples_per_pdb)" \
      batch_size="$(_parse_param batch_size)" seed="$(_parse_param seed)" scn_diffusion.num_steps="$(_parse_param sidechain_steps)" \
      scn_diffusion.timestep_schedule.num_steps="$(_parse_param sidechain_steps)"
    compgen -G "$output_dir/samples/*.pdb" >/dev/null || { echo "FAMPNN produced no packed structures" >&2; exit 1; }
    ;;
  fampnn_score)
    checkpoint="${weights}/fampnn_0_3_cath.pt"; [[ -s "$checkpoint" ]] || { echo "Missing FAMPNN checkpoint: $checkpoint" >&2; exit 1; }
    python3 "${FAMPNN_PATH}/fampnn/inference/score_all_muts.py" checkpoint_path="$checkpoint" pdb_path="$input_file" \
      out_dir="$output_dir" batch_size="$(_parse_param batch_size)" seed="$(_parse_param seed)"
    [[ -s "$output_dir/all_scores.csv" ]] || { echo "FAMPNN produced no mutation score table" >&2; exit 1; }
    ;;
  *) echo "Unknown TASK_TYPE: ${TASK_TYPE}" >&2; exit 1;;
esac
touch "$output_dir/task_finished"
