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
    active_receipt_valid,
    candidate_receipt_valid,
    run_live_tests,
)
from revocompute.live_tests import LiveTestReport, sha256_file
from revocompute_ctl.artifact_evidence import write_artifact_evidence
from revocompute_ctl.registry import RuntimeFamily


class _State:
    def __init__(self, root: Path):
        self.root = root
        self.env_file = str(root / "test.env")

    def server_dir(self):
        return str(self.root / "server")

    def exported(self):
        return {}

    def compose_args(self):
        return []

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
    cases = [SimpleNamespace(id="case", task="predict", parameters={})] if with_case else []
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
        "revocompute_ctl.live_test.read_artifact_evidence",
        lambda *_args: (digest, {"sif_sha256": digest, "build_provenance_digest": "build"}),
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
        "revocompute_ctl.live_test.read_artifact_evidence",
        lambda *_args: (digest, {"sif_sha256": digest, "build_provenance_digest": "build"}),
    )
    monkeypatch.setattr(
        "revocompute_ctl.live_test._build_provenance",
        lambda *_args: {"build_provenance_digest": "build", "apptainer_version": "1.4"},
    )
    worker._load_identity = _identity
    worker._validate_candidate = lambda: (_ for _ in ()).throw(
        RunnerLiveTestError("SIF_VALIDATION_FAILURE", "bad sif")
    )

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
        "revocompute_ctl.live_test.read_artifact_evidence",
        lambda *_args: (digest, {"sif_sha256": digest, "build_provenance_digest": "build"}),
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


