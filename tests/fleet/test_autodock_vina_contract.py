# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Public result-manifest contract for the AutoDock Vina storyboard."""

from __future__ import annotations

import json

from test_scientific_result_protocols import _finalize


def test_autodock_vina_publishes_the_ranked_pose_contract(monkeypatch, tmp_path) -> None:
    """The Task-scoped tree resolves every identity the Vina storyboard binds to.

    The run writes one PDBQT per ligand plus the normalizer's scores/summary and
    its own run record; the receptor snapshot is optional because a result whose
    debug tree was purged still has to present its ranked poses.
    """
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "autodock_vina",
        "autodock_vina",
        {
            "vina_1.pdbqt": "MODEL 1\nREMARK VINA RESULT: -1.331 0.000 0.000\nENDMDL\n",
            "vina_1.log": "mode |   affinity | dist from best mode\n",
            "scores.csv": (
                "ligand,pose_rank,affinity_kcal_mol,rmsd_lb_angstrom,rmsd_ub_angstrom,pose_file\n"
                "ethanol.sdf,1,-1.331,0,0,vina_1.pdbqt#MODEL=1\n"
            ),
            "summary.json": json.dumps(
                {
                    "ligand_count": 1,
                    "pose_count": 1,
                    "ranking_metric": "affinity_kcal_mol",
                    "ranking_order": "ascending",
                    "runner": "autodock_vina",
                    "scores_file": "scores.csv",
                }
            ),
            "vina-run.json": json.dumps({"task_type": "autodock_vina", "runtime_network": False}),
            "prepared/receptor.pdbqt": "ATOM      1  CA  ALA A   1       0.0   0.0   0.0  1.00  0.00           C\n",
            "prepared/ligand_1.pdbqt": "ATOM      1  C   UNL     1       0.0   0.0   0.0  1.00  0.00           C\n",
            "debug/inputs/receptor/1abc_A_B.pdb": "ATOM      1  CA  ALA A   1       0.0   0.0   0.0  1.00  0.00           C\n",
            "debug/inputs/ligands/ethanol.sdf": "CCO\n",
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["storyboard"] == {
        "identifier": "autodock-vina-result",
        "entrypoint": "index.js",
        "requires": ["scores", "summary", "poses"],
        "optional": ["run_record", "pose_logs", "prepared", "receptor", "ligands", "citations"],
    }
    files = manifest["result"]["files"]
    assert {key: len(value) for key, value in files.items()} == {
        "poses": 1,
        "scores": 1,
        "summary": 1,
        "run_record": 1,
        "pose_logs": 1,
        "prepared": 2,
        "receptor": 1,
        "ligands": 1,
        "citations": 1,
    }
    # The PDBQT pose is published download-only: the shared viewer does not parse
    # AutoDock atom types, and the declaration must not claim otherwise.
    pose = files["poses"][0]
    assert pose["path"] == "vina_1.pdbqt"
    assert pose["logical_type"] is None


def test_autodock_vina_keeps_the_pose_contract_when_the_input_snapshot_is_absent(monkeypatch, tmp_path) -> None:
    """The receptor snapshot is provenance, never a condition of presenting poses."""
    manifest = _finalize(
        monkeypatch,
        tmp_path,
        "autodock_vina",
        "autodock_vina",
        {
            "vina_1.pdbqt": "MODEL 1\nENDMDL\n",
            "vina_1.log": "mode |   affinity\n",
            "scores.csv": "ligand,pose_rank,affinity_kcal_mol\nethanol.sdf,1,-1.331\n",
            "summary.json": json.dumps({"pose_count": 1}),
            "vina-run.json": json.dumps({"task_type": "autodock_vina"}),
            "prepared/receptor.pdbqt": "ATOM\n",
            "prepared/ligand_1.pdbqt": "ATOM\n",
        },
    )

    assert manifest["output_check"]["state"] == "passed", manifest["output_check"]
    assert manifest["result"]["files"]["receptor"] == []
    assert len(manifest["result"]["files"]["poses"]) == 1
