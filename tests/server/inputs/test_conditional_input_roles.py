# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Server-enforced conditional input cardinality.

A JSON Schema parameter rule cannot see uploaded files, so the owning Task
declares ``presence`` on the role and Core applies it before any upload is
quarantined. This exercises the complete all-modes × input-set matrix through
the real submission and preflight boundaries.
"""

from __future__ import annotations

import io
from dataclasses import replace

import pytest
import conftest
from conftest import _inject_task_type, _load_pssm_module, _test_client_auth
from revocompute.io_contracts import FileRolePresence
from revocompute.task_types import TaskInputRole

SYSTEM = b"entities: []\n"
CIF = b"data_test\n_atom_site.id\n1\n"


@pytest.fixture
def module(monkeypatch, tmp_path):
    loaded = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678", "ENABLED_TASKRUNNERS": "typed_runner"},
    )
    user = loaded.app.config["user_db"].create_user(
        "conditional-inputs", "{{EMAIL_ozgjq2jx}}", "password",
        registration_status="approved", user_status="active",
    )
    loaded.app.config["user_db"].verify_email(user["id"])
    loaded.app.config["user_db"].update_user(user["id"], allow_gpu_use=True)

    class Queued:
        id = "conditional-inputs"

    monkeypatch.setattr(loaded.run_compute_task, "apply_async", lambda *args, **kwargs: Queued())

    base, runner = loaded.task_runtime._get_task_type("typed_runner")
    _inject_task_type(
        loaded,
        replace(
            base,
            name="conditional_inputs",
            inputs=(
                TaskInputRole("system", "System", "supporting_data", ("yaml",), 1, 1),
                TaskInputRole(
                    "starting_structure", "Starting structure", "protein_structure", ("cif",), 0, 1,
                    presence=FileRolePresence(
                        "mode", ("propagate",), ("equilibrium", "structure_prediction")
                    ),
                ),
            ),
            params=(),
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["equilibrium", "structure_prediction", "propagate"],
                        "default": "equilibrium",
                    }
                },
            },
        ),
        runner,
    )
    return loaded


def _submit(module, mode, files):
    return module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module, "conditional-inputs", "password"),
        data={
            "task_type": "conditional_inputs",
            "params[mode]": mode,
            "files": [(io.BytesIO(payload), name) for name, payload in files],
            "input_roles": [name.rsplit(".", 1)[0] for name, _payload in files],
        },
        content_type="multipart/form-data",
    )


def _system(cif):
    return [("system.yaml", SYSTEM), ("starting_structure.cif", CIF)] if cif else [("system.yaml", SYSTEM)]


@pytest.mark.parametrize(
    ("mode", "files", "status", "code"),
    [
        # equilibrium and structure_prediction require the system and refuse a CIF.
        ("equilibrium", _system(False), 302, None),
        ("equilibrium", _system(True), 400, "input_role_presence"),
        ("equilibrium", [("starting_structure.cif", CIF)], 400, "input_role_cardinality"),
        ("equilibrium", [], 400, "input_role_cardinality"),
        ("structure_prediction", _system(False), 302, None),
        ("structure_prediction", _system(True), 400, "input_role_presence"),
        ("structure_prediction", [("starting_structure.cif", CIF)], 400, "input_role_cardinality"),
        ("structure_prediction", [], 400, "input_role_cardinality"),
        # propagate requires both.
        ("propagate", _system(True), 302, None),
        ("propagate", _system(False), 400, "input_role_presence"),
        ("propagate", [("starting_structure.cif", CIF)], 400, "input_role_cardinality"),
        ("propagate", [], 400, "input_role_cardinality"),
    ],
)
def test_every_mode_and_input_set_is_enforced_at_the_submission_boundary(module, mode, files, status, code):
    response = _submit(module, mode, files)

    assert response.status_code == status, response.get_json()
    if code is not None:
        assert response.get_json()["details"][0]["code"] == code


def test_preflight_applies_the_same_presence_rule_before_allocation(module):
    response = module.app.test_client().post(
        "/compute/api/preflight/conditional_inputs",
        headers=_test_client_auth(module, "conditional-inputs", "password"),
        data={
            "task_type": "conditional_inputs",
            "params[mode]": "propagate",
            "files": (io.BytesIO(SYSTEM), "system.yaml"),
            "input_roles": "system",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["valid"] is False
    assert payload["contract"] == {"status": "failed"}
    assert payload["errors"][0]["code"] == "input_role_presence"
    assert payload["errors"][0]["role"] == "starting_structure"
