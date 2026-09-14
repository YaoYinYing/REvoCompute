#!/usr/bin/env bash
set -euo pipefail
source "${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
while getopts ':i:o:' opt; do case "$opt" in i) manifest=$OPTARG;; o) out=$OPTARG;; *) exit 2;; esac; done
[[ -f "${manifest:-}" && -n "${out:-}" ]] || exit 2
[[ "${TASK_TYPE:-}" == autodock_gpu ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
mapfile -t ligands < <(python3 - "$manifest" <<'PY'
import json,sys
for x in json.load(open(sys.argv[1]))['inputs']['ligands']: print(x['path'])
PY
)
receptor=$(task_input receptor)
(( ${#ligands[@]} >= 1 )) || { echo 'AutoDock-GPU requires at least one ligand' >&2; exit 1; }
mkdir -p "$out/prepared"
center=("$(_parse_param center_x)" "$(_parse_param center_y)" "$(_parse_param center_z)")
size=("$(_parse_param size_x)" "$(_parse_param size_y)" "$(_parse_param size_z)")
echo 'REVODESIGN_STAGE:maps'
mk_prepare_receptor.py --read_pdb "$receptor" -o "$out/prepared/receptor" -p -g --box_center "${center[@]}" --box_size "${size[@]}"
gpf="$out/prepared/receptor.gpf"; fld="$out/prepared/receptor.maps.fld"
test -s "$gpf" || { echo 'Meeko produced no AutoGrid GPF' >&2; exit 1; }
(cd "$out/prepared" && autogrid4 -p receptor.gpf -l autogrid.glg)
test -s "$fld" || { echo 'AutoGrid produced no FLD map descriptor' >&2; exit 1; }
echo 'REVODESIGN_STAGE:dock'; n=0
for ligand in "${ligands[@]}"; do
  n=$((n+1)); prepared="$out/prepared/ligand_${n}.pdbqt"
  if [[ "${ligand,,}" == *.pdbqt ]]; then cp "$ligand" "$prepared"; else mk_prepare_ligand.py -i "$ligand" -o "$prepared"; fi
  result="$out/autodock_gpu_${n}"
  autodock_gpu --ffile "$fld" --lfile "$prepared" --nrun "$(_parse_param nrun)" --resnam "$result"
  test -s "$result.dlg" || { echo "AutoDock-GPU produced no DLG for ligand $n" >&2; exit 1; }
done
python3 /app/revocompute/normalize_results.py "$out" "${ligands[@]}"
test -s "$out/scores.csv" && test -s "$out/summary.json"
python3 - "$manifest" "$out/autodock-gpu-run.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); json.dump({'task_type':'autodock_gpu','runtime_network':False,'inputs':m['inputs'],'parameters':m.get('params',{})},open(sys.argv[2],'w'),indent=2); open(sys.argv[2],'a').write('\n')
PY
touch "$out/task_finished"
