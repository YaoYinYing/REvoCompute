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

import pytest
from conftest import _load_pssm_module, _test_client_auth
from revocompute.artifact_evidence import write_artifact_evidence, write_staged_identity
from revocompute.live_tests import LIVE_TEST_RECEIPT_VERSION, atomic_write_json
from revocompute.runner_admin_view import fleet_view
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_live_test import candidate_receipt_valid, load_validation_identity
from revocompute.runner_readiness import bundle_digest, load_instance_families, resolve_runner_readiness
from revocompute.runner_registry import RegistryError, _build_provenance
from revocompute.serialization import sha256_file
from revocompute_ctl.promotion import promote_sifs


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


def _record_artifact(state, family, artifact: Path, *, receipt: str = "valid") -> None:
    """Leave the evidence a live-test run leaves for this artifact.

    ``receipt="valid"`` is a passing smoke receipt, ``"invalid"`` is a receipt
    for the current identity whose cases did not pass, and ``None`` leaves build
    evidence only.
    """
    provenance = _build_provenance(state, family)
    digest = sha256_file(artifact)
    write_artifact_evidence(family, digest, "build", provenance)
    if artifact.name.endswith(".next"):
        # The build boundary records the staged path's own identity; readiness
        # reads that sidecar instead of guessing among content-addressed records.
        write_staged_identity(family, digest, str(provenance["build_provenance_digest"]))
    if receipt is None:
        return
    identity = load_validation_identity(family, state=state)
    passed = receipt == "valid"
    write_artifact_evidence(
        family,
        digest,
        "receipt",
        {
            "receipt_contract_version": LIVE_TEST_RECEIPT_VERSION,
            "runner_family": family.name,
            "collection": "smoke",
            "passed": passed,
            "sif_sha256": digest,
            "build_provenance_digest": provenance["build_provenance_digest"],
            "runtime_bundle_sha256": bundle_digest(state, family),
            "test_definition_digest": identity.plan.digest,
            "configuration_digest": identity.configuration_digest,
            "execution_uid": 1234,
            "execution_gid": 5678,
            "scheduler_user": "revodesign",
            "cases": [{"case_id": case.id, "passed": passed} for case in identity.plan.select("smoke")],
            "ended_at": "2026-10-25T12:00:00+00:00",
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


def _assert_post_is_refused(module, readiness, *, status: str, reason: str, next_action: str, queued) -> dict:
    """Publish the controller's verdict and prove POST creates no side effect."""
    _publish(module, readiness)
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
    assert body["status"] == status
    assert body["reason"] == reason
    assert body["next_action"] == next_action
    assert module.task_store.list_tasks() == tasks_before
    assert module.task_store.list_live_reservations() == reservations_before
    assert _durable_uploads(module) == uploads_before
    assert queued == []
    return body


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
    _record_artifact(state, family, active)

    # The installed artifact is genuinely ready before a candidate exists.
    baseline = resolve_runner_readiness(state, family)
    assert baseline.ready is True, baseline

    # The build=True live-test flow stages the candidate without touching the
    # installed path, then records the candidate's current-provenance evidence.
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"validated-candidate-v2")
    _record_artifact(state, family, candidate)
    assert active.read_bytes() == b"installed-image-v1"

    staged = resolve_runner_readiness(state, family)
    assert staged.ready is False, "a staged candidate must not make the installed image READY"
    assert staged.status.value == "BUILD_STALE"
    assert staged.reason_code == "CANDIDATE_AWAITING_PROMOTION"
    assert staged.next_action == "promote"
    assert "promote" in staged.message and "rebuild" not in staged.message.lower()
    # A promotion verdict implies the host activation accepts the candidate;
    # the evaluator's evidence check is at least as strong as that predicate.
    assert candidate_receipt_valid(state, family) is True
    assert (staged.reason_code == "CANDIDATE_AWAITING_PROMOTION") is candidate_receipt_valid(
        state, family
    )
    # The row carries the candidate's own live-test evidence rather than
    # dataclass defaults: the Fleet must not claim "No receipt" for a candidate
    # that promote-sifs will accept, and smoke coverage must not read 0/0.
    assert staged.sif_exists is True
    assert staged.build_provenance_current is True
    assert staged.runtime_bundle_sha256 == bundle_digest(state, family)
    assert staged.receipt_exists is True
    assert staged.receipt_valid is True
    assert staged.receipt_tested_at
    assert staged.receipt_sif_sha256
    # The installed artifact's identity is not established by a candidate's
    # evidence, so no digest is presented as the active one.
    assert staged.sif_sha256 is None
    assert staged.required_smoke_cases == ("minimal-synthetic",)
    assert staged.passed_smoke_cases == ("minimal-synthetic",)

    # The admin Fleet forwards those facts rather than dataclass defaults: the
    # candidate receipt is visible, the active identity is not claimed.
    fleet_row = next(row for row in fleet_view(state) if row["runner_family"] == "cpu_runner")
    assert fleet_row["readiness"]["active_image"] == {
        "state": "UNKNOWN",
        "sha256": None,
        "reason_code": "STAGED_CANDIDATE_PENDING",
    }
    fleet_evidence = fleet_row["readiness"]["evidence"]
    assert fleet_evidence["sif_sha256"] is None
    assert fleet_evidence["build_provenance_current"] is True
    assert fleet_evidence["runtime_bundle_sha256"] == bundle_digest(state, family)
    assert fleet_evidence["receipt_exists"] is True
    assert fleet_evidence["receipt_valid"] is True
    assert fleet_evidence["receipt_tested_at"]
    assert fleet_evidence["required_smoke_cases"] == ["minimal-synthetic"]
    assert fleet_evidence["passed_smoke_cases"] == ["minimal-synthetic"]

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
    promote_sifs(state, [family])
    promoted = resolve_runner_readiness(state, family)
    assert promoted.ready is True, promoted
    assert promoted.reason_code == "READY"


def test_first_build_candidate_without_an_active_sif_awaits_promotion(monkeypatch, tmp_path):
    """First enablement stages a validated candidate with no active SIF at all."""
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
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"first-candidate-v1")
    _record_artifact(state, family, candidate)
    assert not active.exists()

    staged = resolve_runner_readiness(state, family)
    assert staged.ready is False
    assert staged.status.value == "BUILD_STALE"
    assert staged.reason_code == "CANDIDATE_AWAITING_PROMOTION"
    assert staged.next_action == "promote"
    assert staged.sif_exists is False
    assert staged.receipt_valid is True
    assert staged.receipt_sif_sha256 == sha256_file(candidate)
    assert staged.sif_sha256 is None
    assert staged.passed_smoke_cases == ("minimal-synthetic",)
    assert candidate_receipt_valid(state, family) is True
    assert (staged.reason_code == "CANDIDATE_AWAITING_PROMOTION") is candidate_receipt_valid(state, family)

    # The Fleet forwards the first-build state as two lanes of one candidate:
    # no installed artifact is claimed, while the candidate's own receipt is
    # reported as validated.
    fleet_row = next(row for row in fleet_view(state) if row["runner_family"] == "cpu_runner")
    assert fleet_row["readiness"]["active_image"] == {
        "state": "MISSING",
        "sha256": None,
        "reason_code": "SIF_MISSING",
    }
    fleet_evidence = fleet_row["readiness"]["evidence"]
    assert fleet_evidence["sif_exists"] is False
    assert fleet_evidence["receipt_exists"] is True
    assert fleet_evidence["receipt_valid"] is True

    _publish(module, staged)
    response = module.app.test_client().post(
        "/compute/api/post",
        headers=_test_client_auth(module),
        data=_payload(),
        content_type="multipart/form-data",
    )
    assert response.status_code == 503, response.get_data(as_text=True)
    assert response.get_json()["reason"] == "CANDIDATE_AWAITING_PROMOTION"
    assert module.task_store.list_tasks() == []
    assert module.task_store.list_live_reservations() == []
    assert _durable_uploads(module) == []
    assert queued == []

    # promote-sifs installs the candidate even with no previous active file.
    promote_sifs(state, [family])
    assert active.is_file()
    assert not candidate.exists()
    assert resolve_runner_readiness(state, family).ready is True


