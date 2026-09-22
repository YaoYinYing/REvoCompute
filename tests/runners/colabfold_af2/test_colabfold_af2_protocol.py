# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
from functools import partial
from pathlib import Path

from runner_protocol import ROOT, run_with_manifest

COLABFOLD_RUNNER_SCRIPT = ROOT / "docker/runners/colabfold_af2/run.sh"
COLABFOLD_NORMALIZER = ROOT / "docker/runners/colabfold_af2/normalize_interface_scores.py"
_run_with_manifest = partial(run_with_manifest, role="sequence")

def _write_fake_context(tmp_path: Path, **parameters) -> Path:
    values = {
        "model_type": "auto",
        "msa_mode": "mmseqs2_uniref_env",
        "num_recycle": 3,
        "num_models": 5,
        "num_seeds": 1,
        "random_seed": 0,
        "num_relax": 1,
        "use_fast_kernels": "false",
        "kernel_backend": "auto",
        "compile_mode": "tuned",
        **parameters,
    }
    resolved = " ".join(f"{name}) echo {value};;" for name, value in values.items())
    script = tmp_path / "task_context.sh"
    script.write_text(
        f'_parse_param() {{ case "$1" in {resolved} esac; }}\n'
        'task_input() { printf "%s\\n" "$FAKE_PRIMARY_INPUT"; }\n',
        encoding="utf-8",
    )
    return script

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
        '  if [[ "${FAKE_INTERFACE_SCORES:-no}" == "yes" ]]; then\n'
        '    printf \'{"ptm":0.8,"ipsae":{"A-B":0.61,"A-C":0.74},"pdockq2":{"A-B":0.71,"A-C":0.42}}\\n\''
        ' > "$output_dir/query_scores_rank_001_model_1.json"\n'
        "  fi\n"
        "fi\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable

def _runner_env(tmp_path: Path, fake_context: Path, input_file: Path, fake_args: Path) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "COLABFOLD_BATCH": str(_write_fake_colabfold(tmp_path)),
            "COLABFOLD_NORMALIZER": str(COLABFOLD_NORMALIZER),
            "FAKE_ARGS_FILE": str(fake_args),
            "FAKE_PRIMARY_INPUT": str(input_file),
            "TASK_CONTEXT_SRC": str(fake_context),
        }
    )
    return env

def test_colabfold_feature_stage_uses_online_msa_and_stops_before_modeling(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
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
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    (output_dir / ".colabfold-msa-complete").touch()
    (output_dir / "query.a3m").write_text(">query\nAAAA\n", encoding="utf-8")
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
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

def test_colabfold_model_stage_leaves_fused_kernels_off_by_default(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    (output_dir / ".colabfold-msa-complete").touch()
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8").splitlines()
    assert "--use-fast-kernels" not in args
    assert args[args.index("--kernel-backend") + 1] == "auto"
    assert args[args.index("--compile-mode") + 1] == "tuned"

def test_colabfold_model_stage_forwards_requested_kernel_settings(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    (output_dir / ".colabfold-msa-complete").touch()
    fake_context = _write_fake_context(
        tmp_path,
        use_fast_kernels="true",
        kernel_backend="pallas",
        compile_mode="full",
    )
    env = _runner_env(tmp_path, fake_context, input_file, fake_args)
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text(encoding="utf-8").splitlines()
    assert "--use-fast-kernels" in args
    assert args[args.index("--kernel-backend") + 1] == "pallas"
    assert args[args.index("--compile-mode") + 1] == "full"

def test_colabfold_model_stage_summarizes_complex_interface_confidence(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    (output_dir / ".colabfold-msa-complete").touch()
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    env["FAKE_INTERFACE_SCORES"] = "yes"
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((output_dir / "interface_scores.json").read_text(encoding="utf-8"))
    assert summary["interface"] == "A-C"
    assert summary["ipsae"] == 0.74
    assert summary["pdockq2"] == 0.42
    assert summary["scores_file"] == "query_scores_rank_001_model_1.json"

def test_colabfold_model_stage_omits_interface_summary_for_monomers(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    fake_args = tmp_path / "colabfold.args"
    input_file.write_text(">test\nAAAA\n", encoding="utf-8")
    output_dir.mkdir()
    (output_dir / ".colabfold-msa-complete").touch()
    env = _runner_env(tmp_path, _write_fake_context(tmp_path), input_file, fake_args)
    completed = _run_with_manifest(COLABFOLD_RUNNER_SCRIPT, input_file, output_dir, env, extra_args=("-s", "model"))

    assert completed.returncode == 0, completed.stderr
    assert not (output_dir / "interface_scores.json").exists()
    assert (output_dir / "task_finished").is_file()
