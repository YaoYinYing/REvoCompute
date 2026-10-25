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


def test_undeclared_fixed_positions_parameter_does_not_change_dispatch(tmp_path):
    """An undeclared parameter is not adapter input, even when it reaches TASK_PARAMS.

    No MPNN Task declares ``fixed_positions``, so the adapter reads nothing from it: the
    argv handed to the pinned upstream CLI and the produced outputs must be identical with
    and without the value. This observes executable behavior rather than the variable's
    source text, and fails if a future adapter starts dispatching the field without a
    declared Task contract.
    """
    input_file = tmp_path / "input.pdb"
    input_file.write_text("ATOM\n", encoding="utf-8")
    mpnn_root = tmp_path / "ProteinMPNN"
    mpnn_root.mkdir()
    (mpnn_root / "protein_mpnn_run.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "open(os.environ['CAPTURE_ARGV'], 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
        "out = Path(sys.argv[sys.argv.index('--out_folder') + 1])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'seq.fa').write_text('>design_1\\nACDE\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    declared = {"num_seq_per_target": 2, "sampling_temp": "0.1", "batch_size": 1}
    runs = []
    for label, params in (("declared", declared), ("undeclared", {**declared, "fixed_positions": "A:10 A:11"})):
        capture = tmp_path / f"{label}.argv.json"
        output_dir = tmp_path / "outputs"
        env = os.environ.copy()
        env.update({"TASK_TYPE": "proteinmpnn", "MPNN_PATH": str(mpnn_root), "CAPTURE_ARGV": str(capture)})
        completed = _run_with_manifest(MPNN_RUNNER_SCRIPT, input_file, output_dir, env, params=params)
        assert completed.returncode == 0, completed.stderr
        runs.append((json.loads(capture.read_text(encoding="utf-8")), (output_dir / "seq.fa").read_bytes()))

    (declared_argv, declared_output), (undeclared_argv, undeclared_output) = runs
    assert undeclared_argv == declared_argv
    assert undeclared_output == declared_output
    assert "--fixed_positions" not in undeclared_argv
    assert "fixed_positions" not in undeclared_argv