def test_active_and_candidate_receipts_resolve_build_identity(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    active = Path(worker.family.slurm_image)
    candidate = worker.candidate
    active.parent.mkdir(parents=True)
    active.write_bytes(b"active-A")
    candidate.write_bytes(b"candidate-B")
    monkeypatch.setattr(RunnerLiveTestWorker, "_load_identity", lambda _self: _identity())
    monkeypatch.setattr(
        "revocompute_ctl.live_test._build_provenance",
        lambda *_args: {"build_provenance_digest": "build"},
    )
    for artifact in (active, candidate):
        write_artifact_evidence(
            worker.family,
            sha256_file(artifact),
            "receipt",
            {
                "receipt_contract_version": 2,
                "passed": True,
                "build_provenance_digest": "build",
                "test_definition_digest": "test",
                "configuration_digest": "config",
                "cases": [{"case_id": "case", "passed": True}],
            },
        )

    assert active_receipt_valid(worker.state, worker.family)
    assert candidate_receipt_valid(worker.state, worker.family)
    candidate.write_bytes(b"changed-after-validation")
    assert active_receipt_valid(worker.state, worker.family)
    assert candidate_receipt_valid(worker.state, worker.family)


def test_live_worker_uses_candidate_image_one_off_worker_and_contract_mount(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    artifact = Path(worker.family.slurm_image)
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"candidate")
    request_result = worker.work_root / "live-test-execution.json"
    request_result.parent.mkdir(parents=True)
    request_result.write_text(json.dumps({
        "execution_uid": 129, "execution_gid": 137, "scheduler_user": "revodesign",
        "slurm_job_id": "42", "slurm_jobs": [],
    }))
    commands = []
    monkeypatch.setattr("revocompute_ctl.live_test.build_web_images", lambda *_args: None)
    monkeypatch.setattr("revocompute_ctl.live_test.detect_compose_cmd", lambda: ("docker", "compose"))
    def fake_run(argv, **_kwargs):
        commands.append(list(argv))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr("revocompute_ctl.live_test.run_cmd", fake_run)
    result = worker._execute_in_worker("a" * 32, "predict", worker.work_root)
    assert result["execution_uid"] == 129
    command = commands[-1]
    assert command[:2] == ["docker", "compose"]
    assert "run" in command and "exec" not in command
    assert "--no-deps" in command
    assert f"SERVER_DIR={worker.state.server_dir()}/live-tests/{'a' * 32}" in command
    assert f"DB_PATH={worker.state.server_dir()}/live-tests/{'a' * 32}/live-test.sqlite3" in command
    assert any("/run/revocompute-candidate-runners" in value and value.endswith(":ro") for value in command)


def test_live_workers_share_candidate_server_image_build(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    artifact = Path(worker.family.slurm_image)
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"candidate")
    builds = []
    monkeypatch.setattr("revocompute_ctl.live_test.build_web_images", lambda *_args: builds.append(True))
    monkeypatch.setattr("revocompute_ctl.live_test.detect_compose_cmd", lambda: ("docker", "compose"))
    monkeypatch.setattr(
        "revocompute_ctl.live_test.run_cmd",
        lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": json.dumps({"task_status": "finished"}), "stderr": ""})(),
    )

    worker._execute_in_worker("a" * 32, "predict", worker.work_root)
    RunnerLiveTestWorker(worker.state, worker.family)._execute_in_worker("b" * 32, "predict", worker.work_root)

    assert len(builds) == 1


def test_live_test_refreshes_submission_attestations_after_receipt_update(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    published = []
    worker_build_flags = []
    monkeypatch.setattr("revocompute_ctl.live_test.load_plugin_families", lambda _root: [worker.family])
    monkeypatch.setattr("revocompute_ctl.live_test.prepare_live_test_server_image", lambda _state: None)
    monkeypatch.setattr(
        "revocompute_ctl.live_test.RunnerLiveTestWorker.run",
        lambda *_args, **kwargs: (worker_build_flags.append(kwargs["build"]) or SimpleNamespace(passed=True)),
    )
    monkeypatch.setattr(
        "revocompute_ctl.readiness.write_runner_attestation",
        lambda state, family: published.append((state, family)),
    )

    assert run_live_tests(
        worker.state,
        runner="demo",
        task=None,
        collection="smoke",
        all_runners=False,
    )
    assert published == [(worker.state, worker.family)]
    assert worker_build_flags == [True]


def test_live_test_skips_attestation_refresh_after_failure(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    published = []
    monkeypatch.setattr("revocompute_ctl.live_test.load_plugin_families", lambda _root: [worker.family])
    monkeypatch.setattr("revocompute_ctl.live_test.prepare_live_test_server_image", lambda _state: None)
    monkeypatch.setattr(
        "revocompute_ctl.live_test.RunnerLiveTestWorker.run",
        lambda *_args, **_kwargs: SimpleNamespace(passed=False),
    )
    monkeypatch.setattr(
        "revocompute_ctl.readiness.write_runner_attestation",
        lambda *_args: published.append(True),
    )

    assert not run_live_tests(
        worker.state,
        runner="demo",
        task=None,
        collection="smoke",
        all_runners=False,
    )
    assert published == []


def test_live_worker_builds_candidate_before_family_is_enabled(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    calls = []
    monkeypatch.setattr(
        "revocompute_ctl.live_test.build_slurm_images",
        lambda state, families, **kwargs: calls.append((state, families, kwargs)),
    )

    report = worker.run(build=True)
    assert report.failure_category == "BUILD_FAILURE"
    assert calls == [
        (
            worker.state,
            [worker.family],
            {"fail_on_error": True, "include_disabled": True},
        )
    ]


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


def test_live_worker_identity_acceptance_is_fail_closed():
    expected = (129, 137, "revodesign")
    correct = {"execution_uid": 129, "execution_gid": 137, "scheduler_user": "revodesign", "slurm_jobs": []}
    assert RunnerLiveTestWorker._execution_identity_matches(correct, expected)
    for key, value in (("execution_uid", 1), ("execution_gid", 1), ("scheduler_user", "yinying")):
        altered = {**correct, key: value}
        assert not RunnerLiveTestWorker._execution_identity_matches(altered, expected)
    assert not RunnerLiveTestWorker._execution_identity_matches(
        {**correct, "scheduler_user": None, "slurm_jobs": [{"stage": "model", "scheduler_user": None}]},
        expected,
    )
    assert not RunnerLiveTestWorker._execution_identity_matches(
        {**correct, "slurm_jobs": [{"stage": "model"}]}, expected
    )
    assert not RunnerLiveTestWorker._execution_identity_matches({**correct, "slurm_jobs": {}}, expected)


def test_live_worker_gpu_accounting_acceptance_requires_exact_slurm_settlement():
    execution = {
        "slurm_job_id": "42",
        "slurm_jobs": [{"stage": "model", "job_id": "42"}],
    }
    evidence = {
        "task_id": "a" * 32,
        "user_id": 1,
        "period": "2026-09",
        "before_remaining_gpu_seconds": 60_000,
        "after_remaining_gpu_seconds": 59_978,
        "usage_gpu_seconds": 22,
        "allocations": [
            {
                "slurm_job_id": "42",
                "task_id": "a" * 32,
                "user_id": 1,
                "stage_id": "model",
                "gpu_count": 2,
                "started_at": 100.0,
                "finished_at": 110.2,
                "gpu_seconds": 22,
                "status": "settled",
            }
        ],
        "usage_entries": [
            {
                "kind": "usage",
                "gpu_seconds": -22,
                "task_id": "a" * 32,
                "user_id": 1,
                "period": "2026-09",
                "stage_id": "model",
                "slurm_job_id": "42",
            }
        ],
    }

    assert RunnerLiveTestWorker._gpu_accounting_valid(execution, evidence)
    for key, value in (
        ("after_remaining_gpu_seconds", 59_979),
        ("usage_gpu_seconds", 21),
        ("usage_entries", [{**evidence["usage_entries"][0], "gpu_seconds": -21}]),
    ):
        assert not RunnerLiveTestWorker._gpu_accounting_valid(execution, {**evidence, key: value})
    changed_allocation = {**evidence["allocations"][0], "slurm_job_id": "43"}
    assert not RunnerLiveTestWorker._gpu_accounting_valid(
        execution,
        {**evidence, "allocations": [changed_allocation]},
    )


def test_live_worker_requires_matching_slurm_resource_observations():
    policy = json.dumps(
        {
            "cpus": 4,
            "ntasks": 1,
            "requires_gpu": True,
        }
    )
    resources = TaskResourceSnapshot("predict", policy, ())
    observation = {
        "job_id": "42",
        "accounting_available": True,
        "rows": [
            {
                "JobIDRaw": "42",
                "State": "COMPLETED",
                "ElapsedRaw": "11",
                "AllocCPUS": "4",
                "AllocTRES": "cpu=4,mem=8G,gres/gpu:a100=1",
                "TotalCPU": "00:00:09",
                "MaxRSS": "128M",
            }
        ],
        "accelerator_metrics_available": True,
        "accelerator_rows": [
            {
                "JobIDRaw": "42.batch",
                "TRESUsageInMax": "gres/gpumem=2048M,gres/gpuutil=76",
                "TRESUsageInAve": "gres/gpuutil=54",
            }
        ],
    }
    execution = {
        "slurm_job_id": "42",
        "slurm_jobs": [{"stage": "main", "job_id": "42", "resource_observation": observation}],
    }

    assert RunnerLiveTestWorker._resource_observations_valid(execution, resources)
    for changed_row in (
        {**observation["rows"][0], "State": "FAILED"},
        {**observation["rows"][0], "AllocCPUS": "3"},
        {**observation["rows"][0], "AllocTRES": "cpu=4,mem=8G"},
        {**observation["rows"][0], "TotalCPU": ""},
        {**observation["rows"][0], "MaxRSS": ""},
    ):
        changed = {**observation, "rows": [changed_row]}
        changed_execution = {
            **execution,
            "slurm_jobs": [{"stage": "main", "job_id": "42", "resource_observation": changed}],
        }
        assert not RunnerLiveTestWorker._resource_observations_valid(changed_execution, resources)
    assert not RunnerLiveTestWorker._resource_observations_valid(
        {**execution, "slurm_jobs": [{"stage": "main", "job_id": "42"}]},
        resources,
    )


def test_live_worker_accepts_complete_cpu_wrapper_observation_when_sacct_is_disabled():
    resources = TaskResourceSnapshot(
        "predict",
        json.dumps({"cpus": 2, "ntasks": 1, "requires_gpu": False}),
        (),
    )
    wrapper = {
        "schema_version": 1,
        "source": "allocation_wrapper",
        "job_id": "42",
        "allocated_cpus_per_task": 2,
        "allocated_tasks": 1,
        "allocated_gpus_on_node": "",
        "allocated_gpu_ids": "",
        "visible_gpu_devices": "",
        "exit_code": 0,
        "elapsed_seconds": 1.2,
        "user_cpu_seconds": 0.8,
        "system_cpu_seconds": 0.1,
        "max_rss_kib": 2048,
    }
    execution = {
        "slurm_job_id": "42",
        "slurm_jobs": [
            {
                "stage": "main",
                "job_id": "42",
                "resource_observation": {
                    "job_id": "42",
                    "accounting_available": True,
                    "rows": [],
                    "source": "allocation_wrapper",
                    "wrapper": wrapper,
                },
            }
        ],
    }

    assert RunnerLiveTestWorker._resource_observations_valid(execution, resources)
    for key, value in (
        ("job_id", "43"),
        ("allocated_cpus_per_task", 1),
        ("exit_code", 1),
        ("max_rss_kib", 0),
    ):
        changed = {**wrapper, key: value}
        changed_execution = {
            **execution,
            "slurm_jobs": [
                {
                    **execution["slurm_jobs"][0],
                    "resource_observation": {
                        **execution["slurm_jobs"][0]["resource_observation"],
                        "wrapper": changed,
                    },
                }
            ],
        }
        assert not RunnerLiveTestWorker._resource_observations_valid(changed_execution, resources)


def test_gpu_live_case_fails_when_execution_has_no_accounting_evidence(tmp_path, monkeypatch):
    worker = _worker(tmp_path)
    artifact = Path(worker.family.slurm_image)
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"candidate")
    case = SimpleNamespace(id="gpu-case", task="predict", inputs={}, parameters={})
    resources = TaskResourceSnapshot(
        "predict",
        json.dumps({"cpus": 1, "ntasks": 1, "requires_gpu": True}),
        (),
    )
    execution = {
        "task_status": "finished",
        "error": None,
        "execution_uid": 129,
        "execution_gid": 137,
        "scheduler_user": "revodesign",
        "slurm_job_id": "42",
        "slurm_jobs": [
            {
                "stage": "main",
                "job_id": "42",
                "scheduler_user": "revodesign",
                "resource_observation": {
                    "job_id": "42",
                    "accounting_available": True,
                    "rows": [
                        {
                            "JobIDRaw": "42",
                            "State": "COMPLETED",
                            "ElapsedRaw": "1",
                            "AllocCPUS": "1",
                            "AllocTRES": "cpu=1,gres/gpu=1",
                            "TotalCPU": "00:00:01",
                            "MaxRSS": "1M",
                        }
                    ],
                    "accelerator_metrics_available": True,
                    "accelerator_rows": [
                        {
                            "JobIDRaw": "42.batch",
                            "TRESUsageInMax": "gres/gpumem=1M,gres/gpuutil=1",
                            "TRESUsageInAve": "gres/gpuutil=1",
                        }
                    ],
                },
            }
        ],
        "output_check": {"state": "passed", "problems": []},
        "artifacts": [{"path": "result.json", "size": 10}],
        "gpu_accounting": None,
    }
    monkeypatch.setattr(worker, "_execute_in_worker", lambda *args, **kwargs: execution)
    monkeypatch.setattr(worker, "_configured_execution_identity", lambda: (129, 137, "revodesign"))

    result = worker._run_case(case, LiveTestReport("demo", "smoke", "", "", "", ""), resources)

    assert result["passed"] is False
    assert result["failure_category"] == "GPU_ACCOUNTING_FAILURE"
