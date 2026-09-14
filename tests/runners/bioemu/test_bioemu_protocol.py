# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
from functools import partial

from runner_protocol import ROOT, run_with_manifest

BIOEMU_RUNNER_SCRIPT = ROOT / "docker/runners/bioemu/run.sh"
_run_with_manifest = partial(run_with_manifest, role="sequence")

def test_bioemu_non_default_sample_count_reaches_upstream(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    module_root = tmp_path / "modules"
    checkpoint_root = tmp_path / "checkpoint"
    capture = tmp_path / "bioemu.argv"
    input_file.write_text(">test\nACDE\n", encoding="utf-8")
    (module_root / "bioemu").mkdir(parents=True)
    checkpoint_root.mkdir()
    (checkpoint_root / "checkpoint.ckpt").write_bytes(b"checkpoint")
    (checkpoint_root / "config.yaml").write_text("model: test\n", encoding="utf-8")
    (module_root / "bioemu" / "__init__.py").write_text("", encoding="utf-8")
    (module_root / "bioemu" / "sample.py").write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['BIOEMU_ARGV']).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "BIOEMU_CHECKPOINT_ROOT": str(checkpoint_root),
            "BIOEMU_ARGV": str(capture),
            "PYTHONPATH": f"{module_root}:{env.get('PYTHONPATH', '')}",
        }
    )

    completed = _run_with_manifest(
        BIOEMU_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        params={
            "num_samples": 137,
            "batch_size_100": 7,
            "denoiser_type": "heun",
            "filter_samples": False,
            "base_seed": 19,
        },
    )

    assert completed.returncode == 0, completed.stderr
    argv = capture.read_text(encoding="utf-8").splitlines()
    assert argv[:3] == [str(input_file), "137", str(output_dir)]
    assert "--batch_size_100=7" in argv
    assert "--denoiser_type=heun" in argv
    assert "--filter_samples=false" in argv
    assert "--base_seed=19" in argv
