# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Focused coverage for the machine-generated production API acceptance receipt.

The receipt is derived entirely from canonical state, so these tests build that
state (a task row, a published ResultManifest, its result artifacts, and the
executor's Slurm accounting) and assert what the generator observes from it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "run"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from revocompute_ctl.api_receipt import (
    ApiReceiptCaptureError,
    capture_api_receipt,
    receipt_path,
)
from revocompute_ctl.env import EnvState

from revocompute.api_receipt import (
    API_RECEIPT_KIND,
    API_RECEIPT_VERSION,
    ApiReceiptError,
    build_api_receipt,
    parse_api_receipt,
    receipt_failures,
    render_api_receipt_summary,
)

TASK_ID = "944ed43af62ead9f5c9560bae1ccd897"
STORAGE_KEY = "tester-t9c7f33h"


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _summary_payload() -> dict:
    return {
        "schema_version": 2,
        "method": "GREMLIN_LH",
        "alignment": {
            "sequence_count": 6,
            "alignment_length": 79,
            "effective_sequence_count": 2.8667,
            "columns_excluded_by_gap_cutoff": 3,
        },
        "model": {"positions": 79, "states": 21, "regularization": "LH"},
        "optimization": {"final_loss": 42.9618, "iterations": 50},
    }


class _PublishedTask:
    """A finished production submission's canonical on-disk state."""

    def __init__(self, root: Path, *, status: str = "finished", summary: dict | None = None):
        self.result_root = root
        self.result_root.mkdir(parents=True, exist_ok=True)
        self.files = {
            "summary.json": json.dumps(summary if summary is not None else _summary_payload()).encode(),
            "alignment/filtered_alignment.a3m": b">a\nMKT\n>b\nMKT\n",
            "couplings/raw_scores.csv": b"position,1,2\n1,0,1\n2,1,0\n",
        }
        artifacts = []
        logical_summary = []
        for relative, payload in sorted(self.files.items()):
            path = self.result_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            entry = {
                "path": relative,
                "size": len(payload),
                "sha256": _sha256(path),
                "media_type": "application/json" if relative.endswith(".json") else "text/plain",
                "role": "provenance" if relative.endswith("summary.json") else "evidence",
            }
            artifacts.append(entry)
            if relative == "summary.json":
                logical_summary.append({**entry, "logical_type": "json", "cardinality": "one"})
        self.manifest = {
            "schema_version": 3,
            "task_id": TASK_ID,
            "task_type": "gremlin_lh_fit",
            "created_at": "2026-10-04T03:24:33.471+00:00",
            "run": {
                "method": {"id": "gremlin_lh_fit", "name": "GREMLIN_LH Potts model"},
                "inputs": [
                    {
                        "role": "alignment",
                        "path": "2KL8.i90c75_aln.a3m",
                        "sha256": "b0" * 32,
                        "format": "a3m",
                        "logical_type": "alignment",
                    }
                ],
                "parameters": [
                    {"name": "regularization", "label": "Regularization", "value": "LH", "unit": ""},
                    {"name": "iterations", "label": "Iterations", "value": 50, "unit": ""},
                ],
                "submitted_at": "2026-10-04T03:24:09.730+00:00",
                "started_at": "2026-10-04T03:24:10.100+00:00",
                "finished_at": "2026-10-04T03:24:33.471+00:00",
                "walltime_seconds": 23.61,
                "citations": [],
            },
            "output_check": {"state": "passed", "checks": [], "problems": []},
            "limitations": [],
            "artifacts": artifacts,
            "views": [
                {"id": "raw_couplings", "plugin": "matrix", "role": "primary", "title": "Coupling strength (raw Frobenius)", "sources": {"matrices": ["couplings/raw_scores.csv"]}},
            ],
            "result": {"files": {"summary": logical_summary, "raw_matrix": [{**artifacts[-1], "cardinality": "one"}]}},
            "storyboard": None,
            "total_size": sum(len(payload) for payload in self.files.values()),
        }
        (self.result_root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.task_row = {
            "md5sum": TASK_ID,
            "status": status,
            "task_type": "gremlin_lh_fit",
            "filename": "2KL8.i90c75_aln.a3m",
            "slurm_job_id": "10304",
            "storage_key": STORAGE_KEY,
        }
        execution = self.result_root / "execution"
        execution.mkdir(exist_ok=True)
        (execution / f"slurm-revodesign-gremlin_lh_fit-{TASK_ID}.resource.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "source": "allocation_wrapper",
                    "job_id": "10304",
                    "exit_code": 0,
                    "elapsed_seconds": 23.42,
                    "max_rss_kib": 486944,
                    "user_cpu_seconds": 25.52,
                    "system_cpu_seconds": 2.01,
                    "allocated_cpus_per_task": 1,
                    "allocated_tasks": 1,
                }
            ),
            encoding="utf-8",
        )

    def build(self, **overrides):
        arguments = {
            "task_id": TASK_ID,
            "manifest": self.manifest,
            "task_row": self.task_row,
            "result_root": str(self.result_root),
            # The task finishes AFTER the stamp, so the current deployment may
            # legitimately have executed it.
            "deployment_stamp": {"commit": "c82ea79", "dirty": True, "mode": "dev", "stamped_at": "2026-10-04T03:00:00+00:00"},
            "resource_payload": json.loads((self.result_root / "execution" / f"slurm-revodesign-gremlin_lh_fit-{TASK_ID}.resource.json").read_text()),
            "status_evidence": {
                "endpoint": "/compute/api/running/<task_id>",
                "http_status": 200,
                "status": "finished",
                "terminal": True,
                "result_available": True,
            },
            "base_url": "https://revocompute.example",
            "captured_at": "2026-10-04T04:00:00+00:00",
        }
        arguments.update(overrides)
        return build_api_receipt(**arguments)


