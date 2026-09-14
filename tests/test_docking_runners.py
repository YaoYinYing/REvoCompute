# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import csv
import importlib.util
import io
import json
import subprocess
from pathlib import Path

import yaml
from conftest import _load_pssm_module, _test_client_auth

from revocompute import task_types
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker/runners"


def _load_normalizer(family: str):
    path = RUNNERS / family / "normalize_results.py"
    spec = importlib.util.spec_from_file_location(f"{family}_normalize_results", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _discover(family: str):
    saved = (dict(task_types._registry), dict(task_types._runtime_registry), dict(task_types._category_registry))
    try:
        task_types._registry.clear()
        task_types._runtime_registry.clear()
        task_types._category_registry.clear()
        discover_plugins(str(RUNNERS), {family})
        yield task_types.get(family)
    finally:
        task_types._registry.clear()
        task_types._registry.update(saved[0])
        task_types._runtime_registry.clear()
        task_types._runtime_registry.update(saved[1])
        task_types._category_registry.clear()
        task_types._category_registry.update(saved[2])


def test_docking_families_are_distinct_self_contained_plugins() -> None:
    expected_gpu = {"autodock_vina": False, "autodock_gpu": True, "gnina": True, "diffdock": True}
    for family, needs_gpu in expected_gpu.items():
        task, runner = next(_discover(family))
        assert task.category == "docking"
        assert task.runtime.name == family
        assert task.gpus is needs_gpu
        assert task.schema["additionalProperties"] is False
        assert task.citation_dois
        assert (RUNNERS / family / "upstream.json").is_file()
        build_inputs = yaml.safe_load((RUNNERS / family / "plugin.yaml").read_text())["runtime"]["build_inputs"]
        assert f"{family}/normalize_results.py" in build_inputs
        result_contract = yaml.safe_dump(yaml.safe_load((RUNNERS / family / f"tasks/{family}/task.yaml").read_text()))
        assert "scores.csv" in result_contract
        assert "summary.json" in result_contract
        smoke = yaml.safe_load((RUNNERS / family / "test.yaml").read_text())
        assert smoke["collections"]["smoke"]["cases"][0]["task"] == family


def test_docking_input_cardinality_is_exposed_and_enforced_by_api(monkeypatch, tmp_path: Path) -> None:
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

    class _Queued:
        id = "queued-docking"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: _Queued())
    receptor = b"ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nEND\n"
    ligand = (ROOT / "tests/data/docking/ethanol.sdf").read_bytes()

    for family in families:
        detail = client.get(f"/compute/api/types/{family}", headers=auth_header)
        assert detail.status_code == 200
        file_input = detail.get_json()["file_input"]
        assert file_input["multiple"] is True
        expected_max = 2 if family in {"gnina", "diffdock"} else (33 if family == "autodock_vina" else 65)
        assert file_input["max_files"] == expected_max

        rejected = client.post(
            "/compute/api/post",
            data={"task_type": family, "file": (io.BytesIO(receptor), "receptor.pdb")},
            headers=auth_header,
            content_type="multipart/form-data",
        )
        assert rejected.status_code == 400

        accepted = client.post(
            "/compute/api/post",
            data={
                "task_type": family,
                "files": [(io.BytesIO(receptor), "receptor.pdb"), (io.BytesIO(ligand), "ligand.sdf")],
            },
            headers=auth_header,
            content_type="multipart/form-data",
        )
        assert accepted.status_code == 302, accepted.get_data(as_text=True)

        if family in {"gnina", "diffdock"}:
            rejected_extra = client.post(
                "/compute/api/post",
                data={
                    "task_type": family,
                    "files": [
                        (io.BytesIO(receptor), "receptor.pdb"),
                        (io.BytesIO(ligand), "ligand.sdf"),
                        (io.BytesIO(ligand), "extra.sdf"),
                    ],
                },
                headers=auth_header,
                content_type="multipart/form-data",
            )
            assert rejected_extra.status_code == 400


