#!/usr/bin/env bash

set -euo pipefail

command_name="$(basename "$0")"

case "${command_name}" in
  srun)
    while [[ $# -gt 0 && "${1##*/}" != "bash" ]]; do
      shift
    done
    [[ $# -ge 2 && "${1##*/}" == "bash" ]] || {
      echo "mock srun did not receive a wrapper script" >&2
      exit 2
    }
    export SLURM_JOB_ID=4242
    export SLURM_CPUS_PER_TASK="${SLURM_CPUS_PER_TASK:-2}"
    exec "$@"
    ;;
  apptainer)
    [[ "${1:-}" == "exec" ]] || {
      echo "mock apptainer only supports exec" >&2
      exit 2
    }
    shift
    declare -A binds=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --nv|--containall|--cleanenv)
          shift
          ;;
        --bind)
          spec="${2:?missing bind specification}"
          source="${spec%%:*}"
          remainder="${spec#*:}"
          target="${remainder%%:*}"
          binds["${target}"]="${source}"
          shift 2
          ;;
        *)
          image="$1"
          shift
          break
          ;;
      esac
    done
    [[ "${image:-}" == *.sif && "${1:-}" == "bash" && "${2:-}" == "/app/revocompute/run.sh" ]] || {
      echo "mock apptainer received an unexpected execution plan" >&2
      exit 2
    }
    shift 2
    input=""
    output=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -i) input="${2:?missing manifest path}"; shift 2 ;;
        -o) output="${2:?missing output path}"; shift 2 ;;
        *) shift ;;
      esac
    done
    for target in "${!binds[@]}"; do
      source="${binds[$target]}"
      input="${input/#"$target"/"$source"}"
      output="${output/#"$target"/"$source"}"
    done
    [[ -f "${input}" && -d "${output}" ]] || {
      echo "mock apptainer could not resolve task workspace binds" >&2
      exit 2
    }
    input_name="$(python -c 'import json,sys; data=json.load(open(sys.argv[1])); print(data["files"][0]["relative_path"])' "${input}")"
    prefix="${input_name%.*}"
    mkdir -p "${output}/log" "${output}/gremlin_msa" "${output}/gremlin_res" "${output}/pssm_msa"
    printf 'REVODESIGN_STAGE:hhblits\n'
    printf '>query\nACDEFGHIKLMNPQRSTVWY\n' >"${output}/gremlin_msa/${prefix}.i90c75.a3m"
    printf 'REVODESIGN_STAGE:gremlin\n'
    printf 'mock coupling data\n' >"${output}/gremlin_res/${prefix}.i90c75_aln.GREMLIN.mrf.pkl"
    printf 'mock png data\n' >"${output}/gremlin_res/${prefix}_GREMLIN_mtx.png"
    printf 'REVODESIGN_STAGE:blast\n'
    printf 'mock PSSM data\n' >"${output}/pssm_msa/${prefix}_ascii_mtx_file"
    printf 'finished\n' >"${output}/log/task_finished"
    ;;
  sbatch|squeue|scancel|sacct|sinfo)
    exit 0
    ;;
  *)
    echo "unsupported mocked HPC command: ${command_name}" >&2
    exit 2
    ;;
esac
