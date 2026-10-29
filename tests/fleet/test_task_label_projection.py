# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A concise Task label is presentation only: identity and dispatch do not move.

Two real Task manifests publish a model name instead of a role description. The
label a reader sees changes; the stable Task id the catalog, detail, parameter,
submission and history contracts all address must not, and the runtime family
that dispatches the work must not either.
"""

from __future__ import annotations

from conftest import _load_fleet_module

RENAMED = {
    "bioemu2_equilibrium": ("BioEmu2", "bioemu2"),
    "foundry_rf3_fold": ("RoseTTAFold3", "foundry"),
}


def test_concise_task_labels_keep_ids_and_dispatch_families(monkeypatch, tmp_path):
    module = _load_fleet_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "bioemu2,foundry"},
    )
    client = module.app.test_client()

    catalog = client.get("/compute/api/types")
    assert catalog.status_code == 200
    labels = {item["name"]: item["display_name"] for item in catalog.get_json()["task_types"]}

    for task_id, (label, family) in RENAMED.items():
        assert task_id in labels, f"{task_id} is the stable Task id and must stay addressable"
        assert labels[task_id] == label

        detail = client.get(f"/compute/api/types/{task_id}")
        assert detail.status_code == 200
        projection = detail.get_json()
        assert projection["name"] == task_id
        assert projection["display_name"] == label
        assert projection["runtime_family"] == family
        assert client.get(f"/compute/api/task-parameters/{task_id}").status_code == 200