@pytest.fixture()
def published(tmp_path: Path) -> _PublishedTask:
    return _PublishedTask(tmp_path / "results" / "users" / STORAGE_KEY / "tasks" / TASK_ID)


def test_receipt_derives_the_gremlin_lh_observables_from_published_evidence(published):
    receipt = published.build()

    assert receipt["complete"] is True
    assert receipt_failures(receipt) == []
    assert receipt["kind"] == API_RECEIPT_KIND
    assert receipt["receipt_version"] == API_RECEIPT_VERSION
    assert receipt["submission"]["task_type"] == "gremlin_lh_fit"
    assert receipt["submission"]["parameters"] == [
        {"name": "regularization", "value": "LH", "unit": ""},
        {"name": "iterations", "value": 50, "unit": ""},
    ]
    summary = receipt["observables"]["summary"]
    assert summary["alignment.sequence_count"] == 6
    assert summary["alignment.alignment_length"] == 79
    assert summary["alignment.effective_sequence_count"] == 2.8667
    assert summary["optimization.final_loss"] == 42.9618
    # Derived, not transcribed: three published artifacts, each re-hashed.
    assert {artifact["path"] for artifact in receipt["result"]["artifacts"]} == set(published.files)
    assert receipt["scheduler"]["slurm_job_id"] == "10304"
    assert receipt["scheduler"]["max_rss_kib"] == 486944
    assert receipt["scheduler"]["job_id_matches"] is True


def test_receipt_is_deterministic_for_the_same_evidence(published):
    first = published.build()
    second = published.build()
    assert first == second
    assert first["receipt_digest"] == second["receipt_digest"]


def test_receipt_digest_ignores_only_volatile_capture_metadata(published):
    base = published.build()
    later = published.build(captured_at="2027-01-01T00:00:00+00:00")
    assert later["receipt_digest"] == base["receipt_digest"]
    assert later["captured_at"] != base["captured_at"]


def test_receipt_derives_lifecycle_intervals_from_observed_timestamps(published):
    receipt = published.build()
    intervals = receipt["lifecycle"]["intervals"]
    assert intervals["queue_seconds"] == pytest.approx(0.37, abs=1e-6)
    assert intervals["execution_seconds"] == pytest.approx(23.371, abs=1e-6)
    assert intervals["observed_seconds"] == pytest.approx(23.741, abs=1e-6)