def test_diffdock_contract_is_explicitly_structure_only_and_offline() -> None:
    task, runner = next(_discover("diffdock"))
    serialized = yaml.safe_dump(
        yaml.safe_load((RUNNERS / "diffdock/tasks/diffdock/task.yaml").read_text())
    ).lower()
    assert task.primary_input_extensions == (".pdb",)
    assert set(task.input_extensions) == {".pdb", ".sdf", ".mol2"}
    assert "sequence" not in task.schema["properties"]
    assert "fasta" not in task.input_extensions
    assert "never accepts protein sequences" in serialized
    assert all(mount.mode == "ro" for mount in runner.mounts)
    assert {mount.host_path for mount in runner.mounts} == {
        "/mnt/db/weights/revocompute/diffdock",
        "/mnt/db/weights/esm",
    }
    wrapper = (RUNNERS / "diffdock/run.sh").read_text()
    assert "protein_sequence" not in wrapper
    assert "sequences are not accepted" in wrapper
    assert "(cd /opt/diffdock && python3 -m inference" in wrapper
    assert "DIFFDOCK_MODEL_ROOT" in wrapper
    assert "sha256sum --strict --check --status" in wrapper
    assert "runtime_network':False" in wrapper
    source_patch = (RUNNERS / "diffdock/structure-only.patch").read_text().splitlines()
    installed_lines = [line for line in source_patch if not line.startswith("-") or line.startswith("---")]
    installed_patch = "\n".join(installed_lines).lower()
    definition = (RUNNERS / "diffdock/diffdock.def").read_text()
    assert "import e3nn, esm, rdkit" in definition
    assert 'hasattr(esm.pretrained, "load_model_and_alphabet")' in definition
    assert "-import esm" not in "\n".join(source_patch)
    assert "esmfold" not in installed_patch
    assert "openfold" not in installed_patch
    assert "protein_sequence" not in installed_patch


def test_runtime_definitions_pin_matching_accelerator_stacks_and_use_uv() -> None:
    vina_definition = (RUNNERS / "autodock_vina/autodock_vina.def").read_text()
    gpu_definition = (RUNNERS / "autodock_gpu/autodock_gpu.def").read_text()
    gnina_definition = (RUNNERS / "gnina/gnina.def").read_text()
    diffdock_definition = (RUNNERS / "diffdock/diffdock.def").read_text()

    assert "uv==0.8.22" in vina_definition
    assert "uv==0.8.22" in gpu_definition
    assert "nvidia/cuda:12.2.0-devel-ubuntu22.04" in gpu_definition
    assert "nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04" in gnina_definition
    assert "gnina.1.3.2.cuda12.8" in gnina_definition
    assert "nvidia/cuda:11.7.1-runtime-ubuntu22.04" in diffdock_definition
    assert "uv==0.8.22" in diffdock_definition
    assert "torch==1.13.1+cu117" in diffdock_definition
    assert "git init /opt/openfold" not in diffdock_definition
    assert "uv pip install" in diffdock_definition
    assert "prody==2.4.1" in diffdock_definition
    assert "fair-esm[esmfold]" not in diffdock_definition.lower()
    assert "structure-only.patch" in diffdock_definition
    assert "(cd /opt/diffdock && /opt/venv/bin/python -m inference --help" in diffdock_definition
    assert "! /opt/venv/bin/python -m inference --help |" not in diffdock_definition


def test_autodock_gpu_owns_autogrid_and_batch_ligand_pipeline() -> None:
    task, _ = next(_discover("autodock_gpu"))
    wrapper = (RUNNERS / "autodock_gpu/run.sh").read_text()
    assert task.allow_multiple_inputs is True
    assert "mk_prepare_receptor.py --read_pdb" in wrapper
    assert "autogrid4" in wrapper
    assert "receptor.maps.fld" in wrapper
    assert 'for ligand in "${inputs[@]:1}"' in wrapper
    assert "autodock_gpu --ffile" in wrapper
    assert "AutoGrid affinity map preparation" in (
        RUNNERS / "autodock_gpu/tasks/autodock_gpu/task.yaml"
    ).read_text()


