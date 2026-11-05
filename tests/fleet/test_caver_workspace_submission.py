# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from conftest import _load_fleet_module, _test_client_auth


def test_caver_manual_point_submission_accepts_empty_selection(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[2]
    caver_task = next((root / "docker" / "runners").glob("*/tasks/caver/task.yaml"))
    family = yaml.safe_load((caver_task.parents[2] / "plugin.yaml").read_text())["id"]
    module = _load_fleet_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": family},
    )
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: SimpleNamespace(id="queued-caver"))
    pdb = Path(__file__).resolve().parents[2] / "tests" / "data" / "3fap_hf3_A_short.pdb"
    workspace = {"version": 2, "capabilities": {"structure_summary": {"selected_residues": []}}}
    data = {
        "task_type": "caver",
        "workspace": json.dumps(workspace),
        "files": (io.BytesIO(pdb.read_bytes()), "reference.pdb"),
        "input_roles": "structure",
        "params[start_point_mode]": "point",
        "params[start_x]": "1.0",
        "params[start_y]": "2.0",
        "params[start_z]": "3.0",
    }

    response = module.app.test_client().post(
        "/compute/api/post", headers=_test_client_auth(module), data=data, content_type="multipart/form-data"
    )

    assert response.status_code == 302, response.get_data(as_text=True)
    assert len(module.task_store.list_tasks()) == 1
