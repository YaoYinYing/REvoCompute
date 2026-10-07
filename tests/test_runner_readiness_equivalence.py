# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Cross-surface readiness identity.

CLI status, production admission, and the Admin API must answer the readiness
question from one evaluator, so a Runner cannot be READY on the CLI and
unavailable to a submission (or vice versa).  These cases drive the real
evaluator and prove the three surfaces agree on state, reason code, and the
evidence identity a submission would bind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from revocompute.admission import RunnerReadinessStatus, resolve_submission_readiness
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_readiness import (
    evaluate_fleet_readiness,
    evaluate_runner_readiness,
    runner_status_snapshot,
)
from revocompute.runner_registry import RuntimeFamily


class _EnvState:
    """The CLI's host view, as ``revocompute_ctl.env.EnvState`` provides it."""

    def __init__(self, root: Path):
        self.root = root

    def get(self, key: str, default: str = "") -> str:
        return str(self.root / "runners") if key == "RUNNER_SOURCE_ROOT" else default

    def server_dir(self) -> str:
        return str(self.root / "server")

    def config_dir(self) -> str:
        return str(self.root / "config")

    def server_root(self) -> str:
        return str(self.root)

    def exported(self) -> dict[str, str]:
        return {}

    def use_slurm(self) -> bool:
        return True


def _family(root: Path) -> RuntimeFamily:
    family_root = root / "runners" / "demo"
    family_root.mkdir(parents=True)
    (family_root / "demo.def").write_text("Bootstrap: ubuntu:24.04\n", encoding="utf-8")
    (family_root / "plugin.yaml").write_text(
        "api_version: 1\nid: demo\nversion: '1'\n"
        "runtime:\n  image_artifact: demo.sif\n  definition: demo.def\n"
        "  entrypoint: [bash, run.sh]\n",
        encoding="utf-8",
    )
    return RuntimeFamily(
        "demo",
        "1",
        "demo.def",
        "demo.sif",
        str(root / "images" / "demo.sif"),
        root=family_root,
    )


def _patch_evaluator(monkeypatch, *, status_inputs: dict):
    """Point the one evaluator at a fixed evidence snapshot."""
    from revocompute import runner_readiness as core

    monkeypatch.setattr(core, "diagnose", lambda *_a, **_k: status_inputs["doctor"]())
    monkeypatch.setattr(core, "_build_provenance", lambda *_a: status_inputs["provenance"])
    monkeypatch.setattr(core, "sif_stale", lambda *_a: status_inputs["stale"])
    monkeypatch.setattr(core, "load_validation_identity", status_inputs["identity"])


def _active_sif(root: Path) -> Path:
    active = root / "images" / "demo.sif"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(b"active-sif")
    return active


def test_cli_and_service_evaluation_share_one_verdict(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from revocompute.doctor import DoctorReport

    _family(tmp_path)
    _patch_evaluator(
        monkeypatch,
        status_inputs={
            "doctor": lambda: DoctorReport(()),
            "provenance": {"build_provenance_digest": "sha256:build-current"},
            "stale": False,
            "identity": lambda *_a, **_k: SimpleNamespace(
                plan=SimpleNamespace(digest="sha256:test-current", select=lambda _c: ()),
                configuration_digest="sha256:config-current",
            ),
        },
    )
    _active_sif(tmp_path)

    cli_state = _EnvState(tmp_path)
    server_state = ServerHostPaths(
        server=str(tmp_path / "server"),
        config=str(tmp_path / "config"),
        root=str(tmp_path),
        settings={"RUNNER_SOURCE_ROOT": str(tmp_path / "runners")},
    )

    cli_row = runner_status_snapshot(cli_state, runner="demo", all_runners=False)[0]
    service_row = evaluate_runner_readiness(server_state, "demo")
    fleet_row = evaluate_fleet_readiness(server_state)[0]

    # Same evidence snapshot, same verdict: state, reason, and evidence identity.
    for other in (service_row, fleet_row):
        assert other.status is cli_row.status
        assert other.reason_code == cli_row.reason_code
        assert other.sif_sha256 == cli_row.sif_sha256
        assert other.build_provenance_digest == cli_row.build_provenance_digest
        assert other.receipt_valid == cli_row.receipt_valid
    # NOT_VALIDATED with no receipt: the CLI and the service both say "run a
    # live test", and neither invents a READY.
    assert cli_row.status is RunnerReadinessStatus.NOT_VALIDATED
    assert cli_row.next_action == "live-test"


def test_admission_agrees_with_the_evaluator_on_the_published_payload(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from revocompute.doctor import DoctorReport

    _family(tmp_path)
    _patch_evaluator(
        monkeypatch,
        status_inputs={
            "doctor": lambda: DoctorReport(()),
            "provenance": {"build_provenance_digest": "sha256:build-current"},
            "stale": False,
            "identity": lambda *_a, **_k: SimpleNamespace(
                plan=SimpleNamespace(digest="sha256:test-current", select=lambda _c: ()),
                configuration_digest="sha256:config-current",
            ),
        },
    )
    _active_sif(tmp_path)

    server_state = ServerHostPaths(
        server=str(tmp_path / "server"),
        config=str(tmp_path / "config"),
        root=str(tmp_path),
        settings={"RUNNER_SOURCE_ROOT": str(tmp_path / "runners")},
    )
    evaluated = evaluate_runner_readiness(server_state, "demo")

    # What a deployment publishes is exactly the evaluator's serialization.
    readiness_dir = tmp_path / "server" / "readiness"
    readiness_dir.mkdir(parents=True)
    (readiness_dir / "demo.json").write_text(json.dumps(evaluated.as_dict()), encoding="utf-8")

    admitted = resolve_submission_readiness(tmp_path / "server", "demo")
    assert admitted.status is evaluated.status
    assert admitted.reason_code == evaluated.reason_code
    assert admitted.ready is evaluated.ready


def test_unknown_or_disabled_family_evaluates_not_configured(tmp_path, monkeypatch):
    """An unknown family fails closed instead of reading as a readiness verdict."""
    from types import SimpleNamespace

    from revocompute.doctor import DoctorReport

    _family(tmp_path)
    _patch_evaluator(
        monkeypatch,
        status_inputs={
            "doctor": lambda: DoctorReport(()),
            "provenance": {"build_provenance_digest": "sha256:build-current"},
            "stale": False,
            "identity": lambda *_a, **_k: SimpleNamespace(
                plan=SimpleNamespace(digest="sha256:test-current", select=lambda _c: ()),
                configuration_digest="sha256:config-current",
            ),
        },
    )
    _active_sif(tmp_path)

    server_state = ServerHostPaths(
        server=str(tmp_path / "server"),
        config=str(tmp_path / "config"),
        root=str(tmp_path),
        settings={"RUNNER_SOURCE_ROOT": str(tmp_path / "runners")},
    )
    missing = evaluate_runner_readiness(server_state, "not_a_runner")
    assert missing.status is RunnerReadinessStatus.NOT_CONFIGURED
    assert missing.reason_code == "RUNNER_UNKNOWN"
    assert not missing.ready