def test_receipt_rejects_a_manifest_that_names_a_different_task(published):
    manifest = {**published.manifest, "task_id": "0" * 32}
    receipt = published.build(manifest=manifest)
    assert receipt["complete"] is False
    assert any("task identity" in problem for problem in receipt["problems"])


def test_receipt_rejects_an_unfinished_task(published):
    row = {**published.task_row, "status": "running"}
    receipt = published.build(task_row=row)
    assert receipt["complete"] is False
    assert any("not a finished success" in problem for problem in receipt["problems"])


def test_receipt_rejects_a_missing_artifact(published):
    (published.result_root / "couplings" / "raw_scores.csv").unlink()
    receipt = published.build()
    assert receipt["complete"] is False
    assert any("missing" in problem for problem in receipt["problems"])


def test_receipt_rejects_bytes_that_disagree_with_the_manifest(published):
    (published.result_root / "summary.json").write_text("{}", encoding="utf-8")
    receipt = published.build()
    assert receipt["complete"] is False
    assert any("sha256 disagrees" in problem for problem in receipt["problems"])


def test_receipt_rejects_an_artifact_path_that_escapes_the_result_root(tmp_path: Path):
    root = tmp_path / "task"
    root.mkdir()
    (tmp_path / "escaped.txt").write_bytes(b"outside")
    manifest = {
        "schema_version": 3,
        "task_id": TASK_ID,
        "task_type": "gremlin_lh_fit",
        "output_check": {"state": "passed", "problems": []},
        "artifacts": [{"path": "../escaped.txt", "size": 7, "sha256": "0" * 64, "role": "artifact"}],
        "result": {"files": {}},
        "views": [],
    }
    receipt = build_api_receipt(
        task_id=TASK_ID,
        manifest=manifest,
        task_row={"md5sum": TASK_ID, "status": "finished", "task_type": "gremlin_lh_fit"},
        result_root=str(root),
    )
    assert receipt["complete"] is False
    assert any("safe relative path" in problem for problem in receipt["problems"])


def test_receipt_rejects_malformed_timestamps_and_negative_intervals(published):
    run = dict(published.manifest["run"])
    run["submitted_at"] = "not-a-timestamp"
    run["started_at"] = "2026-10-04T03:00:00+00:00"
    run["finished_at"] = "2026-10-04T02:00:00+00:00"
    receipt = published.build(manifest={**published.manifest, "run": run})
    assert receipt["complete"] is False
    assert any("submitted_at is malformed" in problem for problem in receipt["problems"])
    assert any("negative lifecycle interval" in problem for problem in receipt["problems"])


def test_receipt_marks_a_missing_deploy_stamp_incomplete(published):
    receipt = published.build(deployment_stamp=None)
    assert receipt["complete"] is False
    assert receipt["deployment"]["available"] is False
    assert any("deployed revision is not observable" in problem for problem in receipt["problems"])


def test_receipt_records_the_observed_runtime_sif_digest(published):
    receipt = published.build(runtime_sif_sha256="sha256:" + "b" * 64)
    assert receipt["deployment"]["runtime_sif_sha256"] == "sha256:" + "b" * 64
    assert receipt["complete"] is True


def test_receipt_reports_a_nonzero_exit_code(published):
    payload_path = published.result_root / "execution" / f"slurm-revodesign-gremlin_lh_fit-{TASK_ID}.resource.json"
    payload = json.loads(payload_path.read_text())
    payload["exit_code"] = 9
    receipt = published.build(resource_payload=payload)
    assert receipt["complete"] is False
    assert any("exit code is nonzero" in problem for problem in receipt["problems"])


def test_receipt_reports_scheduler_identity_mismatch(published):
    payload = {"source": "allocation_wrapper", "job_id": "99999", "exit_code": 0}
    receipt = published.build(resource_payload=payload)
    assert receipt["scheduler"]["job_id_matches"] is False
    assert receipt["complete"] is False


