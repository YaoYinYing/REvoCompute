# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The admission boundary on the real submission and execution paths.

These drive the actual HTTP submission route and the actual worker entry point,
so they prove what the boundary does rather than restating what it declares: a
namespace collision fails closed with no durable or queued side effect, the
admitted snapshot carries a receipt bound to the bytes execution consumes, and
a swap of those bytes between admission and execution is detected instead of
being silently executed.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import conftest
from conftest import _load_pssm_module, _test_client_auth
from revocompute.task_types import TaskInputRole

REPO = Path(__file__).resolve().parents[2]
FASTA = (REPO / "tests/data/msa/2KL8.fasta").read_bytes()
RECEPTOR = b"ATOM      1  CA  ALA A   1      11.104   6.134  -6.504  1.00  0.00           C\n"
HOSTILE = b"ATOM      1  CA  ALA A   1\n"  # no END and no full record — still a PDB


def _pdb_only(module, *, minimum: int = 1, maximum: int = 2):
    """Register a synthetic family whose structure role accepts up to two files."""
    base, runner = module.task_runtime._get_task_type("gremlin")
    conftest._inject_task_type(
        module,
        # ``replace`` on the frozen TaskType, exactly as the preflight tests do.
        __import__("dataclasses").replace(
            base,
            name="pdb_only",
            inputs=(TaskInputRole("structure", "Structure", "protein_structure", ("pdb",), minimum, maximum),),
            params=(),
        ),
        runner,
    )


def _recording_dispatch(module):
    """Record dispatches instead of running them; return the recorded list."""
    queued: list[str] = []
    module.run_compute_task.apply_async = lambda *args, **kwargs: (
        queued.append(args[0] if args else (kwargs.get("args") or [None])[0]),
        SimpleNamespace(id="celery-test"),
    )[1]
    return queued


def test_canonical_collision_fails_closed_with_no_durable_or_queue_side_effects(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _pdb_only(module)
    queued = _recording_dispatch(module)
    roots = [Path(module.app.config[key]) for key in ("UPLOAD_FOLDER", "WORKSPACE_FOLDER", "RESULTS_FOLDER")]
    before = {root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots}

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": [
                (io.BytesIO(RECEPTOR), "a b.pdb"),
                (io.BytesIO(RECEPTOR), "a_b.pdb"),
            ],
            "input_roles": ["structure", "structure"],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_namespace_collision"
    assert module.task_store.list_tasks() == []
    assert queued == []
    after = {root: sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file()) for root in roots}
    assert after == before