def test_unvalidated_staged_candidate_is_told_to_validate_not_promote(monkeypatch, tmp_path):
    """An old active image plus a candidate that no passing receipt validates."""
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
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"unvalidated-candidate-v2")
    _record_artifact(state, family, candidate, receipt=None)

    staged = resolve_runner_readiness(state, family)
    assert staged.ready is False
    assert staged.status.value == "NOT_VALIDATED"
    assert staged.reason_code == "RECEIPT_MISSING"
    assert staged.next_action == "live-test"
    # The message names the staged candidate; it must not imply a fact about
    # the installed artifact the candidate verdict never established.
    assert "staged Runner candidate" in staged.message
    assert "active" not in staged.message.lower()
    assert staged.sif_exists is True
    assert staged.sif_sha256 is None
    assert staged.build_provenance_current is True
    assert staged.receipt_exists is False
    assert staged.receipt_valid is False
    assert staged.required_smoke_cases == ("minimal-synthetic",)
    assert staged.passed_smoke_cases == ()
    # No promote verdict is offered that the host activation would refuse.
    assert candidate_receipt_valid(state, family) is False
    with pytest.raises(RegistryError, match="no valid live-test receipt"):
        promote_sifs(state, [family])
    assert active.read_bytes() == b"installed-image-v1"
    assert candidate.is_file()

    fleet_row = next(row for row in fleet_view(state) if row["runner_family"] == "cpu_runner")
    assert fleet_row["readiness"]["active_image"] == {
        "state": "UNKNOWN",
        "sha256": None,
        "reason_code": "STAGED_CANDIDATE_PENDING",
    }
    fleet_evidence = fleet_row["readiness"]["evidence"]
    assert fleet_evidence["sif_sha256"] is None
    assert fleet_evidence["receipt_exists"] is False
    assert fleet_evidence["receipt_valid"] is False
    assert fleet_evidence["required_smoke_cases"] == ["minimal-synthetic"]
    assert fleet_evidence["passed_smoke_cases"] == []

    # No Task row, upload, reservation, or scheduler call is created while the
    # only actionable step is to validate the candidate.
    _assert_post_is_refused(
        module, staged, status="NOT_VALIDATED", reason="RECEIPT_MISSING", next_action="live-test", queued=queued
    )

    # A receipt for the candidate's identity that did not pass is stale
    # evidence, not a missing receipt, and still cannot be promoted.
    _record_artifact(state, family, candidate, receipt="invalid")
    stale = resolve_runner_readiness(state, family)
    assert stale.ready is False
    assert stale.status.value == "VALIDATION_STALE"
    assert stale.reason_code == "RECEIPT_STALE"
    assert stale.next_action == "live-test"
    assert "staged Runner candidate" in stale.message
    assert stale.sif_sha256 is None
    assert stale.receipt_exists is True
    assert stale.receipt_valid is False
    assert candidate_receipt_valid(state, family) is False
    with pytest.raises(RegistryError, match="no valid live-test receipt"):
        promote_sifs(state, [family])
    assert active.read_bytes() == b"installed-image-v1"


