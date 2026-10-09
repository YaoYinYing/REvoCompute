# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations
import hashlib
import inspect
import io
import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path
import pytest
import requests
import yaml
import conftest
from conftest import _anchor_result_publication, _extract_md5, _load_fleet_module, _relocate_task_artifacts, _task_owner
from jsonschema import Draft202012Validator
from revocompute.resource_ledger import DataLifecycleState
from revocompute.task_types import TaskInputRole
from werkzeug.utils import secure_filename
ROOT = Path(__file__).resolve().parents[2]
SERVER_PACKAGE = ROOT / "revocompute"
from test_tasks import _test_client_auth, _upsert_task_for_user


def test_task_type_api_exposes_runtime_family_and_gpu_contract(monkeypatch, tmp_path):
    module = _load_fleet_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "mpnn",
        },
    )
    client = module.app.test_client()

    response = client.get("/compute/api/types")
    assert response.status_code == 200
    catalog = response.get_json()
    assert all(set(category) == {"name", "label"} for category in catalog["categories"])
    laser = next(item for item in catalog["task_types"] if item["name"] == "lasermpnn")
    assert set(laser) == {
        "name",
        "display_name",
        "category",
        "summary",
        "access",
        "detail_url",
        "parameters_url",
    }
    assert laser["detail_url"] == "/compute/api/types/lasermpnn"
    assert laser["parameters_url"] == "/compute/api/task-parameters/lasermpnn"
    assert not ({"params", "parameter_schema", "runtime_family", "workflow", "citations"} & set(laser))

    form_response = client.get("/compute/api/types/lasermpnn")
    assert form_response.status_code == 200
    form = form_response.get_json()
    assert form["runtime_family"] == "mpnn"
    assert form["gpus"] is False
    # Resource usage is not part of the user-facing submission review.
    assert "resources" not in form
    assert form["definition_version"] == 4
    assert form["input_workspace"]["version"] == 3
    assert form["input_workspace"]["steps"][0]["capabilities"][0]["plugin"] == "files"
    assert form["input_workspace"]["steps"][-1]["capabilities"][-1]["plugin"] == "review"
    assert form["max_request_bytes"] == 16 * 1024 * 1024
    assert form["inputs"][0]["id"] == "structure"
    assert form["parameters_url"] == "/compute/api/task-parameters/lasermpnn"
    assert "parameter_schema" not in form
    assert "params" not in form

    proteinmpnn = client.get("/compute/api/task-parameters/proteinmpnn").get_json()
    assert proteinmpnn["properties"]["seed"]["x-ui-control"] == {"kind": "seed", "random": {"minimum": 1}}
    Draft202012Validator(proteinmpnn).validate({"seed": 0})

def test_pythia_citations_are_published_in_forms_and_results(monkeypatch, tmp_path):
    module = _load_fleet_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "pythia_ddg",
        },
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    expected = [
        {
            "num": 1,
            "doi": "10.1016/j.xinn.2024.100750",
            "title": "Structure-based self-supervised learning enables ultrafast protein stability prediction upon mutation",
            "url": "https://doi.org/10.1016/j.xinn.2024.100750",
        }
    ]

    form_response = client.get("/compute/api/types/pythia_ddg")
    assert form_response.status_code == 200
    assert form_response.get_json()["citations"] == expected

    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "pythia_citations"
    result_dir.mkdir()
    input_path = result_dir / "input.pdb"
    input_path.write_text("END\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename=input_path.name,
        file_path=input_path,
        result_dir=result_dir,
        username="tester",
        task_type="pythia_ddg",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(md5sum), execution_state="completed", finished_at=1_700_000_000
    )

    result_response = client.get(f"/compute/api/results/{md5sum}", headers=auth_header)
    assert result_response.status_code == 200
    result = result_response.get_json()
    assert result["run"]["citations"] == expected
    citation_artifact = next(artifact for artifact in result["artifacts"] if artifact["path"] == "citations.bib")
    assert citation_artifact["role"] == "provenance"
    assert "10.1016/j.xinn.2024.100750" in (result_dir / "citations.bib").read_text(encoding="utf-8")

