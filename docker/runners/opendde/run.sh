#!/bin/bash
# REvoDesign OpenDDE runner — all-atom co-folding and structure prediction.
#
# Runner contract:
#   1. Reads input JSON from /workspace/inputs/
#   2. Writes output to /workspace/outputs/
#   3. Emits REVODESIGN_STAGE:<marker> on stdout
#   4. Accepts -i <input_json> -o <output_dir>
#   5. Exits 0 on success

set -euo pipefail
runtime_root="${RUNNER_RUNTIME_ROOT:-/opt/revocompute/runtime}"
task_context_src="${TASK_CONTEXT_SRC:-$runtime_root/common/runtime/task_context.sh}"
[[ -f "$task_context_src" ]] && source "$task_context_src"

REVODESIGN_RUNSCRIPT_PATH=$(readlink -f "$(dirname "$0")")

usage() {
    echo ""
    echo "Usage: $0 <OPTIONS>"
    echo "Required Parameters:"
    echo "      -i  <task.json>    Task manifest"
    echo "      -o  <output_dir>  Output directory"
    echo ""
    exit 1
}

while getopts ":i:o:" opt; do
    case "${opt}" in
        i) input_file=$OPTARG ;;
        o) output_dir=$OPTARG ;;
        ?) usage ;;
    esac
done

if [[ -z "${input_file:-}" ]]; then
    echo "Missing required option: -i <task.json>"
    usage
fi

if [[ -z "${output_dir:-}" ]]; then
    echo "Missing required option: -o <output_dir>"
    usage
fi

input_file=$(readlink -f "$input_file")
input_file=$(task_input specification)

output_dir=$(readlink -f "$output_dir")

if [[ ! -f "$input_file" ]]; then
    echo "Input file not found: $input_file"
    exit 1
fi

mkdir -p "$output_dir"