def test_first_build_unvalidated_candidate_is_told_to_validate(monkeypatch, tmp_path):
    """First enablement stages a candidate with no active SIF and no receipt."""
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
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"first-unvalidated-candidate-v1")
    _record_artifact(state, family, candidate, receipt=None)
    assert not active.exists()

    staged = resolve_runner_readiness(state, family)
    assert staged.ready is False
    assert staged.status.value == "NOT_VALIDATED"
    assert staged.reason_code == "RECEIPT_MISSING"
    assert staged.next_action == "live-test"
    assert "staged Runner candidate" in staged.message
    assert staged.sif_exists is False
    assert staged.sif_sha256 is None
    assert staged.receipt_exists is False
    assert staged.receipt_valid is False
    assert staged.receipt_sif_sha256 is None
    assert candidate_receipt_valid(state, family) is False

    fleet_row = next(row for row in fleet_view(state) if row["runner_family"] == "cpu_runner")
    assert fleet_row["readiness"]["active_image"] == {
        "state": "MISSING",
        "sha256": None,
        "reason_code": "SIF_MISSING",
    }
    assert fleet_row["readiness"]["evidence"]["receipt_exists"] is False

    _assert_post_is_refused(
        module, staged, status="NOT_VALIDATED", reason="RECEIPT_MISSING", next_action="live-test", queued=queued
    )
    assert not active.exists()
    assert candidate.is_file()

    with pytest.raises(RegistryError, match="no valid live-test receipt"):
        promote_sifs(state, [family])
    assert not active.exists()
    assert candidate.is_file()


def test_validated_active_and_unvalidated_candidate_never_promote(monkeypatch, tmp_path):
    """A's passing receipt must not authorize the staged candidate B."""
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
    active.write_bytes(b"validated-active-A")
    _record_artifact(state, family, active)
    assert resolve_runner_readiness(state, family).ready is True

    # B is a different artifact built from the same inputs, never live-tested.
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"unvalidated-candidate-B")
    provenance = _build_provenance(state, family)
    write_artifact_evidence(family, sha256_file(candidate), "build", provenance)
    write_staged_identity(family, sha256_file(candidate), str(provenance["build_provenance_digest"]))

    # A's receipt keeps validating A; it says nothing about B's bytes.
    assert candidate_receipt_valid(state, family, sif_sha256=sha256_file(candidate)) is False

    staged = resolve_runner_readiness(state, family)
    assert staged.ready is False
    assert staged.status.value == "NOT_VALIDATED"
    assert staged.next_action == "live-test"
    assert "staged Runner candidate" in staged.message
    assert "promote" not in staged.message.lower()

    with pytest.raises(RegistryError, match="no valid live-test receipt"):
        promote_sifs(state, [family])
    assert active.read_bytes() == b"validated-active-A"
    assert candidate.read_bytes() == b"unvalidated-candidate-B"

    _assert_post_is_refused(
        module, staged, status="NOT_VALIDATED", reason="RECEIPT_MISSING", next_action="live-test", queued=queued
    )
    assert active.read_bytes() == b"validated-active-A"
    assert candidate.read_bytes() == b"unvalidated-candidate-B"


