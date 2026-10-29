#!/usr/bin/env bash
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
#
# CAVER 3.0.2 tunnel-analysis entrypoint. The SIF supplies the pinned JRE and the
# read-only CAVER distribution; this script and the Python adapters arrive in the
# Runtime Bundle and never write outside the supplied output directory.

set -euo pipefail
runtime_root="${RUNNER_RUNTIME_ROOT:-/opt/revocompute/runtime}"
script_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

usage() { echo "Usage: $0 -i <task.json> -o <output_dir>" >&2; exit 1; }
while getopts ":i:o:" opt; do
    case "$opt" in
        i) task_file=$OPTARG ;;
        o) output_dir=$OPTARG ;;
        *) usage ;;
    esac
done
[[ -n "${task_file:-}" && -n "${output_dir:-}" ]] || usage

task_file=$(readlink -f "$task_file")
output_dir=$(readlink -m "$output_dir")
[[ -f "$task_file" ]] || { echo "Task manifest not found: $task_file" >&2; exit 1; }
mkdir -p "$output_dir"
export TASK_MANIFEST=$task_file

task_context_src="${TASK_CONTEXT_SRC:-$runtime_root/common/runtime/task_context.sh}"
# shellcheck source=/dev/null
[[ -f "$task_context_src" ]] && source "$task_context_src"

[[ "${TASK_TYPE:-}" == caver ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }

caver_home="${CAVER_HOME:-/opt/caver302/caver}"
[[ -s "$caver_home/caver.jar" ]] || { echo "CAVER jar is missing: $caver_home/caver.jar" >&2; exit 1; }
[[ -d "$caver_home/lib" ]] || { echo "CAVER libraries are missing: $caver_home/lib" >&2; exit 1; }
[[ -s "$caver_home/bin/atom_radii.csv" ]] || { echo "CAVER home lacks bin/atom_radii.csv" >&2; exit 1; }

# The SIF environment is the single source of the heap bound. The internal
# timeout is set here, 300 s below runner.yaml's max_runtime_seconds, so a
# stuck JVM is killed and reported before the scheduler kills the job.
java_heap="${CAVER_JAVA_XMX:?CAVER_JAVA_XMX must be supplied by the SIF environment}"
[[ "$java_heap" =~ ^[1-9][0-9]{0,4}[mMgG]$ ]] || {
    echo "CAVER_JAVA_XMX must be a bounded heap size such as 1200m or 4g" >&2
    exit 1
}
timeout_seconds="${CAVER_TIMEOUT_SECONDS:-3300}"
[[ "$timeout_seconds" =~ ^[1-9][0-9]{0,5}$ ]] || { echo "CAVER_TIMEOUT_SECONDS must be a positive integer" >&2; exit 1; }
export CAVER_TIMEOUT_SECONDS="$timeout_seconds"
export CAVER_JAVA_XMX="$java_heap"

structure=$(task_input structure)
[[ -f "$structure" ]] || { echo "CAVER input structure not found: $structure" >&2; exit 1; }
case "${structure,,}" in
    *.pdb|*.ent) ;;
    *) echo "CAVER accepts a PDB structure, not ${structure}" >&2; exit 1 ;;
esac
# The snapshot role is optional and run_caver.py reads it with an empty
# default; asking the shared helper for an absent role exits non-zero.
echo "REVODESIGN_STAGE:resolve_start_point"
python3 "$script_dir/run_caver.py" \
    --task "$task_file" \
    --output-dir "$output_dir" \
    --distribution "$caver_home" \
    --java "${CAVER_JAVA:-java}" \
    --upstream "${CAVER_UPSTREAM_JSON:-$script_dir/upstream.json}"

for artifact in tunnels.csv clusters.csv bottlenecks.csv profiles.csv residues.csv summary.json provenance.json; do
    [[ -s "$output_dir/$artifact" ]] || { echo "CAVER produced no $artifact" >&2; exit 1; }
done
touch "$output_dir/task_finished"
