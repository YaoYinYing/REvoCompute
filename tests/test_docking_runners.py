# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from revocompute import task_types
from revocompute.task_types import discover_plugins

ROOT = Path(__file__).resolve().parents[1]
RUNNERS = ROOT / "docker/runners"


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
        smoke = yaml.safe_load((RUNNERS / family / "test.yaml").read_text())
        assert smoke["collections"]["smoke"]["cases"][0]["task"] == family


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

    vina_wrapper = (RUNNERS / "autodock_vina/run.sh").read_text()
    assert "mk_prepare_receptor.py --read_pdb" in vina_wrapper
    assert "--log" not in vina_wrapper
    assert '| tee "$out/vina_${n}.log"' in vina_wrapper


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
