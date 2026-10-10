# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Generic Server behavior must operate without the installed Runner fleet."""

from __future__ import annotations

import io
import os
from pathlib import Path
from types import SimpleNamespace

from conftest import _load_pssm_module, _test_client_auth


def test_catalog_and_submission_never_access_production_runner_root(monkeypatch, tmp_path):
    production = Path(__file__).resolve().parents[2] / "docker" / "runners"
    real_scandir = os.scandir
    real_open = Path.open

    def reject_production(path):
        try:
            candidate = Path(path).absolute()
        except TypeError:
            return
        if candidate == production or production in candidate.parents:
            raise AssertionError(f"Server accessed production Runner root: {candidate}")

    def guarded_scandir(path):
        reject_production(path)
        return real_scandir(path)

    def guarded_open(path, *args, **kwargs):
        reject_production(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", guarded_scandir)
    monkeypatch.setattr(Path, "open", guarded_open)
    module = _load_pssm_module(monkeypatch, tmp_path, {"RUNNER_UID": "1000", "RUNNER_GID": "1000"})
    client = module.app.test_client()
    names = {row["name"] for row in client.get("/compute/api/types").get_json()["task_types"]}
    assert {"cpu_runner", "restricted_runner", "multistage_runner", "typed_runner"} <= names
    detail = client.get("/compute/api/types/restricted_runner").get_json()
    assert detail["access"]["restricted"] is True
    assert [stage["requires_gpu"] for stage in detail["workflow"]] == [False, True]
    headers = _test_client_auth(module)
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: SimpleNamespace(id="synthetic"))
    response = client.post(
        "/compute/api/post",
        headers=headers,
        data={
            "task_type": "cpu_runner",
            "files": (io.BytesIO(b">synthetic\nACDE\n"), "input.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.get_json()
    task = module.task_store.get_task(response.headers["Location"].rsplit("/", 1)[-1])
    assert task["task_type"] == "cpu_runner"
