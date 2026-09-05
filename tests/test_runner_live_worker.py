# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from revocompute_ctl.live_test import RunnerLiveTestError, RunnerLiveTestWorker
from revocompute_ctl.registry import RuntimeFamily


class _State:
    def __init__(self, root: Path):
        self.root = root

    def server_dir(self):
        return str(self.root / "server")

    def exported(self):
        return {}


def _worker(tmp_path: Path) -> RunnerLiveTestWorker:
    root = tmp_path / "runners" / "demo"
    root.mkdir(parents=True)
    return RunnerLiveTestWorker(
        _State(tmp_path),
        RuntimeFamily("demo", "1", "demo.def", "demo.sif", str(tmp_path / "images/demo.sif"), root=root),
    )


def test_live_worker_records_explicit_success_lifecycle(tmp_path, monkeypatch):
    worker = _worker(tmp_path)

    def build(*_args, **_kwargs):
        worker.candidate.parent.mkdir(parents=True)
        worker.candidate.write_bytes(b"sif")

    monkeypatch.setattr("revocompute_ctl.live_test.build_slurm_images", build)
    digest = "sha256:6d27641e2684684537fb3f401639558228855c1d5721fd1b4b29fd70e8cffd1e"
    monkeypatch.setattr("revocompute_ctl.live_test._read_sif_manifest", lambda _family: {"demo": {"sif_sha256": digest, "build_provenance_digest": "build"}})
    monkeypatch.setattr("revocompute_ctl.live_test._build_provenance", lambda *_args: {"build_provenance_digest": "build", "apptainer_version": "1.4"})
    worker._load_plan = lambda: (SimpleNamespace(digest="test", select=lambda *_args, **_kwargs: [SimpleNamespace(id="case")]), "config")
    worker._validate_candidate = lambda: None

    def run_case(_case, report):
        for state in ("SUBMITTED", "RUNNING", "ACCEPTING"):
            worker._transition(report, state)
        return {"case_id": "case", "passed": True}

    worker._run_case = run_case
    report = worker.run()

    assert report.passed
    assert report.transitions == [
        "PREPARING", "BUILDING", "VALIDATING", "SEEDING", "SUBMITTED", "RUNNING", "ACCEPTING", "PASSED"
    ]


def test_live_worker_reports_validation_failure_and_timeout_category(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    worker.candidate.parent.mkdir(parents=True)
    worker.candidate.write_bytes(b"sif")
    digest = "sha256:6d27641e2684684537fb3f401639558228855c1d5721fd1b4b29fd70e8cffd1e"
    monkeypatch.setattr("revocompute_ctl.live_test._read_sif_manifest", lambda _family: {"demo": {"sif_sha256": digest, "build_provenance_digest": "build"}})
    monkeypatch.setattr("revocompute_ctl.live_test._build_provenance", lambda *_args: {"build_provenance_digest": "build", "apptainer_version": "1.4"})
    worker._load_plan = lambda: (SimpleNamespace(digest="test"), "config")
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
    worker._load_plan = lambda: (
        SimpleNamespace(
            digest="test",
            select=lambda *_args, **_kwargs: [SimpleNamespace(id="case", task="predict")],
        ),
        "config",
    )
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