def test_multiple_citations_export_in_num_order_from_source_bibtex(monkeypatch, tmp_path):
    module = _load_fleet_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "gremlin_lh",
        },
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    detail = client.get("/compute/api/types/gremlin_lh_fit").get_json()
    assert [citation["num"] for citation in detail["citations"]] == [1, 2]
    assert detail["citations"][0]["url"] == "https://doi.org/10.1103/PRXLife.2.023005"
    assert "Disentanglement" in detail["citations"][0]["title"]

    md5sum = uuid.uuid4().hex
    result_dir = tmp_path / "gremlin_citations"
    result_dir.mkdir()
    input_path = result_dir / "input.a3m"
    input_path.write_text(">a\nACDE\n>b\nACDF\n", encoding="utf-8")
    _upsert_task_for_user(
        module,
        md5sum,
        filename=input_path.name,
        file_path=input_path,
        result_dir=result_dir,
        username="tester",
        task_type="gremlin_lh_fit",
    )
    module.task_runtime._finalize_results_manifest(
        module.task_store.get_task(md5sum), execution_state="completed", finished_at=1_700_000_000
    )

    exported = (result_dir / "citations.bib").read_text(encoding="utf-8")
    assert exported.count("@article") == 2
    assert exported.index("Wang_2024") < exported.index("Kamisetty_2013")
    assert "10.1103/prxlife.2.023005" in exported
    assert "10.1073/pnas.1314045110" in exported
    assert exported.endswith("}\n")

    run = client.get(f"/compute/api/results/{md5sum}", headers=auth_header).get_json()["run"]
    assert [citation["num"] for citation in run["citations"]] == [1, 2]
    assert run["citations"][1]["url"] == "https://doi.org/10.1073/pnas.1314045110"

def test_api_projects_presentation_safe_title_from_marked_up_bibtex(monkeypatch, tmp_path):
    module = _load_fleet_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "autodock_gpu",
        },
    )
    client = module.app.test_client()

    response = client.get("/compute/api/types/autodock_gpu")

    assert response.status_code == 200
    citation = response.get_json()["citations"][0]
    assert citation["title"] == "Accelerating AutoDock4 with GPUs and Gradient-Based Local Search"
    assert "<" not in citation["title"] and ">" not in citation["title"]
    assert citation["url"] == "https://doi.org/10.1021/acs.jctc.0c01006"


def test_rfdiffusion_workspace_normalization_and_structure_free_submission(monkeypatch, tmp_path):
    module = _load_fleet_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "ENABLED_TASKRUNNERS": "placer-rfdiffusion",
        },
    )
    client = module.app.test_client()
    auth_header = _test_client_auth(module)
    user = module.app.config["user_db"].get_user_by_username("tester")
    module.app.config["user_db"].update_user(user["id"], allow_gpu_use=True)
    state = {
        "mode": "unconditional",
        "segments": [{"kind": "generated", "min_length": 40, "max_length": 40}],
        "hotspots": [],
    }
    normalized = client.post(
        "/compute/api/types/rfdiffusion/workspace/normalize",
        json={"capability_id": "design_regions", "value": state},
        headers=auth_header,
    )

    class _Queued:
        id = "queued-rfdiffusion"

    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: _Queued())
    submitted = client.post(
        "/compute/api/post",
        data={
            "task_type": "rfdiffusion",
            "workspace": json.dumps({"version": 2, "capabilities": {"design_regions": state}}),
        },
        headers=auth_header,
    )

    assert normalized.status_code == 200
    assert normalized.get_json()["params"]["contig"] == "40-40"
    assert submitted.status_code == 302, submitted.get_json()
    task = module.task_store.get_task(submitted.headers["Location"].rsplit("/", 1)[-1])
    manifest = json.loads(
        (Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs" / "task.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["inputs"] == {"assets": [], "structure": []}
    assert manifest["params"]["design_mode"] == "unconditional"
    assert manifest["params"]["contig"] == "40-40"
