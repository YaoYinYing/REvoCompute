# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import json
import os
from functools import partial

from runner_protocol import ROOT, run_with_manifest

DYNAMICMPNN_RUNNER_SCRIPT = ROOT / "docker/runners/dynamicmpnn/run.sh"
SERVER_ROOT = ROOT
_run_with_manifest = partial(run_with_manifest, role="structure")

def test_dynamicmpnn_runner_passes_upstream_batch_parameters(tmp_path):
    input_file = tmp_path / "input.pdb"
    input_file.write_text("ATOM\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    upstream = tmp_path / "dynamicMPNN"
    weights = tmp_path / "weights" / "model_params"
    capture = tmp_path / "dynamicmpnn.args"
    upstream.mkdir()
    weights.mkdir(parents=True)
    (weights / "proteinmpnn_v_48_020.pt").write_bytes(b"checkpoint")
    manifest = tmp_path / "model-assets.sha256"
    manifest.write_text(
        f"{hashlib.sha256(b'checkpoint').hexdigest()}  proteinmpnn_v_48_020.pt\n", encoding="ascii"
    )
    (upstream / "run.py").write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "Path(os.environ['DYNAMICMPNN_ARGS']).write_text('\\n'.join(args), encoding='utf-8')\n"
        "out = Path(args[args.index('--out_folder') + 1]) / 'seqs'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'design.fa').write_text('>design\\nACDE\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "DYNAMICMPNN_ARGS": str(capture),
            "DYNAMICMPNN_MODEL_PARAMS": str(weights),
            "DYNAMICMPNN_PATH": str(upstream),
            "DYNAMICMPNN_ASSET_MANIFEST": str(manifest),
            "MODEL_ASSET_VERIFY_SRC": str(SERVER_ROOT / "docker/runners/common/verify_model_asset.sh"),
            "TASK_TYPE": "dynamicmpnn",
        }
    )
    completed = _run_with_manifest(
        DYNAMICMPNN_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        params={"number_of_batches": 2, "batch_size": 3, "sampling_temp": 0.2, "seed": 0},
    )

    assert completed.returncode == 0, completed.stderr
    args = capture.read_text(encoding="utf-8")
    assert "--number_of_batches\n2\n" in args
    assert "--batch_size\n3\n" in args
    assert "--temperature\n0.2\n" in args
    assert args.endswith("--seed\n0")
    assert (output_dir / "task_finished").is_file()

    capture.unlink()
    (weights / "proteinmpnn_v_48_020.pt").write_bytes(b"changed")
    rejected = _run_with_manifest(
        DYNAMICMPNN_RUNNER_SCRIPT,
        input_file,
        tmp_path / "rejected",
        env,
        params={"number_of_batches": 2, "batch_size": 3, "sampling_temp": 0.2, "seed": 7},
    )
    assert rejected.returncode != 0
    assert not capture.exists()
