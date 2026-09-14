# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import csv
import importlib.util
import io
import json
from pathlib import Path

from conftest import _load_pssm_module, _test_client_auth

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "docker/runners"


def _load_normalizer(family: str):
    path = RUNNERS / family / "normalize_results.py"
    spec = importlib.util.spec_from_file_location(f"{family}_normalize_results", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docking_input_roles_are_exposed_and_enforced_by_api(monkeypatch, tmp_path: Path) -> None:
    families = ("autodock_vina", "autodock_gpu", "gnina", "diffdock")
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": ",".join(families)},
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.app.config["user_db"].update_user(user["id"], allow_gpu_use=True)

    class Queued:
        id = "queued-docking"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: Queued())
    receptor = b"ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n"
    ligand = (ROOT / "tests/data/docking/ethanol.sdf").read_bytes()

    for family in families:
        detail = client.get(f"/compute/api/types/{family}", headers=auth_header)
        assert detail.status_code == 200
        roles = {role["id"]: role for role in detail.get_json()["inputs"]}
        ligand_role = "ligands" if family in {"autodock_vina", "autodock_gpu"} else "ligand"
        expected_maximum = 32 if family == "autodock_vina" else (64 if family == "autodock_gpu" else 1)
        assert roles["receptor"]["cardinality"] == {"min": 1, "max": 1}
        assert roles[ligand_role]["cardinality"] == {"min": 1, "max": expected_maximum}

        rejected = client.post(
            "/compute/api/post",
            data={
                "task_type": family,
                "file": (io.BytesIO(receptor), "receptor.pdb"),
                "input_roles": "receptor",
            },
            headers=auth_header,
            content_type="multipart/form-data",
        )
        assert rejected.status_code == 400
        assert rejected.get_json()["details"][0]["role"] == ligand_role

        accepted = client.post(
            "/compute/api/post",
            data={
                "task_type": family,
                "files": [(io.BytesIO(ligand), "ligand.sdf"), (io.BytesIO(receptor), "receptor.pdb")],
                "input_roles": [ligand_role, "receptor"],
            },
            headers=auth_header,
            content_type="multipart/form-data",
        )
        assert accepted.status_code == 302, accepted.get_data(as_text=True)

        if expected_maximum == 1:
            rejected_extra = client.post(
                "/compute/api/post",
                data={
                    "task_type": family,
                    "files": [
                        (io.BytesIO(receptor), "receptor.pdb"),
                        (io.BytesIO(ligand), "ligand.sdf"),
                        (io.BytesIO(ligand), "extra.sdf"),
                    ],
                    "input_roles": ["receptor", ligand_role, ligand_role],
                },
                headers=auth_header,
                content_type="multipart/form-data",
            )
            assert rejected_extra.status_code == 400
            assert rejected_extra.get_json()["details"][0]["role"] == ligand_role


def test_runner_owned_normalizers_preserve_native_scoring_semantics(tmp_path: Path) -> None:
    vina_dir = tmp_path / "vina"
    vina_dir.mkdir()
    (vina_dir / "vina_1.log").write_text(
        "mode |   affinity | dist from best mode\n"
        "     | (kcal/mol) | rmsd l.b.| rmsd u.b.\n"
        "-----+------------+----------+----------\n"
        "   1       -6.4          0          0\n"
        "   2       -5.8      1.234      2.345\n"
    )
    (vina_dir / "vina_1.pdbqt").write_text("MODEL 1\nENDMDL\nMODEL 2\nENDMDL\n")
    _load_normalizer("autodock_vina").normalize(vina_dir, ["ligand.sdf"])
    vina_rows = list(csv.DictReader((vina_dir / "scores.csv").open()))
    assert vina_rows[1]["affinity_kcal_mol"] == "-5.8"
    assert vina_rows[1]["pose_file"] == "vina_1.pdbqt#MODEL=2"

    adgpu_dir = tmp_path / "autodock_gpu"
    adgpu_dir.mkdir()
    (adgpu_dir / "autodock_gpu_1.dlg").write_text(
        "DOCKED: USER    Run = 1\n"
        "DOCKED: USER    Estimated Free Energy of Binding    =  -6.42 kcal/mol  [=(1)+(2)+(3)-(4)]\n"
        "DOCKED: USER    (1) Final Intermolecular Energy     =  -6.10 kcal/mol\n"
        "DOCKED: USER    (2) Final Total Internal Energy     =  -0.32 kcal/mol\n"
        "    1      1      1       -6.42      0.00      0.00           RANKING\n"
    )
    _load_normalizer("autodock_gpu").normalize(adgpu_dir, ["ligand.pdbqt"])
    adgpu_row = next(csv.DictReader((adgpu_dir / "scores.csv").open()))
    assert adgpu_row["binding_energy_kcal_mol"] == "-6.42"
    assert adgpu_row["cluster_rank"] == "1"

    gnina_dir = tmp_path / "gnina"
    gnina_dir.mkdir()
    (gnina_dir / "gnina.sdf").write_text(
        "pose\n  gnina\n\nM  END\n"
        "> <minimizedAffinity>\n-7.1\n\n> <CNNscore>\n0.82\n\n> <CNNaffinity>\n6.4\n\n$$$$\n"
    )
    _load_normalizer("gnina").normalize(gnina_dir)
    gnina_row = next(csv.DictReader((gnina_dir / "scores.csv").open()))
    assert gnina_row["CNNscore"] == "0.82"
    assert gnina_row["pose_file"] == "gnina.sdf#record=1"

    diffdock_dir = tmp_path / "diffdock"
    (diffdock_dir / "diffdock").mkdir(parents=True)
    (diffdock_dir / "diffdock/rank1_confidence-1.25.sdf").write_text("pose\n")
    (diffdock_dir / "diffdock/rank2_confidence0.40.sdf").write_text("pose\n")
    _load_normalizer("diffdock").normalize(diffdock_dir)
    diffdock_rows = list(csv.DictReader((diffdock_dir / "scores.csv").open()))
    assert [row["confidence"] for row in diffdock_rows] == ["-1.25", "0.40"]

    for output_dir in (vina_dir, adgpu_dir, gnina_dir, diffdock_dir):
        summary = json.loads((output_dir / "summary.json").read_text())
        assert summary["pose_count"] >= 1
        assert summary["scores_file"] == "scores.csv"
