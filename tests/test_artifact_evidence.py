# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "run"
if str(RUN_DIR) not in sys.path:
    sys.path.insert(0, str(RUN_DIR))

from revocompute.live_tests import sha256_file  # noqa: E402
from revocompute_ctl.artifact_evidence import read_artifact_evidence, write_artifact_evidence  # noqa: E402
from revocompute_ctl.registry import RuntimeFamily  # noqa: E402


def _family(tmp_path: Path, name: str) -> RuntimeFamily:
    return RuntimeFamily(name, "1", f"{name}.def", f"{name}.sif", str(tmp_path / f"{name}.sif"))


def test_active_and_candidate_evidence_are_bound_to_exact_artifact_and_family(tmp_path):
    family = _family(tmp_path, "demo")
    other = _family(tmp_path, "other")
    active = Path(family.slurm_image)
    candidate = Path(f"{family.slurm_image}.next")
    active.write_bytes(b"active-A")
    candidate.write_bytes(b"candidate-B")
    active_sha = sha256_file(active)
    candidate_sha = sha256_file(candidate)
    active_path = write_artifact_evidence(family, active_sha, "receipt", {"marker": "A"})
    candidate_path = write_artifact_evidence(family, candidate_sha, "receipt", {"marker": "B"})

    assert active_path != candidate_path
    assert read_artifact_evidence(family, active, "receipt")[1]["marker"] == "A"
    assert read_artifact_evidence(family, candidate, "receipt")[1]["marker"] == "B"
    assert read_artifact_evidence(other, active, "receipt")[1] is None

    candidate.write_bytes(b"changed-after-validation")
    assert read_artifact_evidence(family, candidate, "receipt")[1] is None
    assert read_artifact_evidence(family, active, "receipt")[1]["marker"] == "A"


def test_one_artifact_keeps_independent_receipts_for_distinct_contracts(tmp_path):
    family = _family(tmp_path, "demo")
    artifact = Path(family.slurm_image)
    artifact.write_bytes(b"same-sif")
    sif_sha256 = sha256_file(artifact)
    old = {"configuration_digest": "sha256:old", "marker": "old"}
    new = {"configuration_digest": "sha256:new", "marker": "new"}

    old_path = write_artifact_evidence(family, sif_sha256, "receipt", old)
    new_path = write_artifact_evidence(family, sif_sha256, "receipt", new)

    assert old_path != new_path
    assert read_artifact_evidence(family, artifact, "receipt", receipt_identity=old)[1]["marker"] == "old"
    assert read_artifact_evidence(family, artifact, "receipt", receipt_identity=new)[1]["marker"] == "new"


def test_scoped_receipts_accumulate_passed_cases_for_same_contract(tmp_path):
    family = _family(tmp_path, "demo")
    artifact = Path(family.slurm_image)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"sif")
    sif_sha256 = sha256_file(artifact)
    identity = {"test_definition_digest": "test", "configuration_digest": "config", "passed": True}

    write_artifact_evidence(family, sif_sha256, "receipt", {**identity, "cases": [{"case_id": "a", "passed": True}]})
    write_artifact_evidence(family, sif_sha256, "receipt", {**identity, "cases": [{"case_id": "b", "passed": True}]})

    receipt = read_artifact_evidence(family, artifact, "receipt", receipt_identity=identity)[1]
    assert receipt is not None
    assert [case["case_id"] for case in receipt["cases"]] == ["a", "b"]
