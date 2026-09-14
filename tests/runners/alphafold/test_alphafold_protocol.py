# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from functools import partial

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
        'for arg in "$@"; do case "$arg" in --output_dir=*) output_dir=${arg#*=} ;; esac; done\n'
        'printf "Running model model_1\\n" >&2\n'
        'mkdir -p "$output_dir/model"\n'
        'printf "MODEL\\n" > "$output_dir/model/ranked_0.pdb"\n',
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
            "ALPHAFOLD_STAGE_TRANSLATOR": str(SERVER_ROOT / "docker" / "runners" / "common" / "stage_translate.py"),
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
