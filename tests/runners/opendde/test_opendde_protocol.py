# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from runner_protocol import ROOT, run_with_manifest

OPENDDE_RUNNER_SCRIPT = ROOT / "docker/runners/opendde/run.sh"
TASK_CONTEXT_SRC = ROOT / "docker" / "runners" / "common" / "task_context.sh"
_run_with_manifest = partial(run_with_manifest, role="specification")

def _write_fake_context(tmp_path: Path, **parameters) -> Path:
    defaults = {
        "model_name": "opendde_v1",
        "num_samples": 1,
        "num_steps": 10,
        "num_cycles": 1,
        "use_msa": "false",
        "use_template": "false",
        "seeds": "",
        "dtype": "fp32",
        "checkpoint": "released",
        "enable_cache": "true",
        "enable_tf32": "true",
        "deterministic": "false",
        "need_atom_confidence": "true",
        "use_default_params": "false",
        "use_tfg_guidance": "false",
        **parameters,
    }
    resolved = " ".join(f"{name}) echo {value};;" for name, value in defaults.items())
    script = tmp_path / "task_context.sh"
    script.write_text(
        f'source "{TASK_CONTEXT_SRC}"\n'
        f'_parse_param() {{ case "$1" in {resolved} esac; }}\n',
        encoding="utf-8",
    )
    return script


def _write_fake_opendde(bin_dir: Path) -> None:
    executable = bin_dir / "opendde"
    executable.write_text(
        """#!/bin/bash
set -euo pipefail
[[ "$1" == "pred" ]]
shift
printf '%s\\n' "$@" > "${FAKE_OPENDDE_ARGS_FILE:-/dev/null}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -i) input_file=$2; shift 2 ;;
        -o) output_dir=$2; shift 2 ;;
        *) shift ;;
    esac
done
snapshot_root=${input_file%/structures/job.json}
test -f "$snapshot_root/config/settings.json"
printf '{}\\n' > "${input_file%.json}-update-msa.json"
if [[ "${FAKE_OPENDDE_CHECK_RUNTIME_ROOT:-no}" == "yes" ]]; then
    test -f "$OPENDDE_ROOT_DIR/checkpoint/opendde.pt"
    printf 'downloaded template\\n' > "$OPENDDE_ROOT_DIR/search_database/mmcif/fetched.cif"
fi
if [[ "${FAKE_OPENDDE_RESULT:-yes}" == "yes" ]]; then
    printf 'data_model\\n' > "$output_dir/model.cif"
elif [[ "${FAKE_OPENDDE_RESULT:-yes}" == "error" ]]; then
    mkdir -p "$output_dir/ERR" "$output_dir/job/msa"
    printf 'internal failure\\n' > "$output_dir/ERR/error.txt"
    printf '>query\\nAAAA\\n' > "$output_dir/job/msa/intermediate.a3m"
fi
"""
    )
    executable.chmod(0o755)

def _run_opendde(tmp_path, *, database_root=None, fake_context=None, **env_overrides):
    """Run the real entrypoint against a nested immutable input snapshot."""
    input_root = tmp_path / "workspace" / "inputs"
    input_file = input_root / "structures" / "job.json"
    auxiliary = input_root / "config" / "settings.json"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    input_file.parent.mkdir(parents=True)
    auxiliary.parent.mkdir(parents=True)
    output_dir.mkdir()
    bin_dir.mkdir()
    (bin_dir / ".keep").write_text("")
    input_file.write_text("{}\n")
    auxiliary.write_text("{}\n")
    _write_fake_opendde(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["TASK_CONTEXT_SRC"] = str(fake_context or _write_fake_context(tmp_path))
    if database_root is not None:
        env["OPENDDE_ROOT_DIR"] = str(database_root)
    env.update(env_overrides)
    completed = _run_with_manifest(OPENDDE_RUNNER_SCRIPT, input_file, output_dir, env)
    return completed, input_file, auxiliary, output_dir


def test_opendde_runner_preserves_read_only_nested_snapshot(tmp_path):
    completed, input_file, auxiliary, output_dir = _run_opendde(tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "model.cif").read_text() == "data_model\n"
    assert (output_dir / "task_finished").is_file()
    assert not (input_file.parent / "job-update-msa.json").exists()
    assert auxiliary.read_text() == "{}\n"


def test_opendde_runner_uses_task_private_template_cache(tmp_path):
    database_root = tmp_path / "database"
    source_cache = database_root / "search_database" / "mmcif"
    source_cache.mkdir(parents=True)
    (database_root / "checkpoint").mkdir()
    (database_root / "checkpoint" / "opendde.pt").write_text("checkpoint\n")

    completed, _input_file, _auxiliary, output_dir = _run_opendde(
        tmp_path,
        database_root=database_root,
        FAKE_OPENDDE_CHECK_RUNTIME_ROOT="yes",
    )

    assert completed.returncode == 0, completed.stderr
    assert not (source_cache / "fetched.cif").exists()
    assert (output_dir / "model.cif").is_file()


def test_opendde_runner_rejects_zero_exit_without_results(tmp_path):
    completed, _input_file, _auxiliary, output_dir = _run_opendde(
        tmp_path, FAKE_OPENDDE_RESULT="no"
    )

    assert completed.returncode != 0
    assert "without producing a structure artifact" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_opendde_runner_rejects_error_and_msa_intermediates(tmp_path):
    completed, _input_file, _auxiliary, output_dir = _run_opendde(
        tmp_path, FAKE_OPENDDE_RESULT="error"
    )

    assert completed.returncode != 0
    assert "reported an internal inference error" in completed.stderr
    assert not (output_dir / "task_finished").exists()


def test_opendde_runner_passes_the_antibody_antigen_checkpoint(tmp_path):
    fake_args = tmp_path / "opendde.args"
    database_root = tmp_path / "database"
    (database_root / "checkpoint").mkdir(parents=True)
    (database_root / "checkpoint" / "opendde.pt").write_text("checkpoint\n")
    (database_root / "checkpoint" / "opendde_abag.pt").write_text("checkpoint\n")
    fake_context = _write_fake_context(tmp_path, checkpoint="antibody_antigen")
    completed, _input_file, _auxiliary, _output_dir = _run_opendde(
        tmp_path,
        database_root=database_root,
        fake_context=fake_context,
        FAKE_OPENDDE_ARGS_FILE=str(fake_args),
    )

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text().splitlines()
    checkpoint = args[args.index("--load_checkpoint_path") + 1]
    assert checkpoint.endswith("/checkpoint/opendde_abag.pt")
    # The runtime root is task-private, so the checkpoint resolves inside scratch
    # rather than the read-only provisioned mount.
    assert checkpoint.startswith("/tmp/")


def test_opendde_runner_keeps_torch_triangle_kernels_and_no_fusion(tmp_path):
    fake_args = tmp_path / "opendde.args"
    completed, _input_file, _auxiliary, _output_dir = _run_opendde(
        tmp_path, FAKE_OPENDDE_ARGS_FILE=str(fake_args)
    )

    assert completed.returncode == 0, completed.stderr
    args = fake_args.read_text().splitlines()
    assert "--load_checkpoint_path" not in args
    assert args[args.index("--trimul_kernel") + 1] == "torch"
    assert args[args.index("--triatt_kernel") + 1] == "torch"
    assert args[args.index("--enable_fusion") + 1] == "false"
