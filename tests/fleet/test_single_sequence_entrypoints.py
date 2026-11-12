# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The sequence-first no-MSA Task is a real, separately discoverable entry.

Discovery, the catalog, the workspace projection, and the preflight contract are
read through the real application against the shipped Runner manifests. Nothing
here executes a Runner or reads a manifest as text; the server projections are
the consumers. AlphaFold 3 has no separate single-sequence Task: its general
JSON Task selects the same no-MSA path with empty inline MSA fields.
"""

from __future__ import annotations

import io

from conftest import _load_fleet_module, _test_client_auth
from frontend_fixtures import validate_payload

AF2 = "alphafold_single_sequence"
DISPLAY_NAME = "AlphaFold2 — Single sequence (no MSA)"


def _client(monkeypatch, tmp_path):
    module = _load_fleet_module(
        monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"}
    )
    return module, module.app.test_client()


def _detail(client, name: str) -> dict:
    response = client.get(f"/compute/api/types/{name}")
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    validate_payload("TaskTypeDetail", payload)
    return payload


def _preflight(module, name: str, fasta: bytes | str, filename: str):
    body = fasta.encode() if isinstance(fasta, str) else fasta
    return module.app.test_client().post(
        f"/compute/api/preflight/{name}",
        headers=_test_client_auth(module),
        data={"files": (io.BytesIO(body), filename), "input_roles": "sequence"},
        content_type="multipart/form-data",
    )


def test_the_entry_is_a_separate_catalog_row(monkeypatch, tmp_path):
    _module, client = _client(monkeypatch, tmp_path)
    catalog = client.get("/compute/api/types").get_json()
    validate_payload("TaskCatalog", catalog)
    by_name = {row["name"]: row for row in catalog["task_types"]}

    assert AF2 in by_name, f"{AF2} is missing from the discoverable catalog"
    assert by_name[AF2]["display_name"] == DISPLAY_NAME
    assert by_name[AF2]["detail_url"] == f"/compute/api/types/{AF2}"

    # The pre-existing MSA-assisted entries are still selectable.
    assert {"alphafold", "alphafold3"} <= set(by_name)
    assert "alphafold3_single_sequence" not in by_name


def test_the_sequence_workspace_binds_the_single_record_role(monkeypatch, tmp_path):
    _module, client = _client(monkeypatch, tmp_path)

    detail = _detail(client, AF2)
    roles = {role["id"]: role for role in detail["inputs"]}
    assert set(roles) == {"sequence"}
    role = roles["sequence"]
    assert role["type"] == "single_protein_sequence"
    assert role["cardinality"] == {"min": 1, "max": 1}
    assert "fasta" in role["formats"]
    assert detail["gpus"] is True
    assert detail["access"]["restricted"] is False

    material = next(step for step in detail["input_workspace"]["steps"] if step["id"] == "material")
    sequence = next(capability for capability in material["capabilities"] if capability["plugin"] == "sequence")
    assert sequence["options"] == {"role": "sequence"}
    assert any(capability["plugin"] == "files" for capability in material["capabilities"])
    assert detail["input_workspace"]["steps"][-1]["capabilities"][-1]["plugin"] == "review"


def test_the_single_sequence_params_do_not_expose_search_controls(monkeypatch, tmp_path):
    _module, client = _client(monkeypatch, tmp_path)

    af2 = client.get(f"/compute/api/task-parameters/{AF2}").get_json()["properties"]
    assert set(af2) == {"model_preset", "models_to_relax", "benchmark"}
    assert set(af2["model_preset"]["enum"]) == {"monomer", "monomer_ptm"}


def _allow_gpu_use(module) -> None:
    """Give the test user the entitlement the GPU-only family requires."""
    _test_client_auth(module)  # ensure the test user exists
    db = module.app.config["user_db"]
    user = db.get_user_by_username("tester")
    db.update_user(user["id"], allow_gpu_use=True)


def test_preflight_rejects_multi_record_and_empty_sequences_before_scheduling(monkeypatch, tmp_path):
    module, _client_obj = _client(monkeypatch, tmp_path)
    _allow_gpu_use(module)
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    multi = _preflight(module, AF2, ">a\nACDEFG\n>b\nHHHHHH\n", "complex.fasta")
    assert multi.status_code == 400, multi.get_data(as_text=True)
    payload = multi.get_json()
    assert payload["valid"] is False
    assert payload["security"]["status"] == "failed"
    assert payload["errors"][0]["code"] == "input_format_invalid"
    assert payload["errors"][0]["role"] == "sequence"
    assert "exactly one FASTA record" in payload["errors"][0]["message"]

    empty = _preflight(module, AF2, ">a\n", "empty.fasta")
    assert empty.status_code == 400, empty.get_data(as_text=True)
    assert empty.get_json()["security"]["status"] == "failed"
    assert "at least one residue" in empty.get_json()["errors"][0]["message"]

    assert module.task_store.list_tasks() == []
    assert queued == []


def test_preflight_rejects_gap_and_stop_symbols_before_scheduling(monkeypatch, tmp_path):
    module, _client_obj = _client(monkeypatch, tmp_path)
    _allow_gpu_use(module)
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *args, **kwargs: queued.append(True))

    for symbol in "-.*":
        response = _preflight(module, AF2, f">one\nACD{symbol}EF\n", "one.fasta")
        assert response.status_code == 400, response.get_data(as_text=True)
        payload = response.get_json()
        assert payload["valid"] is False
        assert payload["security"]["status"] == "failed"
        assert payload["errors"][0]["code"] == "input_format_invalid"
        assert payload["errors"][0]["role"] == "sequence"
        assert "amino-acid letters" in payload["errors"][0]["message"]

    assert module.task_store.list_tasks() == []
    assert queued == []


def test_preflight_accepts_one_single_record_fasta(monkeypatch, tmp_path):
    module, _client_obj = _client(monkeypatch, tmp_path)
    _allow_gpu_use(module)

    response = _preflight(module, AF2, ">one\nACDEFGHIKLMNPQRSTVWY\n", "one.fasta")
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["security"]["status"] == "passed"
    assert payload["contract"]["status"] == "passed"
    assert payload["inputs"] == [{"format": "fasta", "path": "one.fasta", "role": "sequence"}]
