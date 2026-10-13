# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The canonical parameter area of a workspace that claims only some fields.

A workspace can own a *subset* of the canonical schema: a ``regions`` capability
names the fields it draws, and the rest of the task's parameters belong to no one
unless the projection supplies the canonical area for them. This file drives that
shape through the real application - the real workspace projection and the real
preflight boundary - for a synthetic Task registered in the loaded registry.
Nothing here reads a manifest as text or executes a Runner.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace

import conftest
from conftest import _load_pssm_module, _test_client_auth
from revocompute.task_types import InputCapability, InputStep, TaskInputRole

TASK = "partial_ownership"
#: The one canonical field a declared capability owns; the rest of the Task's
#: schema is left for the projection to expose.
CLAIMED = "region_start"
#: A canonical field no declared capability names.
LEFT_OUT = "num_samples"
#: The capability id the projection publishes for the leftover fields.
CANONICAL = "task_parameters"

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        CLAIMED: {
            "type": "integer",
            "title": "Region start",
            "default": 1,
            "minimum": 1,
            "maximum": 50,
            "description": "First residue of the region this run refines.",
        },
        LEFT_OUT: {
            "type": "integer",
            "title": "Sample count",
            "default": 8,
            "minimum": 1,
            "maximum": 64,
            "description": "Number of independent samples to generate.",
        },
    },
}

#: A workspace whose intent step declares a capability that owns one canonical
#: field by name, with no generic parameter area anywhere in the Task.
WORKSPACE = (
    InputStep(
        id="material",
        title="Material",
        description="",
        capabilities=(
            InputCapability(plugin="files", id="source_files", title="Input"),
            InputCapability(plugin="sequence", id="sequence_editor", title="Sequence", options={"role": "sequence"}),
        ),
    ),
    InputStep(
        id="intent",
        title="Regions",
        description="",
        capabilities=(
            InputCapability(
                plugin="regions",
                id="placement_regions",
                title="Placement context",
                options={"fields": [CLAIMED]},
            ),
        ),
    ),
    InputStep(
        id="review",
        title="Review",
        description="",
        capabilities=(
            InputCapability(plugin="review", id="submission_review", title="Review", options={"show_paths": True}),
        ),
    ),
)


def _partial_ownership_module(monkeypatch, tmp_path):
    """Load the isolated application and register the synthetic Task in it.

    ``revocompute.routes`` is imported before the registration: its first import
    installs the discovered runner-family registry snapshot, which would
    otherwise replace the snapshot holding the synthetic Task the projection is
    read through.
    """
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    import revocompute.routes  # noqa: F401  (installs the runner registry snapshot)
    base, runner = module.task_runtime._get_task_type("cpu_runner")
    conftest._inject_task_type(
        module,
        replace(
            base,
            name=TASK,
            inputs=(TaskInputRole("sequence", "Sequence", "protein_sequence", ("fasta",), 1, 1),),
            params=(),
            schema=SCHEMA,
            input_workspace=WORKSPACE,
        ),
        runner,
    )
    return module


def _detail(module) -> dict:
    """The TaskTypeDetail the real projection serves for the synthetic Task."""
    response = module.app.test_client().get(f"/compute/api/types/{TASK}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _projected(module, detail: dict | None = None) -> list[dict]:
    """Every capability the workspace projection publishes for the Task."""
    steps = (detail or _detail(module))["input_workspace"]["steps"]
    return [capability for step in steps for capability in step["capabilities"]]


def _preflight(module, capabilities: dict, params: dict):
    """Post the browser's own workspace and flat parameter fields to preflight."""
    data: dict = {
        "workspace": json.dumps({"version": 2, "capabilities": capabilities}),
        "files": (io.BytesIO(b">sample\nACDEFG\n"), "sequence.fasta"),
        "input_roles": "sequence",
        "task_type": TASK,
    }
    data.update({f"params[{name}]": str(value) for name, value in params.items()})
    return module.app.test_client().post(
        f"/compute/api/preflight/{TASK}",
        headers=_test_client_auth(module),
        data=data,
        content_type="multipart/form-data",
    )


def test_a_partial_field_owner_still_projects_the_unclaimed_parameters(monkeypatch, tmp_path):
    """The projection exposes exactly the fields nothing in the workspace renders.

    The declared ``regions`` capability renders the one field it names; the other
    canonical field would be dropped silently even though the server still applies
    its default, so the projection supplies the canonical parameter area for what
    is left. The declared capability keeps its own field and the area claims none,
    so no parameter renders twice.
    """
    module = _partial_ownership_module(monkeypatch, tmp_path)
    detail = _detail(module)
    capabilities = _projected(module, detail)
    owners = [capability for capability in capabilities if capability["plugin"] == "parameters"]
    assert len(owners) == 1, capabilities
    # The generic area carries no field list, so it renders every field no
    # capability names - here exactly the leftover one, and never the claimed one.
    assert owners[0]["id"] == CANONICAL
    assert owners[0]["options"] == {}
    assert [capability["id"] for capability in capabilities] == [
        "source_files",
        "sequence_editor",
        "placement_regions",
        CANONICAL,
        "submission_review",
    ]

    # The declared owner keeps its own field and gains nothing.
    regions = next(capability for capability in capabilities if capability["plugin"] == "regions")
    assert regions["options"]["fields"] == [CLAIMED]

    # The area lands in the terminal step with the `review` anchor still last, so
    # the workspace grammar the loader enforces still holds.
    steps = detail["input_workspace"]["steps"]
    assert steps[-1]["capabilities"][-1]["plugin"] == "review"
    assert steps[-1]["capabilities"][-2] is owners[0]

    # The leftover field is the one the task-owned schema declares and the
    # parameters endpoint serves, so the area has something real to render.
    schema = module.app.test_client().get(f"/compute/api/task-parameters/{TASK}").get_json()
    assert set(schema["properties"]) == {CLAIMED, LEFT_OUT}


def test_both_the_owned_and_the_unclaimed_parameters_pass_the_submission_boundary(monkeypatch, tmp_path):
    """What the browser collects is what the real preflight resolves.

    The client echoes the workspace it holds: the declared capability under its own
    id and the leftover parameters under the capability id the projection
    published. Both parameter values reach the boundary and are the ones it
    resolves into the normalized contract the Task is created from.
    """
    module = _partial_ownership_module(monkeypatch, tmp_path)
    response = _preflight(
        module,
        {"placement_regions": {CLAIMED: "7"}, CANONICAL: {LEFT_OUT: "9"}},
        {CLAIMED: 7, LEFT_OUT: 9},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["valid"] is True, payload
    assert payload["normalized_params"] == {CLAIMED: 7, LEFT_OUT: 9}
    assert payload["contract"] == {"status": "passed"}
    assert payload["errors"] == []
    assert module.task_store.list_tasks() == []


def test_the_boundary_admits_only_the_capability_ids_the_projection_published(monkeypatch, tmp_path):
    """The one id the area adds is the only one the accepted set gains.

    A workspace document naming a capability the projection never published is
    refused, so exposing the canonical area widened the boundary by exactly that
    capability rather than by accepting arbitrary workspace state.
    """
    module = _partial_ownership_module(monkeypatch, tmp_path)
    response = _preflight(module, {"not_published": {LEFT_OUT: "9"}}, {LEFT_OUT: 9})

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["valid"] is False
    assert payload["contract"] == {"status": "failed"}
    assert payload["errors"][0]["code"] == "contract_invalid"
    assert payload["errors"][0]["message"] == "Workspace contains an unknown capability"
    assert module.task_store.list_tasks() == []