def test_an_exact_duplicate_path_in_one_role_is_a_collision_too(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _pdb_only(module)
    queued = _recording_dispatch(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": [
                (io.BytesIO(RECEPTOR), "same.pdb"),
                (io.BytesIO(HOSTILE), "same.pdb"),
            ],
            "input_roles": ["structure", "structure"],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_namespace_collision"
    assert module.task_store.list_tasks() == []
    assert queued == []


def test_two_distinct_paths_in_one_role_still_submit(monkeypatch, tmp_path):
    """The collision rule must not reject a legitimate multi-file role."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _pdb_only(module)
    queued = _recording_dispatch(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": [
                (io.BytesIO(RECEPTOR), "first.pdb"),
                (io.BytesIO(HOSTILE), "second.pdb"),
            ],
            "input_roles": ["structure", "structure"],
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    assert len(queued) == 1


def test_the_snapshot_carries_a_receipt_bound_to_the_admitted_bytes(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    queued = _recording_dispatch(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "gremlin",
            "file": (io.BytesIO(FASTA), "2KL8.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    task_id = response.headers["Location"].rsplit("/", 1)[-1]
    task = module.task_store.get_task(task_id)
    snapshot_root = Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs"
    manifest = json.loads((snapshot_root / "task.json").read_text(encoding="utf-8"))

    entry = manifest["inputs"]["sequence"][0]
    receipt = entry["validation"]
    assert receipt["decision"] == "accepted"
    assert receipt["reason_code"] is None
    assert receipt["sha256"] == hashlib.sha256(FASTA).hexdigest()
    assert receipt["size"] == len(FASTA)
    assert receipt["format"] == "fasta"
    assert receipt["logical_type"] == "protein_sequence"
    assert receipt["relative_path"] == "2KL8.fasta"
    assert receipt["role"] == "sequence"
    assert receipt["validator_revision"].startswith("sha256:")

    # The receipt describes the bytes that were actually snapshotted.
    snapshot_bytes = (snapshot_root / "sequence" / "2KL8.fasta").read_bytes()
    assert hashlib.sha256(snapshot_bytes).hexdigest() == receipt["sha256"]


def test_a_swapped_blob_is_refused_before_any_dispatch(monkeypatch, tmp_path):
    """A validated file cannot be substituted between admission and execution."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    queued = _recording_dispatch(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "gremlin",
            "file": (io.BytesIO(FASTA), "2KL8.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    task_id = response.headers["Location"].rsplit("/", 1)[-1]
    task = module.task_store.get_task(task_id)
    snapshot = Path(module.app.config["storage_resolver"].get_input_root(task)) / "inputs" / "sequence" / "2KL8.fasta"
    assert snapshot.is_file()
    # Swap the admitted bytes under the very digest the row trusts, at the path
    # the Runner will actually consume.
    snapshot.chmod(0o640)
    snapshot.write_bytes(b">other\nACDEFG\n")
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() != hashlib.sha256(FASTA).hexdigest()

    executed: list[str] = []
    monkeypatch.setattr(
        module.task_runtime,
        "_run_compute_job",
        lambda *args, **kwargs: executed.append("ran") or None,
    )

    module.run_compute_task(task_id)

    task = module.task_store.get_task(task_id)
    assert task["status"] == "failed"
    assert executed == []


def test_an_untampered_blob_executes_and_records_the_same_receipt(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    queued = _recording_dispatch(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "gremlin",
            "file": (io.BytesIO(FASTA), "2KL8.fasta"),
            "input_roles": "sequence",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    task_id = response.headers["Location"].rsplit("/", 1)[-1]

    executed: list[str] = []

    def _fake_job(task_id, tt, runner, entities, output_dir, stage_callback=None, username="", **kwargs):
        executed.append(task_id)
        return module.task_runtime.JobState.COMPLETED

    monkeypatch.setattr(module.task_runtime, "_run_compute_job", _fake_job)

    module.run_compute_task(task_id)

    assert executed == [task_id]
    task = module.task_store.get_task(task_id)
    assert task["status"] == "finished"


def _legacy_pending_task(
    module,
    tmp_path,
    *,
    content: bytes,
    filename: str = "query.fasta",
    role: str = "sequence",
    logical_type: str = "protein_sequence",
    format_name: str = "fasta",
):
    """Write a Task row shaped like one created before admission receipts existed.

    It carries the same file-entity fields production wrote then — hash, format,
    logical type, snapshot path — and no ``validation_receipt``, so the worker
    has to re-establish the identity of the bytes rather than read it.
    """
    task_id = conftest._insert_pending_task(module, tmp_path / "legacy")
    owner = conftest._task_owner(module, "tester")
    resolver = module.app.config["storage_resolver"]
    identity = {"md5sum": task_id, **owner}
    snapshot_root = Path(resolver.get_input_root(identity)) / "inputs"
    snapshot_path = snapshot_root / role / filename
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    blob = Path(module.task_runtime.CONFIG.upload_folder) / f"{digest}.upload"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(content)
    entity = {
        "name": role,
        "type": "file",
        "role": role,
        "value": filename,
        "verified_value": filename,
        "relative_path": filename,
        "mounted": f"/workspace/inputs/{role}/{filename}",
        "hash": digest,
        "format": format_name,
        "logical_type": logical_type,
        "snapshot_path": str(snapshot_path),
        "snapshot_root": str(snapshot_root),
        "workspace_key": owner["storage_key"],
    }
    module.task_store.update_task(
        task_id,
        input_form=json.dumps(
            {
                "user": "tester",
                "snapshot_root": str(snapshot_root),
                "workspace_key": owner["storage_key"],
                "request_id": "legacy-request",
                "entities": [entity],
            }
        ),
    )
    return task_id


def test_a_legacy_row_without_a_receipt_is_revalidated_not_trusted(monkeypatch, tmp_path):
    """An input with no receipt is re-run through the Core boundary, not assumed safe."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    task_id = _legacy_pending_task(module, tmp_path, content=FASTA)
    executed: list[str] = []
    monkeypatch.setattr(
        module.task_runtime,
        "_run_compute_job",
        lambda *args, **kwargs: executed.append(kwargs["task_id"]) or module.task_runtime.JobState.COMPLETED,
    )

    module.run_compute_task(task_id)

    # The legacy input really is a FASTA for the sequence role, so it passes the
    # canonical boundary and reaches execution.
    assert executed == [task_id]


def test_a_legacy_row_whose_bytes_are_not_the_declared_format_fails_closed(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    # A row that declares a shell script as a FASTA for a sequence role.  The
    # digest matches the bytes on disk, so only re-validation can refuse it —
    # and it must, before anything is executed.
    task_id = _legacy_pending_task(module, tmp_path, content=b"#!/bin/sh\necho pwned\n")
    executed: list[str] = []
    monkeypatch.setattr(
        module.task_runtime,
        "_run_compute_job",
        lambda *args, **kwargs: executed.append(kwargs["task_id"]) or module.task_runtime.JobState.COMPLETED,
    )

    module.run_compute_task(task_id)

    assert executed == []
    assert module.task_store.get_task(task_id)["status"] == "failed"


@pytest.mark.parametrize(
    "raw_path",
    [
        "../escape.pdb",
        "/etc/passwd",
        ".hidden.pdb",
        "a" * 300 + ".pdb",
        "nul\0byte.pdb",
    ],
)
def test_a_hostile_submitted_path_never_reaches_quarantine_or_queue(monkeypatch, tmp_path, raw_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _pdb_only(module)
    queued = _recording_dispatch(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": (io.BytesIO(RECEPTOR), "safe.pdb"),
            "input_roles": "structure",
            "input_paths": raw_path,
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.get_json()["details"][0]["code"] == "input_path_invalid"
    assert module.task_store.list_tasks() == []
    assert queued == []


@pytest.mark.parametrize(
    ("files", "roles", "expected_code", "expected_phase"),
    [
        ([(b"not a structure at all\n", "bad.pdb")], ["structure"], "input_format_invalid", "security"),
        ([(RECEPTOR, "a b.pdb"), (RECEPTOR, "a_b.pdb")], ["structure", "structure"], "input_namespace_collision", "security"),
        ([(RECEPTOR, "x.pdb")], ["nope"], "input_role_unknown", "contract"),
        ([(RECEPTOR, "x.txt")], ["structure"], "input_role_format", "contract"),
    ],
)
def test_the_browser_and_preflight_ingress_classify_a_rejection_identically(
    monkeypatch, tmp_path, files, roles, expected_code, expected_phase
):
    """One canonical boundary: the same bytes get the same code on both ingresses."""
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _pdb_only(module)
    queued = _recording_dispatch(module)

    submission = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": [(io.BytesIO(payload), name) for payload, name in files],
            "input_roles": roles,
        },
        content_type="multipart/form-data",
    )
    preflight = module.app.test_client().post(
        "/compute/api/preflight/pdb_only",
        headers=_test_client_auth(module),
        data={
            "task_type": "pdb_only",
            "files": [(io.BytesIO(payload), name) for payload, name in files],
            "input_roles": roles,
        },
        content_type="multipart/form-data",
    )

    assert submission.status_code == 400
    assert submission.get_json()["details"][0]["code"] == expected_code
    # The preflight errors carry the same code and phase, so a UI that only
    # knows the preflight vocabulary can render either decision.
    preflight_payload = preflight.get_json()
    assert preflight_payload["errors"][0]["code"] == expected_code
    assert preflight_payload[expected_phase] == {"status": "failed"}
    assert module.task_store.list_tasks() == []
    assert queued == []


def test_the_workspace_normalize_post_carries_the_shared_csrf_gate(monkeypatch, tmp_path):
    """The Runner-owned normalizer endpoint is gated like every other POST.

    It executes Runner-supplied normalizer code, so it is classified with its
    siblings rather than left as a cookie-authenticated POST.
    """
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"},
    )
    _pssm_module_ready = module  # keep the module alive for the assertions below
    client = module.app.test_client()
    token_only = _test_client_auth(module)

    # A caller with no credential at all is refused.
    anonymous = client.post(
        "/compute/api/types/gremlin/workspace/normalize",
        json={"capability_id": "sequence_editor", "value": ">x\nACDE\n"},
    )
    assert anonymous.status_code in {401, 403}

    # A Bearer caller reaches the normalizer.
    authorized = client.post(
        "/compute/api/types/gremlin/workspace/normalize",
        json={"capability_id": "sequence_editor", "value": ">x\nACDE\n"},
        headers=token_only,
    )
    assert authorized.status_code in {200, 400}