def test_vina_and_gnina_expose_their_distinct_scoring_controls() -> None:
    vina, _ = next(_discover("autodock_vina"))
    gnina, _ = next(_discover("gnina"))
    assert {"center_x", "center_y", "center_z", "size_x", "size_y", "size_z", "seed"} <= set(vina.schema["properties"])
    assert vina.params[-1].ui_control["kind"] == "seed"
    cnn = gnina.schema["properties"]["cnn_scoring"]
    assert cnn["enum"] == ["none", "rescore", "refinement", "all"]
    assert {"center_x", "center_y", "center_z", "size_x", "size_y", "size_z"} <= set(gnina.schema["properties"])
    assert "autobox_add" not in gnina.schema["properties"]
    for coordinate in ("center_x", "center_y", "center_z"):
        assert gnina.schema["properties"][coordinate]["minimum"] == -10000.0
        assert gnina.schema["properties"][coordinate]["maximum"] == 10000.0

    vina_wrapper = (RUNNERS / "autodock_vina/run.sh").read_text()
    assert "mk_prepare_receptor.py --read_pdb" in vina_wrapper
    assert "--log" not in vina_wrapper
    assert '| tee "$out/vina_${n}.log"' in vina_wrapper
    gnina_wrapper = (RUNNERS / "gnina/run.sh").read_text()
    assert "--autobox_ligand" not in gnina_wrapper
    for argument in ("center_x", "center_y", "center_z", "size_x", "size_y", "size_z"):
        assert f'--{argument} "$(_parse_param {argument})"' in gnina_wrapper


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
    assert vina_rows[1] == {
        "ligand": "ligand.sdf",
        "pose_rank": "2",
        "affinity_kcal_mol": "-5.8",
        "rmsd_lb_angstrom": "1.234",
        "rmsd_ub_angstrom": "2.345",
        "pose_file": "vina_1.pdbqt#MODEL=2",
    }

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
    adgpu_rows = list(csv.DictReader((adgpu_dir / "scores.csv").open()))
    assert adgpu_rows[0]["binding_energy_kcal_mol"] == "-6.42"
    assert adgpu_rows[0]["intermolecular_energy_kcal_mol"] == "-6.10"
    assert adgpu_rows[0]["internal_energy_kcal_mol"] == "-0.32"
    assert adgpu_rows[0]["cluster_rank"] == "1"

    gnina_dir = tmp_path / "gnina"
    gnina_dir.mkdir()
    (gnina_dir / "gnina.sdf").write_text(
        "pose\n  gnina\n\nM  END\n"
        "> <minimizedAffinity>\n-7.1\n\n> <CNNscore>\n0.82\n\n> <CNNaffinity>\n6.4\n\n$$$$\n"
    )
    _load_normalizer("gnina").normalize(gnina_dir)
    gnina_row = next(csv.DictReader((gnina_dir / "scores.csv").open()))
    assert gnina_row == {
        "pose_rank": "1",
        "minimizedAffinity": "-7.1",
        "CNNscore": "0.82",
        "CNNaffinity": "6.4",
        "pose_file": "gnina.sdf#record=1",
    }

    diffdock_dir = tmp_path / "diffdock"
    (diffdock_dir / "diffdock").mkdir(parents=True)
    (diffdock_dir / "diffdock/rank1_confidence-1.25.sdf").write_text("pose\n")
    (diffdock_dir / "diffdock/rank2_confidence0.40.sdf").write_text("pose\n")
    _load_normalizer("diffdock").normalize(diffdock_dir)
    diffdock_rows = list(csv.DictReader((diffdock_dir / "scores.csv").open()))
    assert diffdock_rows == [
        {"pose_rank": "1", "confidence": "-1.25", "pose_file": "diffdock/rank1_confidence-1.25.sdf"},
        {"pose_rank": "2", "confidence": "0.40", "pose_file": "diffdock/rank2_confidence0.40.sdf"},
    ]
    for output_dir in (vina_dir, adgpu_dir, gnina_dir, diffdock_dir):
        summary = json.loads((output_dir / "summary.json").read_text())
        assert summary["pose_count"] >= 1
        assert summary["scores_file"] == "scores.csv"


def test_diffdock_wrapper_rejects_sequence_input_before_model_execution(tmp_path: Path) -> None:
    fasta = tmp_path / "protein.fasta"
    fasta.write_text(">p\nAAAA\n")
    ligand = ROOT / "tests/data/docking/ethanol.sdf"
    manifest = tmp_path / "task.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [{"path": str(fasta)}, {"path": str(ligand)}],
                "params": {"samples": 2, "steps": 5},
            }
        )
    )
    completed = subprocess.run(
        ["bash", str(RUNNERS / "diffdock/run.sh"), "-i", str(manifest), "-o", str(tmp_path / "out")],
        env={
            "TASK_MANIFEST": str(manifest),
            "TASK_CONTEXT_SRC": str(RUNNERS / "common/task_context.sh"),
            "TASK_TYPE": "diffdock",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "sequences are not accepted" in completed.stderr
    assert not (tmp_path / "out/task_finished").exists()


def test_upstream_release_tags_resolve_to_recorded_immutable_commits() -> None:
    expected = {
        "autodock_vina": "8eb40404f4f45608acb3b01427587ac049f27c1f",
        "autodock_gpu": "e63e6f6280ebfad18caa3e8f48afdc269e79e063",
        "gnina": "f23dd2b781b59d29047ddacb4410ece68d085a3c",
        "diffdock": "9a22cbcbc7612c7565c80e8399d9be298971f156",
    }
    for family, commit in expected.items():
        intake = json.loads((RUNNERS / family / "upstream.json").read_text())
        assert intake["commit"] == commit
