# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import _load_pssm_module, _test_client_auth
from revocompute.task_types import TaskInputRole


@pytest.mark.parametrize("endpoint", ["/compute/api/post", "/compute/api/preflight/pdb_only"])
def test_security_rejection_has_no_durable_or_queue_side_effects(monkeypatch, tmp_path, endpoint):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    base, runner = module.task_runtime._get_task_type("gremlin")
    module.task_runtime._register_tt(
        replace(
            base,
            name="pdb_only",
            inputs=(TaskInputRole("structure", "Structure", "protein_structure", ("pdb",), 1, 2),),
            params=(),
        ),
        runner,
    )
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))
    roots = [Path(module.app.config[key]) for key in ("UPLOAD_FOLDER", "WORKSPACE_FOLDER", "RESULTS_FOLDER")]
    before = {root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots}

    response = module.app.test_client().post(
        endpoint,
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": [
                (io.BytesIO(b"ATOM      1  CA  ALA A   1\n"), "valid.pdb"),
                (io.BytesIO(b"this is not a pdb\n"), "hostile.pdb"),
            ],
            "input_roles": ["structure", "structure"],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert {
        root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots
    } == before


def test_read_only_preflight_reuses_validation_without_side_effects(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))
    roots = [Path(module.app.config[key]) for key in ("UPLOAD_FOLDER", "WORKSPACE_FOLDER", "RESULTS_FOLDER")]
    before = {root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots}

    response = module.app.test_client().post(
        "/compute/api/preflight/gremlin",
        headers=_test_client_auth(module),
        data={
            "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload.pop("normalized_params")["iter"] == 100
    assert payload == {
        "admission": {"allowed": True},
        "contract": {"status": "passed"},
        "errors": [],
        "inputs": [{"format": "fasta", "path": "sequence.fasta", "role": "sequence"}],
        "security": {"status": "passed"},
        "valid": True,
        "warnings": [],
    }
    assert module.task_store.list_tasks() == []
    assert queued == []
    assert {
        root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots
    } == before