# Inference runs from a task-private writable copy of the complete input
# snapshot.  Production input snapshots are deliberately mounted read-only, and
# OpenDDE 1.2.0 still writes template mmCIF downloads beneath
# ``$OPENDDE_ROOT_DIR`` and may write ``*-update-msa.json`` next to the input
# JSON.  The copy also holds the writable runtime root below and preserves
# relative references to auxiliary inputs.
# Verified against opendde 1.2.0: the MSA client redirects its generated JSON to
# a per-input directory under the output directory, but the writable runtime
# root is still required, so the snapshot copy is retained.
case "$input_file" in
    */inputs/*)
        input_root="${input_file%%/inputs/*}/inputs"
        input_relative_path="${input_file#"$input_root"/}"
        ;;
    *)
        input_root=$(dirname "$input_file")
        input_relative_path=$(basename "$input_file")
        ;;
esac
opendde_input_root=$(mktemp -d "${TMPDIR:-/tmp}/revodesign-opendde.XXXXXX")
cleanup_opendde_inputs() {
    rm -rf -- "$opendde_input_root"
}
trap cleanup_opendde_inputs EXIT
# The target scratch filesystem may not support preserving source mode or
# ownership metadata (for example, some network-backed Slurm TMPDIRs).  The
# task only needs the snapshot contents and symlink relationships, so copy
# recursively while allowing the destination filesystem to choose metadata.
cp -R --no-preserve=mode,ownership -- "$input_root"/. "$opendde_input_root"/
writable_input_file="$opendde_input_root/$input_relative_path"

if [[ ! -f "$writable_input_file" ]]; then
    echo "Failed to prepare writable OpenDDE input snapshot" >&2
    exit 1
fi

# Template inference downloads missing mmCIF files beneath
# ``$OPENDDE_ROOT_DIR/search_database/mmcif``.  Keep the production database
# mount read-only and expose its trusted contents through symlinks inside a
# task-private writable root.  Newly fetched template files then live only for
# this task and disappear with the other temporary inputs.
readonly_opendde_root="${OPENDDE_ROOT_DIR:-/mnt/db/opendde}"
writable_opendde_root="$opendde_input_root/.opendde-runtime"
mkdir -p "$writable_opendde_root/search_database/mmcif"
for source_path in "$readonly_opendde_root"/*; do
    [[ -e "$source_path" ]] || continue
    source_name=$(basename "$source_path")
    [[ "$source_name" == "search_database" ]] && continue
    ln -s "$source_path" "$writable_opendde_root/$source_name"
done
if [[ -d "$readonly_opendde_root/search_database" ]]; then
    for source_path in "$readonly_opendde_root/search_database"/*; do
        [[ -e "$source_path" ]] || continue
        source_name=$(basename "$source_path")
        [[ "$source_name" == "mmcif" ]] && continue
        ln -s "$source_path" "$writable_opendde_root/search_database/$source_name"
    done
fi
if [[ -d "$readonly_opendde_root/search_database/mmcif" ]]; then
    for source_path in "$readonly_opendde_root/search_database/mmcif"/*; do
        [[ -e "$source_path" ]] || continue
        ln -s "$source_path" "$writable_opendde_root/search_database/mmcif/$(basename "$source_path")"
    done
fi
export OPENDDE_ROOT_DIR="$writable_opendde_root"

# Parse TASK_PARAMS JSON into env vars.
MODEL_NAME="$(_parse_param model_name)"
NUM_SAMPLES="$(_parse_param num_samples)"
NUM_STEPS="$(_parse_param num_steps)"
NUM_CYCLES="$(_parse_param num_cycles)"
USE_MSA="$(_parse_param use_msa)"
USE_TEMPLATE="$(_parse_param use_template)"
SEEDS="$(_parse_param seeds)"
DTYPE="$(_parse_param dtype)"
CHECKPOINT="$(_parse_param checkpoint)"
ENABLE_CACHE="$(_parse_param enable_cache)"
ENABLE_TF32="$(_parse_param enable_tf32)"
DETERMINISTIC="$(_parse_param deterministic)"
NEED_ATOM_CONFIDENCE="$(_parse_param need_atom_confidence)"
USE_DEFAULT_PARAMS="$(_parse_param use_default_params)"
USE_TFG_GUIDANCE="$(_parse_param use_tfg_guidance)"

# v1.2.0 validates the input JSON constraint field instead of ignoring it.
# Contact and epitope guidance affect the prediction only when TFG is enabled;
# upstream merely warns for contact without it, so refuse here rather than
# publish an unguided structure as if the constraint had been applied.
CONSTRAINT_PRESENT=$(python3 - "$writable_input_file" "$USE_TFG_GUIDANCE" <<'PY'
import json
import sys

path, guided = sys.argv[1], sys.argv[2] == "true"
constraint = json.load(open(path, encoding="utf-8")).get("constraint")
if constraint is None:
    print("false")
    raise SystemExit(0)
if not isinstance(constraint, dict):
    raise SystemExit("OpenDDE refuses a non-object constraint field")
if constraint.get("contact") and not guided:
    raise SystemExit(
        "constraint.contact requires use_tfg_guidance; refusing to run an unguided prediction"
    )
if constraint.get("epitope") is not None and not guided:
    raise SystemExit(
        "constraint.epitope requires use_tfg_guidance; refusing to run an unguided prediction"
    )
print("true")
PY
)

echo "Processing $input_file ..."
echo "Output directory: $output_dir"
echo "Model: $MODEL_NAME  Checkpoint: $CHECKPOINT  Samples: $NUM_SAMPLES  Steps: $NUM_STEPS  Cycles: $NUM_CYCLES"
echo "MSA: $USE_MSA  Template: $USE_TEMPLATE"

# OpenDDE inference — MSA + template search happens inside opendde pred
# if enabled (requires network access and search databases). v1.2.0 keeps the
# unified pred command and its independent --use_msa/--use_template flags; the
# new inputprep command always searches MSA, template, and RNA together, so it
# cannot preserve those toggles.
# Use the supported PyTorch triangle kernels and disable efficient fusion.
# The auto-selected cuequivariance/Triton path compiles a launcher at runtime
# and therefore requires a C toolchain, which is intentionally absent from the
# production inference image.  These flags still exist in opendde 1.2.0.
echo "REVODESIGN_STAGE:opendde"

opendde_args=(pred \
    -i "$writable_input_file" \
    -o "$output_dir" \
    -n "$MODEL_NAME" \
    --dtype "$DTYPE" \
    --sample "$NUM_SAMPLES" \
    --step "$NUM_STEPS" \
    --cycle "$NUM_CYCLES" \
    --use_msa "$USE_MSA" \
    --use_template "$USE_TEMPLATE" \
    --trimul_kernel torch \
    --triatt_kernel torch \
    --enable_fusion false \
    --enable_cache "$ENABLE_CACHE" \
    --enable_tf32 "$ENABLE_TF32" \
    --deterministic "$DETERMINISTIC" \
    --need_atom_confidence "$NEED_ATOM_CONFIDENCE" \
    --use_default_params "$USE_DEFAULT_PARAMS" \
    --use_tfg_guidance "$USE_TFG_GUIDANCE" \
    --use_rna_msa false)
[[ "$CHECKPOINT" == "antibody_antigen" ]] && opendde_args+=(--load_checkpoint_path "$OPENDDE_ROOT_DIR/checkpoint/opendde_abag.pt")
[[ -n "$SEEDS" ]] && opendde_args+=(--seeds "$SEEDS")
opendde "${opendde_args[@]}"

# Some OpenDDE versions catch per-input inference exceptions and still exit 0,
# leaving MSA intermediates plus ERR/error.txt.  Only a non-empty predicted
# structure proves successful inference.
if [[ -d "$output_dir/ERR" ]] && find "$output_dir/ERR" -type f -size +0c -print -quit | grep -q .; then
    echo "OpenDDE reported an internal inference error" >&2
    exit 1
fi
if ! find "$output_dir" -type f -size +0c \
    \( -iname '*.pdb' -o -iname '*.cif' -o -iname '*.mmcif' \) \
    -print -quit | grep -q .; then
    echo "OpenDDE exited without producing a structure artifact" >&2
    exit 1
fi

# v1.2.0 changed its own precision defaults and began interpreting constraints.
# The Runner passes precision/TFG flags explicitly, even with
# --use_default_params (which upstream applies only to cycle and step), and
# passes the input JSON unchanged. Preserve requested and effective values with
# their sources so the result reports what the upstream command received.
python3 - "$output_dir/inference_settings.json" "$DTYPE" "$ENABLE_TF32" \
    "$USE_TFG_GUIDANCE" "$CONSTRAINT_PRESENT" "$USE_DEFAULT_PARAMS" <<'PY'
import json
import sys

path, dtype, enable_tf32, use_tfg_guidance, constraint_present, use_default_params = sys.argv[1:7]
enable_tf32 = enable_tf32 == "true"
use_tfg_guidance = use_tfg_guidance == "true"
constraint_present = constraint_present == "true"
use_default_params = use_default_params == "true"
settings = {
    "upstream_version": "1.2.0",
    "requested": {
        "dtype": dtype,
        "enable_tf32": enable_tf32,
        "use_tfg_guidance": use_tfg_guidance,
        "constraint_present": constraint_present,
        "use_default_params": use_default_params,
    },
    "effective": {
        "dtype": dtype,
        "enable_tf32": enable_tf32,
        "use_tfg_guidance": use_tfg_guidance,
        "constraint": {
            "present": constraint_present,
            "input_handling": "passed_unchanged_to_upstream",
            "guidance": "tfg_enabled" if constraint_present and use_tfg_guidance else (
                "tfg_disabled" if constraint_present else "not_applicable"
            ),
        },
    },
    "effective_sources": {
        "dtype": "explicit_cli_argument",
        "enable_tf32": "explicit_cli_argument",
        "use_tfg_guidance": "explicit_cli_argument",
        "constraint": "input_json_passthrough",
    },
    "upstream_default_params_overrides": ["cycle", "step"] if use_default_params else [],
    "trimul_kernel": "torch",
    "triatt_kernel": "torch",
    "enable_fusion": False,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(settings, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

touch "${output_dir}/task_finished"
echo "OpenDDE inference complete."
