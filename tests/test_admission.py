# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
from pathlib import Path

from revocompute.admission import (
    RunnerReadinessStatus,
    invalidate_submission_attestations,
    resolve_submission_readiness,
)


def test_missing_attestation_fails_closed(tmp_path: Path):
    evidence = resolve_submission_readiness(tmp_path, "demo")
    assert evidence.status is RunnerReadinessStatus.NOT_CONFIGURED
    assert not evidence.ready


def test_attestation_requires_matching_runner_and_ready_status(tmp_path: Path):
    path = tmp_path / "readiness"
    path.mkdir()
    (path / "demo.json").write_text(
        json.dumps({"runner_family": "demo", "status": "READY", "ready": True, "reason_code": "READY"}),
        encoding="utf-8",
    )
    evidence = resolve_submission_readiness(tmp_path, "demo")
    assert evidence.status is RunnerReadinessStatus.READY
    assert evidence.ready

    (path / "demo.json").write_text(json.dumps({"runner_family": "other", "status": "READY", "ready": True}), encoding="utf-8")
    evidence = resolve_submission_readiness(tmp_path, "demo")
    assert evidence.status is RunnerReadinessStatus.NOT_CONFIGURED
    assert not evidence.ready


def test_resource_policy_invalidation_removes_published_evidence(tmp_path: Path):
    path = tmp_path / "readiness"
    path.mkdir()
    (path / "demo.json").write_text("{}", encoding="utf-8")
    invalidate_submission_attestations(tmp_path)
    assert not (path / "demo.json").exists()


def test_resource_policy_invalidation_can_target_runner(tmp_path: Path):
    path = tmp_path / "readiness"
    path.mkdir()
    (path / "gremlin.json").write_text("{}", encoding="utf-8")
    (path / "esm.json").write_text("{}", encoding="utf-8")

    invalidate_submission_attestations(tmp_path, {"gremlin"})

    assert not (path / "gremlin.json").exists()
    assert (path / "esm.json").exists()
