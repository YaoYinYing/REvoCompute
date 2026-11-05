# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
from functools import partial
from pathlib import Path

from runner_protocol import ROOT, run_with_manifest

ALPHAFOLD_RUNNER_SCRIPT = ROOT / "docker/runners/alphafold/run.sh"
SERVER_ROOT = ROOT
_run_with_manifest = partial(run_with_manifest, role="sequence")

def test_alphafold_runner_drains_final_stage_before_exit(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    alphafold_root = tmp_path / "alphafold"
    fake_context = tmp_path / "task_context.sh"
    fake_python = tmp_path / "fake-python"
    delayed_translator = tmp_path / "delayed-stage.awk"
    patterns = tmp_path / "alphafold.stages"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    alphafold_root.mkdir()
    fake_context.write_text(
        '_parse_param() { case "$1" in model_type) echo auto;; msa_mode) echo mmseqs2_uniref_env;; num_recycle) echo 3;; num_models) echo 5;; num_seeds) echo 1;; random_seed) echo 0;; num_relax) echo 1;; esac; }\n'
            'task_input() { printf "%s\\n" "$FAKE_PRIMARY_INPUT"; }\n',
        encoding="utf-8",
    )
    fake_python.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        'for arg in "$@"; do case "$arg" in --output_dir=*) output_dir=${arg#*=} ;; '
        '--fasta_paths=*) fasta=${arg#*=} ;; esac; done\n'
        'job=$(basename "$fasta"); job=${job%.*}\n'
        'printf "Running model model_1\\n" >&2\n'
        'mkdir -p "$output_dir/$job"\n'
        'printf "MODEL\\n" > "$output_dir/$job/ranked_0.pdb"\n'
        "printf '%s\\n' '[{\"predicted_aligned_error\":[[1,2],[2,1]]}]' > \"$output_dir/$job/pae_model_1.json\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    delayed_translator.write_text(
        '{ print > "/dev/stderr"; system("sleep 0.2"); print "REVODESIGN_STAGE:modeling"; fflush() }\n',
        encoding="utf-8",
    )
    patterns.write_text("modeling:Running model model_\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "ALPHAFOLD_PATH": str(alphafold_root),
            "ALPHAFOLD_PYTHON": str(fake_python),
            "ALPHAFOLD_STAGE_TRANSLATOR": str(delayed_translator),
            "ALPHAFOLD_STAGE_PATTERNS": str(patterns),
            "FAKE_PRIMARY_INPUT": str(input_file),
            "TASK_CONTEXT_SRC": str(fake_context),
            "TMPDIR": str(tmp_path),
        }
    )
    completed = _run_with_manifest(ALPHAFOLD_RUNNER_SCRIPT, input_file, output_dir, env)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.index("REVODESIGN_STAGE:modeling") < completed.stdout.index("AlphaFold complete.")
    assert (output_dir / "task_finished").is_file()
def test_alphafold_feature_stage_stops_before_modeling(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    alphafold_root = tmp_path / "alphafold"
    fake_context = tmp_path / "task_context.sh"
    fake_python = tmp_path / "fake-python"
    fake_args = tmp_path / "alphafold.args"
    input_file.write_text(">first\nAAAA\n>second\nBBBB\n", encoding="utf-8")
    output_dir.mkdir()
    alphafold_root.mkdir()
    fake_context.write_text(
        '_parse_param() { [[ "$1" == model_preset ]] && printf "multimer\\n" || printf "%s\\n" "$2"; }\n'
            'task_input() { printf "%s\\n" "$FAKE_PRIMARY_INPUT"; }\n',
        encoding="utf-8",
    )
    fake_python.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        'printf "%s\\n" "$@" > "$FAKE_ARGS_FILE"\n'
        'for arg in "$@"; do\n'
        '  case "$arg" in --output_dir=*) output_dir=${arg#*=} ;; --run_stage=*) stage=${arg#*=} ;; esac\n'
        "done\n"
        '[[ "$stage" == features ]]\n'
        'mkdir -p "$output_dir/input"\n'
        'printf "FEATURES\\n" > "$output_dir/input/features.pkl"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "ALPHAFOLD_PATH": str(alphafold_root),
            "ALPHAFOLD_PYTHON": str(fake_python),
            "FAKE_ARGS_FILE": str(fake_args),
            "FAKE_PRIMARY_INPUT": str(input_file),
            "TASK_CONTEXT_SRC": str(fake_context),
            "ALPHAFOLD_STAGE_TRANSLATOR": str(SERVER_ROOT / "docker" / "runners" / "common" / "runtime" / "stage_translate.py"),
            "ALPHAFOLD_STAGE_PATTERNS": str(SERVER_ROOT / "docker" / "runners" / "alphafold" / "alphafold.stages"),
            "TMPDIR": str(tmp_path),
        }
    )
    completed = _run_with_manifest(
        ALPHAFOLD_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        params={"model_preset": "multimer"},
        extra_args=("-s", "features"),
    )

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8")
    assert "--model_preset=multimer" in args
    assert "--uniref30_database_path=" in args
    assert "--uniprot_database_path=" in args
    assert "--pdb70_database_path=" not in args
    assert (output_dir / ".alphafold-features-complete").is_file()
    assert not (output_dir / "task_finished").exists()


