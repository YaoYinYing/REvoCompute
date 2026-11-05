# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Source-only acceptance for Boltz-2: merge grants no readiness or admission.

These tests use the real discovered family and the canonical readiness/admission
functions. Model assets are absent, no SIF or live-test receipt exists, and the
deployment enables only Boltz-1; merging the family source must not change any of
that, and a receipt for another build identity must not be inherited.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from revocompute.admission import (
    RunnerReadinessStatus,
    resolve_submission_readiness,
    submission_admission,
)
from revocompute.live_tests import sha256_file
from revocompute.runner_live_test import TaskResourceSnapshot, ValidationIdentity
from revocompute.runner_readiness import evaluate_runner_readiness, resolve_runner_readiness
from revocompute.runner_registry import load_plugin_families
from revocompute.doctor import DoctorReport

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "docker" / "runners"
ASSET_ROOT = Path("/mnt/db/weights/boltz2")


class _State:
    """The deployment fields the registry, readiness, and admission read."""

    def __init__(self, root: Path, enabled: str):
        self.root = root
        self.enabled = enabled

    def server_dir(self) -> str:
        return str(self.root / "server")

    def get(self, key: str) -> str:
        if key == "RUNNER_SOURCE_ROOT":
            return str(RUNNERS)
        if key == "ENABLED_TASKRUNNERS":
            return self.enabled
        return ""


def _boltz2_family(tmp_path: Path):
    family = next(item for item in load_plugin_families(RUNNERS) if item.name == "boltz2")
    return replace(family, slurm_image=str(tmp_path / "images" / "boltz2_v1.sif"))


def test_merge_does_not_enable_boltz2(tmp_path: Path) -> None:
    """Discovery finds the family; the deployment still enables only Boltz-1."""
    state = _State(tmp_path, enabled="boltz")
    assert _boltz2_family(tmp_path).build_inputs

    result = evaluate_runner_readiness(state, "boltz2")

    assert result.status is RunnerReadinessStatus.NOT_CONFIGURED
    assert result.reason_code == "RUNNER_UNKNOWN"
    assert result.ready is False


def test_enabled_boltz2_without_assets_or_receipt_cannot_be_ready_or_admitted(tmp_path: Path) -> None:
    if ASSET_ROOT.exists():
        pytest.skip("assets are provisioned; the source-only premise does not apply")
    state = _State(tmp_path, enabled="boltz,boltz2")

    result = evaluate_runner_readiness(state, "boltz2")

    assert result.status is RunnerReadinessStatus.NOT_BUILT
    assert result.reason_code == "SIF_MISSING"
    assert result.next_action == "build-sif"
    assert result.ready is False

    evidence = resolve_submission_readiness(state.server_dir(), "boltz2")
    assert evidence.ready is False
    assert evidence.reason_code == "RUNNER_UNAVAILABLE"
    assert evidence.accepts("boltz2_predict") is False
    assert evidence.accepts("boltz2_affinity") is False

    managed = SimpleNamespace(slurm_enabled=lambda: True)
    admission = submission_admission(state.server_dir(), "boltz2", manage_db=managed)
    assert admission is not None
    assert admission.ready is False
    assert admission.reason_code == "RUNNER_UNAVAILABLE"
    assert admission.accepts("boltz2_predict") is False


def test_a_receipt_for_another_build_identity_is_not_inherited(tmp_path: Path, monkeypatch) -> None:
    state = _State(tmp_path, enabled="boltz,boltz2")
    family = _boltz2_family(tmp_path)
    active = Path(family.slurm_image)
    active.parent.mkdir(parents=True)
    active.write_bytes(b"active-boltz2-sif")
    plan = SimpleNamespace(
        digest="sha256:test-current",
        select=lambda collection: (
            SimpleNamespace(id="boltz2-structure"),
            SimpleNamespace(id="boltz2-affinity"),
        )
        if collection == "smoke"
        else (),
        omitted=(),
    )
    monkeypatch.setattr("revocompute.runner_readiness.diagnose", lambda *_a, **_k: DoctorReport(()))
    monkeypatch.setattr(
        "revocompute.runner_readiness._build_provenance",
        lambda *_a, **_k: {
            "build_provenance_digest": "sha256:build-current",
            "apptainer_version": "apptainer version 1.4.5",
        },
    )
    monkeypatch.setattr("revocompute.runner_readiness.sif_stale", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "revocompute.runner_readiness.load_validation_identity",
        lambda *_a, **_k: ValidationIdentity(
            plan,
            "sha256:config-current",
            (TaskResourceSnapshot("boltz2_predict", None, ()),),
        ),
    )
    old_receipt = {
        "receipt_contract_version": 2,
        "runner_family": "boltz2",
        "passed": True,
        "ended_at": "2026-11-01T12:00:00+00:00",
        "sif_sha256": sha256_file(active),
        "build_provenance_digest": "sha256:build-previous",
        "test_definition_digest": "sha256:test-current",
        "configuration_digest": "sha256:config-current",
        "cases": [
            {"case_id": "boltz2-structure", "passed": True},
            {"case_id": "boltz2-affinity", "passed": True},
        ],
    }
    receipt_path = active.parent / "evidence" / "boltz2" / "previous.receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(old_receipt), encoding="utf-8")

    result = resolve_runner_readiness(state, family)

    assert result.status is RunnerReadinessStatus.NOT_VALIDATED
    assert result.reason_code == "RECEIPT_MISSING"
    assert result.ready is False
    assert result.receipt_exists is False
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == old_receipt
