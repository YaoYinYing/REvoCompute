# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from runner_protocol import ROOT, run_with_manifest

COLABFOLD_RUNNER_SCRIPT = ROOT / "docker/runners/colabfold_af2/run.sh"
_run_with_manifest = partial(run_with_manifest, role="sequence")

def _write_fake_colabfold(tmp_path: Path) -> Path:
    executable = tmp_path / "colabfold_batch"
    executable.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        'printf "%s\\n" "$@" > "$FAKE_ARGS_FILE"\n'
        "output_dir=${@: -1}\n"
        'if [[ " $* " == *" --msa-only "* ]]; then\n'
        '  printf ">query\\nAAAA\\n" > "$output_dir/query.a3m"\n'
        "else\n"
        '  printf "MODEL\\n" > "$output_dir/query_unrelaxed_rank_001_model_1.pdb"\n'
        "fi\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable

def test_colabfold_feature_stage_uses_online_msa_and_stops_before_modeling(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_context = tmp_path / "task_context.sh"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    fake_context.write_text(
        '_parse_param() { case "$1" in model_type) echo auto;; msa_mode) echo mmseqs2_uniref_env;; '
        'num_recycle) echo 3;; num_models) echo 5;; num_seeds) echo 1;; random_seed) echo 0;; num_relax) echo 1;; esac; }\n'
            'task_input() { printf "%s\\n" "$FAKE_PRIMARY_INPUT"; }\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "COLABFOLD_BATCH": str(_write_fake_colabfold(tmp_path)),
            "FAKE_ARGS_FILE": str(fake_args),
            "FAKE_PRIMARY_INPUT": str(input_file),
            "TASK_CONTEXT_SRC": str(fake_context),
        }
    )
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "features"))

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8")
    assert "--msa-only" in args
    assert "--host-url\nhttps://api.colabfold.com" in args
    assert "--data\n/mnt/colabfold" in args
    assert (output_dir / ".colabfold-msa-complete").is_file()
    assert not (output_dir / "task_finished").exists()

def test_colabfold_model_stage_reuses_msa_and_relaxes_on_gpu(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_context = tmp_path / "task_context.sh"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    (output_dir / ".colabfold-msa-complete").touch()
    (output_dir / "query.a3m").write_text(">query\nAAAA\n", encoding="utf-8")
    fake_context.write_text(
        '_parse_param() { case "$1" in model_type) echo auto;; msa_mode) echo mmseqs2_uniref_env;; num_recycle) echo 3;; num_models) echo 5;; num_seeds) echo 1;; random_seed) echo 0;; num_relax) echo 1;; esac; }\n'
            'task_input() { printf "%s\\n" "$FAKE_PRIMARY_INPUT"; }\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "COLABFOLD_BATCH": str(_write_fake_colabfold(tmp_path)),
            "FAKE_ARGS_FILE": str(fake_args),
            "FAKE_PRIMARY_INPUT": str(input_file),
            "TASK_CONTEXT_SRC": str(fake_context),
        }
    )
    completed = _run_with_manifest(
        COLABFOLD_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        extra_args=("-s", "model"),
        params={
            "model_type": "auto",
            "msa_mode": "mmseqs2_uniref_env",
            "num_recycle": 3,
            "num_models": 5,
            "num_seeds": 1,
            "random_seed": 0,
            "num_relax": 1,
        },
    )

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8")
    assert "--msa-only" not in args
    assert "--amber\n--use-gpu-relax\n--num-relax\n1" in args
    assert (output_dir / "task_finished").is_file()