def _write_reuse_fake_alphafold(path):
    path.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        'for arg in "$@"; do case "$arg" in --output_dir=*) output_dir=${arg#*=} ;; '
        '--fasta_paths=*) fasta=${arg#*=} ;; --run_stage=*) stage=${arg#*=} ;; esac; done\n'
        'job=$(basename "$fasta"); job=${job%.*}\n'
        'job_dir="$output_dir/$job"\n'
        'mkdir -p "$job_dir"\n'
        'printf "%s\\n" "$stage" >> "$FAKE_CALL_LOG"\n'
        'if [[ -n "${FAKE_FAIL_STAGE:-}" && "$FAKE_FAIL_STAGE" == "$stage" ]]; then exit 9; fi\n'
        'if [[ "$stage" != model ]]; then\n'
        '  if [[ -e "$job_dir/features.pkl" ]]; then printf "REUSED\\n" > "$job_dir/features.pkl"; '
        'else printf "FRESH\\n" > "$job_dir/features.pkl"; fi\n'
        '  mkdir -p "$job_dir/msas"\n'
        '  printf "MSA\\n" > "$job_dir/msas/query.a3m"\n'
        '  [[ "$stage" == features ]] && exit 0\n'
        "fi\n"
        '[[ -s "$job_dir/features.pkl" ]] || { echo "missing features" >&2; exit 7; }\n'
        'if [[ "${FAKE_NO_STRUCTURE:-}" != "1" ]]; then\n'
        '  if [[ -e "$job_dir/ranked_0.pdb" ]]; then printf "REUSED\\n" > "$job_dir/ranked_0.pdb"; '
        'else printf "FRESH\\n" > "$job_dir/ranked_0.pdb"; fi\n'
        "fi\n"
        'printf "{}\\n" > "$job_dir/ranking_debug.json"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _retry_env(tmp_path):
    input_file = tmp_path / "sequence.fasta"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    fake_context = tmp_path / "task_context.sh"
    fake_context.write_text(
        '_parse_param() { :; }\n'
        'task_input() { printf "%s\\n" "$FAKE_PRIMARY_INPUT"; }\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "ALPHAFOLD_PATH": str(tmp_path),
            "ALPHAFOLD_PYTHON": str(_write_reuse_fake_alphafold(tmp_path / "fake-af2")),
            "FAKE_CALL_LOG": str(tmp_path / "calls"),
            "FAKE_PRIMARY_INPUT": str(input_file),
            "TASK_CONTEXT_SRC": str(fake_context),
            "ALPHAFOLD_STAGE_TRANSLATOR": str(
                SERVER_ROOT / "docker" / "runners" / "common" / "runtime" / "stage_translate.py"
            ),
            "ALPHAFOLD_STAGE_PATTERNS": str(
                SERVER_ROOT / "docker" / "runners" / "alphafold" / "alphafold.stages"
            ),
            "TMPDIR": str(tmp_path),
        }
    )
    return env, input_file, output_dir