def test_receipt_fails_closed_when_scheduler_evidence_is_missing(published):
    receipt = published.build(resource_payload=None, task_row={**published.task_row, "slurm_job_id": None})
    assert receipt["complete"] is False
    assert any("no scheduler job id" in problem for problem in receipt["problems"])
    assert any("no scheduler accounting source" in problem for problem in receipt["problems"])
    assert any("no scheduler exit code" in problem for problem in receipt["problems"])


def test_receipt_rejects_failed_output_validation(published):
    manifest = {
        **published.manifest,
        "output_check": {"state": "failed", "checks": [], "problems": ["required output is missing"]},
    }
    receipt = published.build(manifest=manifest)
    assert receipt["complete"] is False
    assert any("failed output validation" in problem for problem in receipt["problems"])


def test_receipt_rejects_deployment_attribution_for_a_predating_task(published):
    # A task finished before the current stamp cannot claim that deployment.
    stamp = {"commit": "c82ea79", "dirty": True, "mode": "dev", "stamped_at": "2026-10-04T09:30:00+00:00"}
    receipt = published.build(deployment_stamp=stamp)
    assert receipt["complete"] is False
    assert receipt["deployment"]["execution_deployment_established"] is False
    assert receipt["deployment"]["runtime_sif_sha256"] is None
    assert any("deployment attribution is not established" in problem for problem in receipt["problems"])


def test_receipt_requires_observed_api_status(published):
    receipt = published.build(status_evidence=None)
    assert receipt["complete"] is False
    assert receipt["api_status_evidence"] is None
    assert any("public API status was not observed" in problem for problem in receipt["problems"])


def test_receipt_rejects_api_status_that_is_not_a_finished_success(published):
    receipt = published.build(
        status_evidence={"endpoint": "/x", "http_status": 202, "status": "running", "terminal": False}
    )
    assert receipt["complete"] is False
    assert any("public API status is not a finished success" in problem for problem in receipt["problems"])


def test_receipt_rejects_a_logical_file_absent_from_the_inventory(published):
    manifest = {**published.manifest, "result": {"files": {"ghost": [{"path": "couplings/ghost.csv", "role": "evidence"}]}}}
    receipt = published.build(manifest=manifest)
    assert receipt["complete"] is False
    assert any("absent from the artifact inventory" in problem for problem in receipt["problems"])


def test_receipt_rejects_a_logical_file_that_escapes_the_result_root(published):
    manifest = {**published.manifest, "result": {"files": {"escape": [{"path": "../outside.txt", "role": "evidence"}]}}}
    receipt = published.build(manifest=manifest)
    assert receipt["complete"] is False
    assert any("unsafe path" in problem for problem in receipt["problems"])


def test_receipt_never_carries_a_secret(published):
    poisoned = {
        **published.manifest,
        "run": {
            **published.manifest["run"],
            "inputs": [
                {
                    "role": "alignment",
                    "path": "2KL8.i90c75_aln.a3m",
                    "sha256": "b0" * 32,
                    "format": "a3m",
                    "logical_type": "alignment",
                    "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0ZXIifQ.abcdefghijklmnopqrstuvwxyz",
                }
            ],
        },
    }
    task_row = {
        **published.task_row,
        "request_headers": json.dumps({"Authorization": "Bearer supersecrettokenvalue1234567890", "Cookie": "auth_token=x"}),
    }
    receipt = published.build(manifest=poisoned, task_row=task_row)
    serialized = json.dumps(receipt)
    assert "supersecrettokenvalue" not in serialized
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in serialized
    assert "auth_token" not in serialized
    assert any("redacted" in problem for problem in receipt["problems"])


def test_receipt_marks_a_secret_key_by_name_even_without_a_recognisable_value(published):
    manifest = {
        **published.manifest,
        "run": {**published.manifest["run"], "api_token": "plain-looking-value"},
    }
    receipt = published.build(manifest=manifest)
    assert "plain-looking-value" not in json.dumps(receipt)


def test_parse_api_receipt_rejects_a_foreign_document(published):
    with pytest.raises(ApiReceiptError):
        parse_api_receipt({"receipt_version": 999, "kind": API_RECEIPT_KIND})
    with pytest.raises(ApiReceiptError):
        parse_api_receipt({"receipt_version": API_RECEIPT_VERSION, "kind": "something_else"})


