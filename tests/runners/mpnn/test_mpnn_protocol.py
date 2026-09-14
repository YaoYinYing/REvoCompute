# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import os
from functools import partial

from runner_protocol import ROOT, run_with_manifest

MPNN_RUNNER_SCRIPT = ROOT / "docker/runners/mpnn/run.sh"
_run_with_manifest = partial(run_with_manifest, role="structure")

def test_ligandmpnn_runner_omits_blank_optional_cli_values(tmp_path):
    input_file = tmp_path / "input.pdb"
    output_dir = tmp_path / "outputs"
    ligand_root = tmp_path / "LigandMPNN"
    capture = tmp_path / "argv.json"
    input_file.write_text("ATOM\n", encoding="utf-8")
    output_dir.mkdir()
    ligand_root.mkdir()
    (ligand_root / "model_params").mkdir()
    (ligand_root / "model_params" / "ligandmpnn_v_32_010_25.pt").write_bytes(b"checkpoint")
    (ligand_root / "run.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "open(os.environ['CAPTURE_ARGV'], 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
        "out = Path(sys.argv[sys.argv.index('--out_folder') + 1]) / 'seqs'\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'input.fa').write_text('>design_1\\nACDE\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "TASK_TYPE": "ligandmpnn",
            "LIGANDMPNN_PATH": str(ligand_root),
            "CAPTURE_ARGV": str(capture),
        }
    )
    completed = _run_with_manifest(
        MPNN_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        params={"seed": "", "batch_size": 2, "verbose": 0, "chains_to_design": ""},
    )

    assert completed.returncode == 0, completed.stderr
    argv = json.loads(capture.read_text(encoding="utf-8"))
    assert "--seed" not in argv
    assert "--chains_to_design" not in argv
    assert argv[argv.index("--batch_size") + 1] == "2"
    assert argv[argv.index("--verbose") + 1] == "0"
    assert (output_dir / "seqs" / "input.fa").read_text(encoding="utf-8") == ">design_1\nACDE\n"
    assert (output_dir / "task_finished").is_file()