def _run_af2_stage(env, input_file, output_dir, stage):
    return _run_with_manifest(ALPHAFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", stage))


def _calls(env):
    path = Path(env["FAKE_CALL_LOG"])
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _staged_features_document(tmp_path, content=b"STAGED-FEATURES\n", *, role="prepared_features", sha256=None):
    """A Server-shaped document for the AF2 ``model.features`` reuse role."""
    artifact = tmp_path / "stage_inputs" / role / "source_job" / "features.pkl"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(content)
    document = tmp_path / "stage_inputs" / "stage_inputs.json"
    document.write_text(
        json.dumps(
            {
                "version": 1,
                "stage": "model",
                "inputs": {
                    role: {
                        "path": str(artifact),
                        "files": [{
                            "path": str(artifact),
                            "sha256": sha256 or hashlib.sha256(content).hexdigest(),
                            "size": len(content),
                        }],
                        "producer": "features",
                        "producer_attempt": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return document, artifact


def _stage_inputs_env(env, document):
    env.update({
        "TASK_STAGE_INPUTS": str(document),
        "ALPHAFOLD_STAGE_INPUTS_PY": str(SERVER_ROOT / "docker" / "runners" / "common" / "runtime" / "stage_inputs.py"),
    })
    return env


def test_alphafold_model_stage_models_the_verified_staged_features(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    document, staged = _staged_features_document(tmp_path)
    _stage_inputs_env(env, document)

    model = _run_af2_stage(env, input_file, output_dir, "model")

    assert model.returncode == 0, model.stderr
    features = output_dir / "sequence" / "features.pkl"
    assert features.read_bytes() == staged.read_bytes()
    assert (output_dir / ".alphafold-features-complete").read_text(encoding="utf-8").strip() == hashlib.sha256(
        staged.read_bytes()
    ).hexdigest()
    assert _calls(env) == ["model"]
    assert (output_dir / "task_finished").is_file()


def test_alphafold_model_stage_refuses_staged_features_that_changed(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    document, staged = _staged_features_document(tmp_path)
    staged.write_bytes(b"STAGED-FEATUREX\n")
    _stage_inputs_env(env, document)

    model = _run_af2_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "digest does not match" in model.stderr
    assert not (output_dir / "sequence" / "features.pkl").exists()
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == []


def test_alphafold_model_stage_ignores_a_document_without_the_reuse_role(tmp_path):
    # A full-mode model stage exports a document for its in-graph "features"
    # role. Only the reuse role selects the staged artifact; without it the
    # attempt still requires this Task's own validated feature tree.
    env, input_file, output_dir = _retry_env(tmp_path)
    document, _ = _staged_features_document(tmp_path, role="features")
    _stage_inputs_env(env, document)

    model = _run_af2_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "Validated AlphaFold features are missing" in model.stderr
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == []


def test_alphafold_full_mode_still_recomputes_its_own_features(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    document, staged = _staged_features_document(tmp_path, content=b"OTHER-TASK-FEATURES\n")
    _stage_inputs_env(env, document)

    full = _run_af2_stage(env, input_file, output_dir, "all")

    assert full.returncode == 0, full.stderr
    assert (output_dir / "sequence" / "features.pkl").read_text(encoding="utf-8") == "FRESH\n"
    assert staged.read_bytes() == b"OTHER-TASK-FEATURES\n"
    assert _calls(env) == ["all"]



def test_alphafold_features_recomputes_and_clears_a_previous_tree(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    stale = output_dir / "sequence"
    stale.mkdir()
    (stale / "features.pkl").write_text("STALE\n", encoding="utf-8")
    (stale / "ranked_0.pdb").write_text("STALE\n", encoding="utf-8")
    (output_dir / "task_finished").write_text("", encoding="utf-8")

    first = _run_af2_stage(env, input_file, output_dir, "features")

    assert first.returncode == 0, first.stderr
    features = stale / "features.pkl"
    assert features.read_text(encoding="utf-8") == "FRESH\n"
    assert not (stale / "ranked_0.pdb").exists()
    assert not (output_dir / "task_finished").exists()
    marker = output_dir / ".alphafold-features-complete"
    assert marker.read_text(encoding="utf-8").strip() == hashlib.sha256(features.read_bytes()).hexdigest()

    rerun = _run_af2_stage(env, input_file, output_dir, "features")

    assert rerun.returncode == 0, rerun.stderr
    assert features.read_text(encoding="utf-8") == "FRESH\n"
    assert _calls(env) == ["features", "features"]


def test_alphafold_model_stage_requires_the_features_marker(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    stale = output_dir / "sequence"
    stale.mkdir()
    (stale / "features.pkl").write_text("STALE\n", encoding="utf-8")
    (stale / "ranked_0.pdb").write_text("STALE\n", encoding="utf-8")
    (output_dir / "task_finished").write_text("", encoding="utf-8")

    model = _run_af2_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "features are missing" in model.stderr
    assert not (stale / "ranked_0.pdb").exists()
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == []


def test_alphafold_model_stage_rejects_changed_features(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_af2_stage(env, input_file, output_dir, "features").returncode == 0
    (output_dir / "sequence" / "features.pkl").write_text("CHANGED\n", encoding="utf-8")

    model = _run_af2_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "changed after feature validation" in model.stderr
    assert not (output_dir / "sequence" / "ranked_0.pdb").exists()
    assert not (output_dir / "task_finished").exists()
    assert _calls(env) == ["features"]


def test_alphafold_model_stage_recomputes_instead_of_reusing_model_outputs(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_af2_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_af2_stage(env, input_file, output_dir, "model").returncode == 0
    ranked = output_dir / "sequence" / "ranked_0.pdb"
    assert ranked.read_text(encoding="utf-8") == "FRESH\n"
    ranked.write_text("STALE\n", encoding="utf-8")

    rerun = _run_af2_stage(env, input_file, output_dir, "model")

    assert rerun.returncode == 0, rerun.stderr
    assert ranked.read_text(encoding="utf-8") == "FRESH\n"
    assert _calls(env) == ["features", "model", "model"]
    assert (output_dir / "task_finished").is_file()


def test_alphafold_missing_structure_is_not_masked_by_a_sibling_tree(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    sibling = output_dir / "other_family"
    sibling.mkdir()
    (sibling / "ranked_0.pdb").write_text("SIBLING\n", encoding="utf-8")
    assert _run_af2_stage(env, input_file, output_dir, "features").returncode == 0

    env["FAKE_NO_STRUCTURE"] = "1"
    model = _run_af2_stage(env, input_file, output_dir, "model")

    assert model.returncode != 0
    assert "produced no ranked_0.pdb" in model.stderr
    assert not (output_dir / "task_finished").exists()
    assert (sibling / "ranked_0.pdb").read_text(encoding="utf-8") == "SIBLING\n"


def test_alphafold_failed_attempt_publishes_no_stale_output(tmp_path):
    env, input_file, output_dir = _retry_env(tmp_path)
    assert _run_af2_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_af2_stage(env, input_file, output_dir, "model").returncode == 0

    env["FAKE_FAIL_STAGE"] = "features"
    failed = _run_af2_stage(env, input_file, output_dir, "features")
    assert failed.returncode == 9
    assert not (output_dir / "sequence" / "features.pkl").exists()
    assert not (output_dir / ".alphafold-features-complete").exists()
    assert not (output_dir / "sequence" / "ranked_0.pdb").exists()
    assert not (output_dir / "task_finished").exists()

    env.pop("FAKE_FAIL_STAGE")
    assert _run_af2_stage(env, input_file, output_dir, "features").returncode == 0
    assert _run_af2_stage(env, input_file, output_dir, "model").returncode == 0

    env["FAKE_FAIL_STAGE"] = "model"
    failed_model = _run_af2_stage(env, input_file, output_dir, "model")
    assert failed_model.returncode == 9
    assert not (output_dir / "sequence" / "ranked_0.pdb").exists()
    assert not (output_dir / "task_finished").exists()
    assert (output_dir / "sequence" / "features.pkl").is_file()