def test_parse_api_receipt_round_trips_a_complete_receipt(published):
    receipt = published.build()
    assert parse_api_receipt(receipt) == receipt


def test_parse_api_receipt_fails_closed_on_a_tampered_artifact_hash(published):
    receipt = published.build()
    receipt["result"]["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(ApiReceiptError, match="receipt_digest"):
        parse_api_receipt(receipt)


def test_parse_api_receipt_fails_closed_on_a_tampered_summary_observable(published):
    receipt = published.build()
    receipt["observables"]["summary"]["optimization.final_loss"] = 0.0
    with pytest.raises(ApiReceiptError, match="receipt_digest"):
        parse_api_receipt(receipt)


def test_parse_api_receipt_fails_closed_when_the_digest_is_absent(published):
    receipt = published.build()
    receipt.pop("receipt_digest")
    with pytest.raises(ApiReceiptError, match="receipt_digest"):
        parse_api_receipt(receipt)


def test_parse_api_receipt_accepts_volatile_capture_metadata_changes(published):
    receipt = published.build()
    receipt["captured_at"] = "2027-01-01T00:00:00+00:00"
    assert parse_api_receipt(receipt) == receipt


def test_summary_render_names_the_key_facts(published):
    receipt = published.build()
    rendered = render_api_receipt_summary(receipt)
    assert TASK_ID in rendered
    assert "10304" in rendered
    assert "effective_sequence_count = 2.8667" in rendered
    assert "complete=True" in rendered


def test_receipt_rejects_an_invalid_task_id(published):
    with pytest.raises(ApiReceiptError):
        published.build(task_id="not-a-task-id")


def test_receipt_is_bounded_against_a_tensor_shaped_summary(published):
    summary = _summary_payload()
    summary["model"]["couplings"] = [[float(i * j) for j in range(400)] for i in range(400)]
    (published.result_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    artifact = next(item for item in published.manifest["artifacts"] if item["path"] == "summary.json")
    artifact["size"] = (published.result_root / "summary.json").stat().st_size
    artifact["sha256"] = _sha256(published.result_root / "summary.json")
    receipt = published.build()
    # The nested tensor is not a scalar leaf, so it is not copied into the receipt.
    assert "model.couplings" not in receipt["observables"]["summary"]
    assert len(receipt["observables"]["summary"]) <= 200


# ---------------------------------------------------------------------------
# Operator command: reading the deployment's own state
# ---------------------------------------------------------------------------


def _deployment(tmp_path: Path) -> EnvState:
    """A deployment env state whose store, results, and stamp the fixture wrote."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / ".deploy-stamp").write_text(
        json.dumps({"commit": "deadbeef", "dirty": False, "mode": "dev", "stamped_at": "2026-10-04T03:19:00+00:00"}),
        encoding="utf-8",
    )
    return EnvState(
        str(tmp_path / "server.env"),
        values={
            "SERVER_DIR": str(tmp_path),
            "CONFIG_DIR": str(config_dir),
            "DB_PATH": str(tmp_path / "revocompute.sqlite3"),
            "RESULTS_FOLDER": str(tmp_path / "results"),
            "SERVER_BASE_URL": "https://revocompute.example",
        },
    )


def _seed_task_store(db_path: Path, row: dict) -> None:
    import sqlite3

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE tasks (md5sum TEXT PRIMARY KEY, status TEXT, task_type TEXT, "
            "filename TEXT, slurm_job_id TEXT, storage_key TEXT)"
        )
        connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["md5sum"],
                row["status"],
                row["task_type"],
                row["filename"],
                row["slurm_job_id"],
                row["storage_key"],
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_operator_command_reads_the_deployment_state_and_writes_the_receipt(tmp_path: Path):
    published = _PublishedTask(tmp_path / "results" / "users" / STORAGE_KEY / "tasks" / TASK_ID)
    state = _deployment(tmp_path)
    _seed_task_store(Path(state.get("DB_PATH")), published.task_row)
    status = {
        "endpoint": "/compute/api/running/<task_id>",
        "http_status": 200,
        "status": "finished",
        "terminal": True,
        "result_available": True,
    }

    receipt, destination = capture_api_receipt(
        state, TASK_ID, runtime_sif_sha256="sha256:" + "a" * 64, status_evidence=status
    )

    assert destination == receipt_path(state.config_dir(), TASK_ID)
    assert json.loads(destination.read_text(encoding="utf-8")) == receipt
    assert receipt["complete"] is True
    assert receipt["host"]["endpoint_host"] == "revocompute.example"
    assert receipt["deployment"]["commit"] == "deadbeef"
    assert receipt["deployment"]["runtime_sif_sha256"] == "sha256:" + "a" * 64
    assert receipt["scheduler"]["max_rss_kib"] == 486944


def test_operator_command_refuses_a_task_with_no_store_row(tmp_path: Path):
    _PublishedTask(tmp_path / "results" / "users" / STORAGE_KEY / "tasks" / TASK_ID)
    state = _deployment(tmp_path)
    _seed_task_store(
        Path(state.get("DB_PATH")),
        {
            "md5sum": "0" * 32,
            "status": "finished",
            "task_type": "x",
            "filename": "f",
            "slurm_job_id": "1",
            "storage_key": STORAGE_KEY,
        },
    )
    with pytest.raises(ApiReceiptCaptureError, match="not in the task store"):
        capture_api_receipt(state, TASK_ID)


def test_operator_command_verifies_a_checked_in_receipt(tmp_path: Path):
    """A receipt the tool wrote is accepted by the same verifier on re-read."""
    published = _PublishedTask(tmp_path / "results" / "users" / STORAGE_KEY / "tasks" / TASK_ID)
    state = _deployment(tmp_path)
    _seed_task_store(Path(state.get("DB_PATH")), published.task_row)
    status = {
        "endpoint": "/compute/api/running/<task_id>",
        "http_status": 200,
        "status": "finished",
        "terminal": True,
        "result_available": True,
    }

    receipt, destination = capture_api_receipt(
        state, TASK_ID, runtime_sif_sha256="sha256:" + "c" * 64, status_evidence=status
    )
    reloaded = json.loads(destination.read_text(encoding="utf-8"))
    assert parse_api_receipt(reloaded) == receipt


def test_operator_command_refuses_to_capture_without_observing_the_api(tmp_path: Path, monkeypatch):
    """The documented path will not produce an API acceptance from state alone."""
    published = _PublishedTask(tmp_path / "results" / "users" / STORAGE_KEY / "tasks" / TASK_ID)
    state = _deployment(tmp_path)
    _seed_task_store(Path(state.get("DB_PATH")), published.task_row)
    monkeypatch.delenv("REVOCOMPUTE_API_USER", raising=False)
    monkeypatch.delenv("REVOCOMPUTE_API_PASSWORD", raising=False)
    with pytest.raises(ApiReceiptCaptureError, match="public API status could not be observed"):
        capture_api_receipt(state, TASK_ID, runtime_sif_sha256="sha256:" + "d" * 64)


def test_operator_command_refuses_a_task_with_no_manifest(tmp_path: Path):
    published = _PublishedTask(tmp_path / "results" / "users" / STORAGE_KEY / "tasks" / TASK_ID)
    (published.result_root / "manifest.json").unlink()
    state = _deployment(tmp_path)
    _seed_task_store(Path(state.get("DB_PATH")), published.task_row)
    with pytest.raises(ApiReceiptCaptureError, match="no published ResultManifest"):
        capture_api_receipt(state, TASK_ID)


def test_cli_argument_contract_requires_exactly_a_task_id(capsys):
    from revocompute_ctl.__main__ import parse_args

    subcommand, _, flags = parse_args(["api-receipt", "--task", TASK_ID])
    assert subcommand == "api-receipt"
    assert flags.task == TASK_ID
    for invalid in (["api-receipt"], ["api-receipt", "--task", TASK_ID, "--runner", "gremlin_lh"]):
        with pytest.raises(SystemExit):
            parse_args(invalid)
