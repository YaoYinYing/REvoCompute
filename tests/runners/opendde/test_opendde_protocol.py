# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from runner_protocol import ROOT, run_with_manifest

OPENDDE_RUNNER_SCRIPT = ROOT / "docker/runners/opendde/run.sh"
_run_with_manifest = partial(run_with_manifest, role="specification")

def _write_fake_opendde(bin_dir: Path) -> None:
    executable = bin_dir / "opendde"
    executable.write_text(
        """#!/bin/bash
set -euo pipefail
[[ "$1" == "pred" ]]
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        -i) input_file=$2; shift 2 ;;
        -o) output_dir=$2; shift 2 ;;
        *) shift ;;
    esac
done
snapshot_root=${input_file%/structures/job.json}
test -f "$snapshot_root/config/settings.json"
printf '{}\n' > "${input_file%.json}-update-msa.json"
if [[ "${FAKE_OPENDDE_CHECK_RUNTIME_ROOT:-no}" == "yes" ]]; then
    test -f "$OPENDDE_ROOT_DIR/checkpoint/opendde.pt"
    printf 'downloaded template\n' > "$OPENDDE_ROOT_DIR/search_database/mmcif/fetched.cif"
fi
if [[ "${FAKE_OPENDDE_RESULT:-yes}" == "yes" ]]; then
    printf 'data_model\n' > "$output_dir/model.cif"
elif [[ "${FAKE_OPENDDE_RESULT:-yes}" == "error" ]]; then
    mkdir -p "$output_dir/ERR" "$output_dir/job/msa"
    printf 'internal failure\n' > "$output_dir/ERR/error.txt"
    printf '>query\nAAAA\n' > "$output_dir/job/msa/intermediate.a3m"
fi
"""
    )
    executable.chmod(0o755)

def test_opendde_runner_preserves_read_only_nested_snapshot(tmp_path):
    input_root = tmp_path / "workspace" / "inputs"
    input_file = input_root / "structures" / "job.json"
    auxiliary = input_root / "config" / "settings.json"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    input_file.parent.mkdir(parents=True)
    auxiliary.parent.mkdir(parents=True)
    output_dir.mkdir()
    bin_dir.mkdir()
    input_file.write_text("{}\n")
    auxiliary.write_text("{}\n")
    _write_fake_opendde(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    completed = _run_with_manifest(OPENDDE_RUNNER_SCRIPT, input_file, output_dir, env)

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "model.cif").read_text() == "data_model\n"
    assert (output_dir / "task_finished").is_file()
    assert not (input_file.parent / "job-update-msa.json").exists()
    assert auxiliary.read_text() == "{}\n"

def test_opendde_runner_uses_task_private_template_cache(tmp_path):
    input_root = tmp_path / "workspace" / "inputs"
    input_file = input_root / "structures" / "job.json"
    auxiliary = input_root / "config" / "settings.json"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    database_root = tmp_path / "database"
    source_cache = database_root / "search_database" / "mmcif"
    input_file.parent.mkdir(parents=True)
    auxiliary.parent.mkdir(parents=True)
    output_dir.mkdir()
    bin_dir.mkdir()
    source_cache.mkdir(parents=True)
    (database_root / "checkpoint").mkdir()
    (database_root / "checkpoint" / "opendde.pt").write_text("checkpoint\n")
    input_file.write_text("{}\n")
    auxiliary.write_text("{}\n")
    _write_fake_opendde(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["OPENDDE_ROOT_DIR"] = str(database_root)
    env["FAKE_OPENDDE_CHECK_RUNTIME_ROOT"] = "yes"
    completed = _run_with_manifest(OPENDDE_RUNNER_SCRIPT, input_file, output_dir, env)

    assert completed.returncode == 0, completed.stderr
    assert not (source_cache / "fetched.cif").exists()
    assert (output_dir / "model.cif").is_file()

def test_opendde_runner_rejects_zero_exit_without_results(tmp_path):
    input_root = tmp_path / "workspace" / "inputs"
    input_file = input_root / "structures" / "job.json"
    auxiliary = input_root / "config" / "settings.json"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    input_file.parent.mkdir(parents=True)
    auxiliary.parent.mkdir(parents=True)
    output_dir.mkdir()
    bin_dir.mkdir()
    input_file.write_text("{}\n")
    auxiliary.write_text("{}\n")
    _write_fake_opendde(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_OPENDDE_RESULT"] = "no"
    completed = _run_with_manifest(OPENDDE_RUNNER_SCRIPT, input_file, output_dir, env)

    assert completed.returncode != 0
    assert "without producing a structure artifact" in completed.stderr
    assert not (output_dir / "task_finished").exists()
def test_opendde_runner_rejects_error_and_msa_intermediates(tmp_path):
    input_root = tmp_path / "workspace" / "inputs"
    input_file = input_root / "structures" / "job.json"
    auxiliary = input_root / "config" / "settings.json"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    input_file.parent.mkdir(parents=True)
    auxiliary.parent.mkdir(parents=True)
    output_dir.mkdir()
    bin_dir.mkdir()
    input_file.write_text("{}\n")
    auxiliary.write_text("{}\n")
    _write_fake_opendde(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_OPENDDE_RESULT"] = "error"
    completed = _run_with_manifest(OPENDDE_RUNNER_SCRIPT, input_file, output_dir, env)

    assert completed.returncode != 0
    assert "reported an internal inference error" in completed.stderr
    assert not (output_dir / "task_finished").exists()
