# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""LigandMPNN side-chain packing: checkpoint forwarding, failure, and result selection.

Upstream defaults ``--checkpoint_path_sc`` to a workdir-relative path that the
mounted checkpoint directory does not satisfy, so the adapter must forward the
provisioned packer checkpoint whenever packing runs. Upstream also always writes
backbone-only structures under ``backbones/`` while packed all-atom structures land
under ``packed/``, so the published packed view must select ``packed/*.pdb`` only.
"""

from __future__ import annotations

import json
import os

from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery
from runner_protocol import ROOT, run_with_manifest

MPNN_RUNNER_SCRIPT = ROOT / "docker/runners/mpnn/run.sh"
TASKS = ROOT / "docker/runners/mpnn/tasks"
SC_CHECKPOINT = "ligandmpnn_sc_v_32_002_16.pt"


def _ligand_root(tmp_path, *, with_sc_checkpoint: bool = True):
    """A fake LigandMPNN tree: the pinned CLI stub plus the provisioned design checkpoint."""
    ligand_root = tmp_path / "LigandMPNN"
    capture = tmp_path / "argv.json"
    model_params = tmp_path / "model_params"
    model_params.mkdir()
    (model_params / "ligandmpnn_v_32_010_25.pt").write_bytes(b"checkpoint")
    if with_sc_checkpoint:
        (model_params / SC_CHECKPOINT).write_bytes(b"checkpoint")
    ligand_root.mkdir()
    (ligand_root / "run.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "open(os.environ['CAPTURE_ARGV'], 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
        "out = Path(sys.argv[sys.argv.index('--out_folder') + 1])\n"
        "(out / 'seqs').mkdir(parents=True, exist_ok=True)\n"
        "(out / 'seqs' / 'input.fa').write_text('>design_1\\nACDE\\n', encoding='utf-8')\n"
        "(out / 'backbones').mkdir(parents=True, exist_ok=True)\n"
        "(out / 'backbones' / 'fake.pdb').write_text('ATOM\\n', encoding='utf-8')\n"
        "(out / 'packed').mkdir(parents=True, exist_ok=True)\n"
        "(out / 'packed' / 'fake_packed.pdb').write_text('ATOM\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "TASK_TYPE": "ligandmpnn",
            "LIGANDMPNN_PATH": str(ligand_root),
            "LIGANDMPNN_MODEL_PARAMS": str(model_params),
            "CAPTURE_ARGV": str(capture),
        }
    )
    return env, capture


def _run(tmp_path, env, params):
    input_file = tmp_path / "input.pdb"
    input_file.write_text("ATOM\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    return run_with_manifest(MPNN_RUNNER_SCRIPT, input_file, output_dir, env, params=params, role="structure")


def test_packing_forwards_provisioned_packer_checkpoint(tmp_path):
    env, capture = _ligand_root(tmp_path)
    completed = _run(tmp_path, env, {"pack_side_chains": 1, "number_of_batches": 1, "batch_size": 1})

    assert completed.returncode == 0, completed.stderr
    argv = json.loads(capture.read_text(encoding="utf-8"))
    assert argv[argv.index("--pack_side_chains") + 1] == "1"
    assert argv[argv.index("--checkpoint_path_sc") + 1] == str(tmp_path / "model_params" / SC_CHECKPOINT)


def test_packing_disabled_does_not_require_or_forward_packer_checkpoint(tmp_path):
    env, capture = _ligand_root(tmp_path, with_sc_checkpoint=False)
    completed = _run(tmp_path, env, {"pack_side_chains": 0, "number_of_batches": 1, "batch_size": 1})

    assert completed.returncode == 0, completed.stderr
    argv = json.loads(capture.read_text(encoding="utf-8"))
    assert "--checkpoint_path_sc" not in argv


def test_packing_without_packer_checkpoint_fails_naming_the_missing_file(tmp_path):
    env, capture = _ligand_root(tmp_path, with_sc_checkpoint=False)
    completed = _run(tmp_path, env, {"pack_side_chains": 1, "number_of_batches": 1, "batch_size": 1})

    assert completed.returncode != 0
    assert SC_CHECKPOINT in completed.stderr
    assert not capture.exists()


PROVENANCE = [
    "citations.bib",
    "debug/inputs/structure/input.pdb",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
]


def _artifacts(*paths):
    return [{"path": path, "size": 10} for path in [*PROVENANCE, *paths]]


def test_packed_view_selects_packed_structures_not_backbones():
    with isolated_discovery(str(ROOT / "docker" / "runners")) as manager:
        task = manager.contributions.resolve("tasks", "ligandmpnn")
        view = next(v for v in task.result_workspace if v.id == "packed_structures")
        selectors = [selector.value for source in view.sources.values() for selector in source]
        tree = expected_file_tree(task, str(ROOT))

    assert "packed/*.pdb" in selectors
    assert "backbones/*.pdb" not in selectors
    assert not any(view.sources[src][0].required for src in view.sources)

    published = _artifacts("seqs/input.fa", "backbones/input_0.pdb", "packed/input_packed_0_1.pdb")
    resolved, _checks, problems = resolve_expected_files(tree, published)

    assert problems == []
    assert [item["path"] for item in resolved["packed_structures"]] == ["packed/input_packed_0_1.pdb"]


def test_packed_view_stays_empty_for_backbone_only_run():
    """A packing-disabled run publishes only backbone structures, so the evidence view has no candidates."""
    with isolated_discovery(str(ROOT / "docker" / "runners")) as manager:
        task = manager.contributions.resolve("tasks", "ligandmpnn")
        tree = expected_file_tree(task, str(ROOT))

    published = _artifacts("seqs/input.fa", "backbones/input_0.pdb")
    resolved, checks, problems = resolve_expected_files(tree, published)

    assert problems == []
    assert resolved["packed_structures"] == []
    assert next(check for check in checks if check["file_id"] == "packed_structures")["status"] == "passed"