def test_both_artifacts_receipted_promotes_the_staged_candidate(monkeypatch, tmp_path):
    """Same-provenance siblings both have receipts; B's own receipt is found."""
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

    state, family = _deployment(module)
    active = Path(family.slurm_image)
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"validated-active-A")
    _record_artifact(state, family, active)
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"validated-candidate-B")
    _record_artifact(state, family, candidate)

    # B's receipt wins over A's because the lookup is bound to B's bytes.
    assert candidate_receipt_valid(state, family, sif_sha256=sha256_file(candidate)) is True
    promote_sifs(state, [family])

    assert active.read_bytes() == b"validated-candidate-B"
    assert not candidate.exists()
    assert not Path(f"{family.slurm_image}.next.build.json").exists()
    assert resolve_runner_readiness(state, family).ready is True


def test_a_candidate_changed_after_validation_is_not_promoted(monkeypatch, tmp_path):
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

    state, family = _deployment(module)
    active = Path(family.slurm_image)
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"validated-active-A")
    _record_artifact(state, family, active)
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"validated-candidate-B")
    _record_artifact(state, family, candidate)

    # The file no longer hashes to the digest its receipt and staged record name.
    candidate.write_bytes(b"candidate-B-replaced-after-validation")

    # Activation hashes the candidate and refuses: the receipt names B's
    # original bytes, not the replacement.
    assert candidate_receipt_valid(state, family, sif_sha256=sha256_file(candidate)) is False
    with pytest.raises(RegistryError, match="no valid live-test receipt"):
        promote_sifs(state, [family])
    assert active.read_bytes() == b"validated-active-A"
    assert candidate.read_bytes() == b"candidate-B-replaced-after-validation"


def test_an_unrecorded_candidate_identity_names_a_recovery_that_clears_it(monkeypatch, tmp_path):
    """A candidate validated before the staging record existed is repairable."""
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

    state, family = _deployment(module)
    active = Path(family.slurm_image)
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"validated-active-A")
    _record_artifact(state, family, active)
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"validated-candidate-B")
    _record_artifact(state, family, candidate)
    Path(f"{family.slurm_image}.next.build.json").unlink()

    unrecorded = resolve_runner_readiness(state, family)
    assert unrecorded.ready is False
    assert unrecorded.status.value == "NOT_VALIDATED"
    assert unrecorded.reason_code == "RECEIPT_MISSING"
    assert unrecorded.next_action == "live-test"
    assert "live test" in unrecorded.message
    assert "promote" not in unrecorded.message.lower()
    # The live test records the identity of the bytes it validates, which is the
    # recovery the verdict named.
    _record_artifact(state, family, candidate)
    recovered = resolve_runner_readiness(state, family)
    assert recovered.reason_code == "CANDIDATE_AWAITING_PROMOTION"
    promote_sifs(state, [family])
    assert active.read_bytes() == b"validated-candidate-B"


def test_an_unresolvable_bundle_binding_is_a_verdict_not_an_exception(monkeypatch, tmp_path):
    """The staged path must return CONFIGURATION_INVALID, never raise, for this."""
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
    state, family = _deployment(module)
    active = Path(family.slurm_image)
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"validated-active-A")
    _record_artifact(state, family, active)
    candidate = Path(f"{family.slurm_image}.next")
    candidate.write_bytes(b"candidate-B")
    _record_artifact(state, family, candidate)

    # A candidate identity is recorded, but the Runtime Bundle binding that the
    # receipt must match cannot be resolved.
    monkeypatch.setattr(
        "revocompute.runner_readiness.bundle_digest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bundle index unreadable")),
    )

    verdict = resolve_runner_readiness(state, family)
    assert verdict.ready is False
    assert verdict.status.value == "NOT_CONFIGURED"
    assert verdict.reason_code == "CONFIGURATION_INVALID"
    assert verdict.next_action == "doctor"
    assert verdict.build_provenance_current is False
    assert verdict.sif_exists is True
    # The Fleet projection renders that verdict rather than failing.
    row = next(item for item in fleet_view(state) if item["runner_family"] == "cpu_runner")
    assert row["readiness"]["reason_code"] == "CONFIGURATION_INVALID"
