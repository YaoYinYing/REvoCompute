# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A staged candidate must never make the installed image READY for submission.

The live-test flow builds ``<sif>.next`` and records build evidence under the
current provenance, while execution still loads the installed path until a
promotion moves the candidate into place.  Readiness is an admission verdict
about the artifact that will actually execute, so the evaluator must refuse
while a candidate is awaiting promotion and clear once the candidate is active.
"""

from __future__ import annotations

import io
from pathlib import Path

from conftest import _load_pssm_module, _test_client_auth
from revocompute.artifact_evidence import write_artifact_evidence
from revocompute.live_tests import LIVE_TEST_RECEIPT_VERSION, atomic_write_json
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_live_test import load_validation_identity
from revocompute.runner_readiness import bundle_digest, load_instance_families, resolve_runner_readiness
from revocompute.runner_registry import _build_provenance
from revocompute.serialization import sha256_file


class _AvailableInfrastructure:
    """Infrastructure evidence that would admit the Task if readiness allowed it."""

    def report(self) -> dict:
        return {
            "status": "READY",
            "stale": False,
            "summary": {"scheduler": {"capacity": "AVAILABLE"}, "gpu": {"capacity": "AVAILABLE"}},
        }

    def admission_block(self, **_kwargs):
        return None


def _deployment(module) -> tuple[ServerHostPaths, object]:
    state = ServerHostPaths(
        server=module.CONFIG.server_dir,
        config=str(Path(module.CONFIG.server_dir) / "config"),
        root=str(Path(__file__).resolve().parents[2]),
        settings={
            "RUNNER_SOURCE_ROOT": module.CONFIG.runners_dir,
            "RUNTIME_BUNDLE_DIR": module.CONFIG.runtime_bundle_root,
            "MANAGE_DB_PATH": str(module.CONFIG.manage_db_path),
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "RUNNER_USERNAME": "revodesign",
            "RUNNER_GROUP": "revodesign",
            "REVODESIGN_APPTAINER_VERSION": "apptainer version 1.4.0",
        },
    )
    family = next(item for item in load_instance_families(state) if item.name == "cpu_runner")
    return state, family


def _record_validated_artifact(state, family, artifact: Path) -> None:
    """Leave the build evidence and receipt a passing live test leaves for this artifact."""
    provenance = _build_provenance(state, family)
    digest = sha256_file(artifact)
    write_artifact_evidence(family, digest, "build", provenance)
    identity = load_validation_identity(family, state=state)
    write_artifact_evidence(
        family,
        digest,
        "receipt",
        {
            "receipt_contract_version": LIVE_TEST_RECEIPT_VERSION,
            "runner_family": family.name,
            "collection": "smoke",
            "passed": True,
            "sif_sha256": digest,
            "build_provenance_digest": provenance["build_provenance_digest"],
            "runtime_bundle_sha256": bundle_digest(state, family),
            "test_definition_digest": identity.plan.digest,
            "configuration_digest": identity.configuration_digest,
            "execution_uid": 1234,
            "execution_gid": 5678,
            "scheduler_user": "revodesign",
            "cases": [{"case_id": case.id, "passed": True} for case in identity.plan.select("smoke")],
        },
    )


def _publish(module, row) -> Path:
    path = Path(module.CONFIG.server_dir) / "readiness" / "cpu_runner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, row.as_dict())
    return path


def _payload() -> dict:
    return {
        "task_type": "cpu_runner",
        "files": (io.BytesIO(b">sequence\nACDEFGHIK\n"), "sequence.fasta"),
        "input_roles": "sequence",
    }


def _durable_uploads(module) -> list[Path]:
    root = Path(module.app.config["UPLOAD_FOLDER"])
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_staged_candidate_is_not_ready_and_cannot_create_submission_side_effects(monkeypatch, tmp_path):
    module = _load_pssm_module(
        monkeypatch,
        tmp_path,
        extra_env={
            "RUNNER_UID": "1234",
            "RUNNER_GID": "5678",
            "RUNNER_USERNAME": "revodesign",
            "RUNNER_GROUP": "revodesign",
            "REVODESIGN_APPTAINER_VERSION": "apptainer version 1.4.0",
        },
    )
    module.app.config["manage_db"].resource_set("slurm_enabled", "true")
    module.app.config["infrastructure_readiness"] = _AvailableInfrastructure()
    queued: list[bool] = []
    monkeypatch.setattr(module.run_compute_task, "apply_async", lambda *_args, **_kwargs: queued.append(True))

    state, family = _deployment(module)
    active = Path(family.slurm_image)
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"installed-image-v1")
    _record_validated_artifact(state, family, active)

    # The installed artifact is genuinely ready before a candidate exists.
    baseline = resolve_runner_readiness(state, family)
    assert baseline.ready is True, baseline

    # The build=True live-test flow stages the candidate without touching the
    # installed path, then records the candidate's current-provenance evidence.
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"validated-candidate-v2")
    _record_validated_artifact(state, family, candidate)
    assert active.read_bytes() == b"installed-image-v1"

    staged = resolve_runner_readiness(state, family)
    assert staged.ready is False, "a staged candidate must not make the installed image READY"
    assert staged.status.value == "BUILD_STALE"
    assert staged.reason_code == "CANDIDATE_AWAITING_PROMOTION"
    assert staged.next_action == "promote"
    assert "promote" in staged.message and "rebuild" not in staged.message.lower()

    # Publish exactly what the controller publishes, then submit: no Task ID,
    # upload, reservation, or scheduler call may be created for the installed
    # image while the candidate is only staged.
    _publish(module, staged)
    module.task_store.upsert_task(
        "existing-running-task",
        filename="existing.fasta",
        file_path="",
        uploaded_at=1.0,
        started_at=2.0,
        status="running",
        is_binary=0,
        source_ip="127.0.0.1",
        user_agent="pytest",
        username="existing",
        task_type="cpu_runner",
        submitted_by_user_id=0,
        storage_key="existing",
    )
    tasks_before = module.task_store.list_tasks()
    reservations_before = module.task_store.list_live_reservations()
    uploads_before = _durable_uploads(module)

    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data=_payload(),
        content_type="multipart/form-data",
    )

    assert response.status_code == 503, response.get_data(as_text=True)
    body = response.get_json()
    assert body["runner"] == "cpu_runner"
    assert body["status"] == "BUILD_STALE"
    assert body["reason"] == "CANDIDATE_AWAITING_PROMOTION"
    assert body["next_action"] == "promote"
    assert module.task_store.list_tasks() == tasks_before
    assert module.task_store.list_live_reservations() == reservations_before
    assert _durable_uploads(module) == uploads_before
    assert queued == []

    # Promotion is the deployment-host step that makes the candidate the
    # executing artifact; the same evidence then validates a real submission.
    active.write_bytes(candidate.read_bytes())
    candidate.unlink()
    promoted = resolve_runner_readiness(state, family)
    assert promoted.ready is True, promoted
    assert promoted.reason_code == "READY"
