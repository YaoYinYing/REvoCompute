# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from revocompute_ctl.live_test import (
    RunnerLiveTestError,
    RunnerLiveTestWorker,
    TaskResourceSnapshot,
    ValidationIdentity,
)
from revocompute_ctl.registry import RuntimeFamily


class _State:
    def __init__(self, root: Path):
        self.root = root

    def server_dir(self):
        return str(self.root / "server")

    def exported(self):
        return {}

    def get(self, key):
        del key
        return None


def _worker(tmp_path: Path) -> RunnerLiveTestWorker:
    root = tmp_path / "runners" / "demo"
    root.mkdir(parents=True)
    return RunnerLiveTestWorker(
        _State(tmp_path),
        RuntimeFamily("demo", "1", "demo.def", "demo.sif", str(tmp_path / "images/demo.sif"), root=root),
    )


def _identity(*, with_case: bool = True) -> ValidationIdentity:
    cases = [SimpleNamespace(id="case", task="predict")] if with_case else []
    plan = SimpleNamespace(digest="test", select=lambda *_args, **_kwargs: cases)
    return ValidationIdentity(plan, "config", (TaskResourceSnapshot("predict", None, ()),))


def test_live_worker_records_explicit_success_lifecycle(tmp_path, monkeypatch):
    worker = _worker(tmp_path)

    def build(*_args, **_kwargs):
        worker.candidate.parent.mkdir(parents=True)
        worker.candidate.write_bytes(b"sif")

    monkeypatch.setattr("revocompute_ctl.live_test.build_slurm_images", build)
    digest = "sha256:6d27641e2684684537fb3f401639558228855c1d5721fd1b4b29fd70e8cffd1e"
    monkeypatch.setattr(
        "revocompute_ctl.live_test._read_sif_manifest",
        lambda _family: {"demo": {"sif_sha256": digest, "build_provenance_digest": "build"}},
    )
    monkeypatch.setattr(
        "revocompute_ctl.live_test._build_provenance",
        lambda *_args: {"build_provenance_digest": "build", "apptainer_version": "1.4"},
    )
    worker._load_identity = _identity
    worker._validate_candidate = lambda: None

    def run_case(case, report, resources):
        assert report.resource_snapshots[case.task] == resources.as_dict()
        for state in ("SUBMITTED", "RUNNING", "ACCEPTING"):
            worker._transition(report, state)
        return {"case_id": "case", "passed": True}

    worker._run_case = run_case
    report = worker.run()

    assert report.passed
    assert report.resource_snapshots == {
        "predict": {"resource_policy": None, "resource_policies": {}}
    }
    assert report.transitions == [
        "PREPARING", "BUILDING", "VALIDATING", "SEEDING", "SUBMITTED", "RUNNING", "ACCEPTING", "PASSED"
    ]


def test_live_worker_reports_validation_failure_and_timeout_category(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    worker.candidate.parent.mkdir(parents=True)
    worker.candidate.write_bytes(b"sif")
    digest = "sha256:6d27641e2684684537fb3f401639558228855c1d5721fd1b4b29fd70e8cffd1e"
    monkeypatch.setattr(
        "revocompute_ctl.live_test._read_sif_manifest",
        lambda _family: {"demo": {"sif_sha256": digest, "build_provenance_digest": "build"}},
    )
    monkeypatch.setattr(
        "revocompute_ctl.live_test._build_provenance",
        lambda *_args: {"build_provenance_digest": "build", "apptainer_version": "1.4"},
    )
    worker._load_identity = _identity
    worker._validate_candidate = lambda: (_ for _ in ()).throw(RunnerLiveTestError("SIF_VALIDATION_FAILURE", "bad sif"))

    report = worker.run(build=False)

    assert report.failure_category == "SIF_VALIDATION_FAILURE"
    assert report.transitions == ["PREPARING", "VALIDATING", "FAILED"]
    assert worker._runtime_failure_category({"slurm_job_id": "42"}, "time limit exceeded") == "TIMEOUT"


def test_live_worker_keeps_structured_case_when_seeding_fails(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    worker.candidate.parent.mkdir(parents=True)
    worker.candidate.write_bytes(b"sif")
    digest = "sha256:6d27641e2684684537fb3f401639558228855c1d5721fd1b4b29fd70e8cffd1e"
    monkeypatch.setattr(
        "revocompute_ctl.live_test._read_sif_manifest",
        lambda _family: {"demo": {"sif_sha256": digest, "build_provenance_digest": "build"}},
    )
    monkeypatch.setattr(
        "revocompute_ctl.live_test._build_provenance",
        lambda *_args: {"build_provenance_digest": "build", "apptainer_version": "1.4"},
    )
    worker._load_identity = _identity
    worker._validate_candidate = lambda: None
    worker._run_case = lambda *_args: (_ for _ in ()).throw(
        RunnerLiveTestError("INPUT_SEED_FAILURE", "fixture rejected")
    )

    report = worker.run(build=False)

    assert not report.passed
    assert report.failure_category == "INPUT_SEED_FAILURE"
    assert report.cases == [
        {
            "case_id": "case",
            "task_type": "predict",
            "passed": False,
            "task_status": None,
            "slurm_job_id": None,
            "failure_category": "INPUT_SEED_FAILURE",
            "failure_message": "fixture rejected",
            "duration_seconds": report.cases[0]["duration_seconds"],
        }
    ]


def test_live_worker_targets_explicit_active_artifact(tmp_path):
    worker = _worker(tmp_path)
    active = Path(worker.family.slurm_image)

    targeted = RunnerLiveTestWorker(worker.state, worker.family, artifact_path=active)

    assert targeted.artifact == active
    environment = targeted._runtime_environment(tmp_path / "work")
    assert environment["REVOCOMPUTE_RUNTIME_ARTIFACT_OVERRIDES"] == (
        '{"demo": "' + str(active.resolve()) + '"}'
    )


def test_live_worker_preserves_completed_workflow_job_evidence(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    monkeypatch.setattr(worker, "_slurm_state", lambda job_id: "" if job_id == "42" else "unexpected")

    evidence = worker._slurm_evidence(
        {
            "slurm_job_id": None,
            "workflow_state": json.dumps(
                {
                    "demo.features": {"status": "completed", "job_id": "41"},
                    "demo.model": {"status": "completed", "job_id": "42"},
                }
            ),
        }
    )

    assert evidence == {
        "slurm_job_id": "42",
        "slurm_terminal_state": "COMPLETED",
        "slurm_jobs": [
            {"stage": "demo.features", "job_id": "41", "state": "completed"},
            {"stage": "demo.model", "job_id": "42", "state": "completed"},
        ],
    }
