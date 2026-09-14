# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
from functools import partial

from runner_protocol import ROOT, run_with_manifest

ESMDYNAMIC_RUNNER_SCRIPT = ROOT / "docker/runners/esmdynamic/run.sh"
_run_with_manifest = partial(run_with_manifest, role="sequence")

def test_esmdynamic_runner_uses_the_manifest_parameters(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    args_file = tmp_path / "esmdynamic.args"
    input_file.write_text(">test\nACDE\n", encoding="utf-8")
    bin_dir.mkdir()
    runner = bin_dir / "run_esmdynamic"
    runner.write_text(
        "#!/bin/bash\n"
        'printf \'%s\\n\' "$@" > "$ESMDYNAMIC_ARGS_FILE"\n'
        'for arg in "$@"; do [[ $previous == output_dir ]] && output_dir=$arg; previous=${arg#--}; done\n'
        'mkdir -p "$output_dir"\n'
        'printf result > "$output_dir/result.txt"\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "ESMDYNAMIC_ARGS_FILE": str(args_file)})
    completed = _run_with_manifest(
        ESMDYNAMIC_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        params={"batch_size": 2, "chunk_size": 128, "low_memory": True, "num_recycles": 3},
    )

    assert completed.returncode == 0, completed.stderr
    args = args_file.read_text(encoding="utf-8")
    assert "--batch_size\n2\n" in args
    assert "--chunk_size\n128\n" in args
    assert "--low_memory" in args
    assert "--num_recycles\n3\n" in args
    assert (output_dir / "task_finished").is_file()

def test_esmdynamic_failure_does_not_report_complete(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    input_file.write_text(">test\nACDE\n", encoding="utf-8")
    bin_dir.mkdir()
    runner = bin_dir / "run_esmdynamic"
    runner.write_text("#!/bin/bash\nexit 2\n", encoding="utf-8")
    runner.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    completed = _run_with_manifest(ESMDYNAMIC_RUNNER_SCRIPT, input_file, output_dir, env)

    assert completed.returncode == 2
    assert not (output_dir / "task_finished").exists()
