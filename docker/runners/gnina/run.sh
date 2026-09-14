#!/usr/bin/env bash
set -euo pipefail
source "${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
while getopts ':i:o:' opt; do case "$opt" in i) manifest=$OPTARG;; o) out=$OPTARG;; *) exit 2;; esac; done
[[ -f "${manifest:-}" && -n "${out:-}" ]] || exit 2
[[ "${TASK_TYPE:-}" == gnina ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
receptor=$(task_input receptor)
ligand=$(task_input ligand)
mkdir -p "$out"
echo 'REVODESIGN_STAGE:dock'
gnina -r "$receptor" -l "$ligand" --center_x "$(_parse_param center_x)" --center_y "$(_parse_param center_y)" --center_z "$(_parse_param center_z)" --size_x "$(_parse_param size_x)" --size_y "$(_parse_param size_y)" --size_z "$(_parse_param size_z)" --exhaustiveness "$(_parse_param exhaustiveness)" --cnn_scoring "$(_parse_param cnn_scoring)" --log "$out/gnina.log" -o "$out/gnina.sdf"
test -s "$out/gnina.sdf" && test -s "$out/gnina.log"
python3 /app/revocompute/normalize_results.py "$out"
test -s "$out/scores.csv" && test -s "$out/summary.json"
python3 - "$manifest" "$out/gnina-run.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); json.dump({'task_type':'gnina','runtime_network':False,'inputs':m['inputs'],'parameters':m.get('params',{})},open(sys.argv[2],'w'),indent=2); open(sys.argv[2],'a').write('\n')
PY
touch "$out/task_finished"
