#!/usr/bin/env bash
set -euo pipefail
source "${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
while getopts ':i:o:' opt; do case "$opt" in i) manifest=$OPTARG;; o) out=$OPTARG;; *) exit 2;; esac; done
[[ -f "${manifest:-}" && -n "${out:-}" ]] || exit 2
[[ "${TASK_TYPE:-}" == autodock_vina ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
mapfile -t inputs < <(python3 - "$manifest" <<'PY'
import json,sys
for item in json.load(open(sys.argv[1]))['files']: print(item['path'])
PY
)
(( ${#inputs[@]} >= 2 )) || { echo 'AutoDock Vina requires receptor and ligand files' >&2; exit 1; }
[[ "${inputs[0],,}" == *.pdb || "${inputs[0],,}" == *.pdbqt ]] || { echo 'Vina receptor must be PDB or PDBQT' >&2; exit 1; }
for ligand in "${inputs[@]:1}"; do [[ "${ligand,,}" == *.sdf || "${ligand,,}" == *.mol2 || "${ligand,,}" == *.pdbqt ]] || { echo 'Vina ligands must be SDF, MOL2, or PDBQT' >&2; exit 1; }; done
mkdir -p "$out/prepared"; receptor=${inputs[0]}; prepared_receptor="$out/prepared/receptor.pdbqt"
echo 'REVODESIGN_STAGE:prepare'
if [[ "${receptor,,}" == *.pdbqt ]]; then cp "$receptor" "$prepared_receptor"; else mk_prepare_receptor.py --read_pdb "$receptor" -o "$out/prepared/receptor" -p; fi
test -s "$prepared_receptor" || { echo 'Receptor preparation produced no PDBQT' >&2; exit 1; }
echo 'REVODESIGN_STAGE:dock'; n=0
for ligand in "${inputs[@]:1}"; do
  n=$((n+1)); prepared_ligand="$out/prepared/ligand_${n}.pdbqt"
  if [[ "${ligand,,}" == *.pdbqt ]]; then cp "$ligand" "$prepared_ligand"; else mk_prepare_ligand.py -i "$ligand" -o "$prepared_ligand"; fi
  base="$out/vina_${n}.pdbqt"
  vina --receptor "$prepared_receptor" --ligand "$prepared_ligand" --center_x "$(_parse_param center_x)" --center_y "$(_parse_param center_y)" --center_z "$(_parse_param center_z)" --size_x "$(_parse_param size_x)" --size_y "$(_parse_param size_y)" --size_z "$(_parse_param size_z)" --exhaustiveness "$(_parse_param exhaustiveness)" --num_modes "$(_parse_param num_modes)" --seed "$(_parse_param seed)" --out "$base" 2>&1 | tee "$out/vina_${n}.log"
  [[ -s "$base" && -s "$out/vina_${n}.log" ]] || exit 1
done
python3 /app/revocompute/normalize_results.py "$out" "${inputs[@]:1}"
test -s "$out/scores.csv" && test -s "$out/summary.json"
python3 - "$manifest" "$out/vina-run.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); json.dump({'task_type':'autodock_vina','runtime_network':False,'files':m['files'],'parameters':m.get('params',{})},open(sys.argv[2],'w'),indent=2); open(sys.argv[2],'a').write('\n')
PY
touch "$out/task_finished"
