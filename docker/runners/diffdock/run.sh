#!/usr/bin/env bash
set -euo pipefail
source "${TASK_CONTEXT_SRC:-/app/revocompute/task_context.sh}"
while getopts ':i:o:' opt; do case "$opt" in i) manifest=$OPTARG;; o) out=$OPTARG;; *) exit 2;; esac; done
[[ -f "${manifest:-}" && -n "${out:-}" ]] || exit 2
[[ "${TASK_TYPE:-}" == diffdock ]] || { echo "Unsupported TASK_TYPE: ${TASK_TYPE:-unset}" >&2; exit 1; }
mapfile -t inputs < <(python3 - "$manifest" <<'PY'
import json,sys
for x in json.load(open(sys.argv[1]))['files']: print(x['path'])
PY
)
(( ${#inputs[@]} == 2 )) || { echo 'DiffDock requires exactly protein PDB and ligand SDF/MOL2 files' >&2; exit 1; }
[[ "${inputs[0],,}" == *.pdb ]] || { echo 'DiffDock protein input must be a PDB structure; sequences are not accepted' >&2; exit 1; }
[[ "${inputs[1],,}" == *.sdf || "${inputs[1],,}" == *.mol2 ]] || { echo 'DiffDock ligand must be SDF or MOL2' >&2; exit 1; }
model_root=${DIFFDOCK_MODEL_ROOT:-/mnt/db/weights/revocompute/diffdock}
model_manifest=${DIFFDOCK_MODEL_MANIFEST:-/app/revocompute/model-assets.sha256}
esm_root=${DIFFDOCK_ESM_ROOT:-/mnt/db/weights/esm}
esm_manifest=${DIFFDOCK_ESM_MANIFEST:-/app/revocompute/esm-assets.sha256}
score_model="$model_root/score_model"; confidence_model="$model_root/confidence_model"
test -s "$model_manifest" || { echo 'DiffDock model asset manifest is missing' >&2; exit 1; }
test -s "$esm_manifest" || { echo 'DiffDock ESM asset manifest is missing' >&2; exit 1; }
test -s "$score_model/model_parameters.yml" && test -s "$score_model/best_ema_inference_epoch_model.pt" || { echo 'DiffDock score model assets are missing' >&2; exit 1; }
test -s "$confidence_model/model_parameters.yml" && test -s "$confidence_model/best_model_epoch75.pt" || { echo 'DiffDock confidence model assets are missing' >&2; exit 1; }
(cd "$model_root" && sha256sum --strict --check --status "$model_manifest") || { echo 'DiffDock model asset integrity verification failed' >&2; exit 1; }
(cd "$esm_root" && sha256sum --strict --check --status "$esm_manifest") || { echo 'DiffDock ESM asset integrity verification failed' >&2; exit 1; }
mkdir -p "$out/.cache/torch/hub"; ln -s "$esm_root/checkpoints" "$out/.cache/torch/hub/checkpoints"
export TORCH_HOME="$out/.cache/torch" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
config="$out/diffdock-config.yaml"
python3 - /opt/diffdock/default_inference_args.yaml "$config" "$score_model" "$confidence_model" "$(_parse_param samples)" "$(_parse_param steps)" <<'PY'
import sys
import yaml

source, destination, score_model, confidence_model, samples, steps = sys.argv[1:]
with open(source) as handle:
    config = yaml.safe_load(handle)
config.update(
    model_dir=score_model,
    confidence_model_dir=confidence_model,
    samples_per_complex=int(samples),
    inference_steps=int(steps),
    actual_steps=int(steps),
)
with open(destination, "w") as handle:
    yaml.safe_dump(config, handle, sort_keys=True)
PY
echo 'REVODESIGN_STAGE:diffusion'
(cd /opt/diffdock && python3 -m inference --config "$config" --complex_name diffdock --protein_path "${inputs[0]}" --ligand_description "${inputs[1]}" --out_dir "$out")
find "$out" -type f -name '*.sdf' -size +0c -print -quit | grep -q . || { echo 'DiffDock produced no docked poses' >&2; exit 1; }
python3 /app/revocompute/normalize_results.py "$out"
test -s "$out/scores.csv" && test -s "$out/summary.json"
cp "$model_manifest" "$out/diffdock-model-assets.sha256"
cp "$esm_manifest" "$out/diffdock-esm-assets.sha256"
python3 - "$manifest" "$out/diffdock-run.json" <<'PY'
import json,sys
m=json.load(open(sys.argv[1])); json.dump({'task_type':'diffdock','runtime_network':False,'files':m['files'],'parameters':m.get('params',{})},open(sys.argv[2],'w'),indent=2); open(sys.argv[2],'a').write('\n')
PY
touch "$out/task_finished"
