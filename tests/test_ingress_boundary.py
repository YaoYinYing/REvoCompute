# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The Core-owned admission vocabulary and the validation receipt.

These are the facts every scientific ingress projects, so they are asserted at
their own boundary: a reason code maps to exactly one phase and one operational
event, the validator revision is content-derived rather than a hand-maintained
constant, a submitted path canonicalizes to one namespace entry, and a receipt
proves the bytes execution will consume.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from revocompute import ingress_security
from revocompute.ingress_security import (
    REASON_CODES,
    Phase,
    canonical_relative_path,
    event_for_code,
    phase_for_code,
    snapshot_mismatch_reason,
    validator_revision,
)

REPO = Path(__file__).resolve().parents[1]


def test_every_reason_code_belongs_to_exactly_one_phase() -> None:
    seen: dict[str, Phase] = {}
    for phase, codes in REASON_CODES.items():
        assert isinstance(phase, Phase)
        assert codes, f"{phase} has no reason codes"
        for code in codes:
            assert code not in seen, f"{code} is claimed by {phase} and {seen.get(code)}"
            seen[code] = phase
    # The vocabulary must not grow into an unbounded enum: it is a bounded set
    # callers switch on, not a message catalogue.
    assert len(seen) <= 32
    expected_event = {
        Phase.SECURITY: "preflight.security_rejected",
        Phase.CONTRACT: "preflight.contract_rejected",
        Phase.ADMISSION: "preflight.admission_denied",
    }
    for code, phase in seen.items():
        assert phase_for_code(code) == phase.value
        assert event_for_code(code) == expected_event[phase]
        # An admission code is never reported as a security rejection: the two
        # mean different things to an operator reading the event stream.
        assert event_for_code(code) != "preflight.security_rejected" or phase is Phase.SECURITY


def test_every_event_the_vocabulary_routes_to_is_a_real_operational_event() -> None:
    """One event scheme: a code routes to an existing operational_events name.

    The admission vocabulary owns reason codes and their phase; it must not mint
    a second event family.  Each routed name is checked against the owning
    module's declared vocabulary, so a rename there breaks here rather than
    silently emitting an event nobody declared.
    """
    from revocompute.operational_events import EVENT_NAMES

    routed = {event_for_code(code) for codes in REASON_CODES.values() for code in codes}
    assert routed
    assert routed <= EVENT_NAMES


def test_every_reason_code_is_a_bounded_token() -> None:
    for codes in REASON_CODES.values():
        for code in codes:
            assert code == code.strip().lower()
            assert len(code) <= 40
            assert code.replace("_", "").isalnum()


def test_an_unlisted_code_falls_back_by_status_not_by_phase_guessing() -> None:
    # A code that is not in the vocabulary is never silently classified as a
    # hostile-bytes security rejection; it degrades to the status-derived
    # default the boundary used before the vocabulary existed.
    assert phase_for_code("brand_new_code") == "contract"
    assert phase_for_code("brand_new_code", http_status=403) == "admission"


def test_validator_revision_is_content_derived_not_a_constant() -> None:
    """The identity tracks the boundary bytes, not a value someone bumps.

    Changing a boundary source must change the revision; that is the whole point
    of deriving it.  Asserted by perturbing the source set rather than by
    re-implementing the digest recipe, so the test describes behavior (revision
    follows content) instead of pinning the helper's internals.
    """
    baseline = validator_revision()
    assert baseline.startswith("sha256:")
    assert baseline == validator_revision()  # stable within one boundary

    monkeypatch = None
    import revocompute.ingress_security as module

    original = module._BOUNDARY_SOURCES
    try:
        module._BOUNDARY_SOURCES = (*original, "input_validators/does_not_exist.py")
        assert validator_revision() == "sha256:unavailable"
        assert validator_revision() != baseline
    finally:
        module._BOUNDARY_SOURCES = original
    assert validator_revision() == baseline


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "../escape.pdb",
        "/etc/passwd",
        "a/../../b.pdb",
        "a//b.pdb",
        "sub/./model.pdb",
        ".hidden.pdb",
        "dir/.hidden/model.pdb",
        "nul\x00byte.pdb",
        "line\nbreak.pdb",
        "del\x7fchar.pdb",
        "%2e%2e/escape.pdb",
        "C:\\windows\\model.pdb",
        "\\\\server\\share\\model.pdb",
        "a" * 300 + ".pdb",
        "/".join(["dir"] * 400) + "/model.pdb",
    ],
)
def test_canonical_relative_path_fails_closed_with_a_bounded_code(raw: str) -> None:
    path, reason = canonical_relative_path(raw)
    assert path is None
    assert reason == "input_path_invalid"


def test_canonical_relative_path_sanitizes_to_one_namespace_entry() -> None:
    assert canonical_relative_path("a b.pdb") == ("a_b.pdb", None)
    assert canonical_relative_path("sub\\a.pdb") == ("sub/a.pdb", None)
    assert canonical_relative_path("a  b.pdb") == ("a_b.pdb", None)
    # A leading/trailing-space name and its stripped form are the same entry,
    # so the collision rule sees them as one and not two.
    assert canonical_relative_path("  spaced.pdb  ")[0] == "spaced.pdb"


def test_receipt_proves_the_exact_bytes_and_only_under_the_same_boundary(tmp_path) -> None:
    victim = tmp_path / "input.pdb"
    victim.write_bytes(b"ATOM      1  CA  ALA A   1\n")
    digest = hashlib.sha256(victim.read_bytes()).hexdigest()
    receipt = {
        "sha256": digest,
        "size": victim.stat().st_size,
        "validator_revision": validator_revision(),
    }
    assert snapshot_mismatch_reason(receipt, str(victim)) is None

    # Different bytes: the snapshot is not what was admitted.
    other = tmp_path / "other.pdb"
    other.write_bytes(b"ATOM      1  CA  GLY A   1\n")
    assert snapshot_mismatch_reason(receipt, str(other)) == "input_snapshot_mismatch"

    # Same bytes, but a different validator identity decided: revalidation is
    # not skippable, because "validated" no longer means what it meant.
    stale = {**receipt, "validator_revision": "sha256:0000"}
    assert snapshot_mismatch_reason(stale, str(victim)) == "input_snapshot_mismatch"

    # No receipt at all is not a passing receipt.
    assert snapshot_mismatch_reason(None, str(victim)) == "input_snapshot_mismatch"


def test_receipt_refuses_a_link_instead_of_the_admitted_private_file(tmp_path) -> None:
    target = tmp_path / "real.pdb"
    target.write_bytes(b"ATOM      1  CA  ALA A   1\n")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    receipt = {"sha256": digest, "validator_revision": validator_revision()}

    link = tmp_path / "link.pdb"
    link.symlink_to(target)
    assert snapshot_mismatch_reason(receipt, str(link)) == "input_snapshot_mismatch"

    hard = tmp_path / "hard.pdb"
    os.link(target, hard)
    assert snapshot_mismatch_reason(receipt, str(hard)) == "input_snapshot_mismatch"

    assert snapshot_mismatch_reason(receipt, str(tmp_path / "missing.pdb")) == "input_snapshot_mismatch"


def test_receipt_records_the_decision_it_projects(tmp_path) -> None:
    receipt = ingress_security.ValidationReceipt(
        sha256="c" * 64,
        size=42,
        format="fasta",
        logical_type="sequence_alignment",
        relative_path="query.fasta",
        role="sequence",
    )
    record = receipt.as_record()
    assert record["decision"] == "accepted"
    assert record["reason_code"] is None
    assert record["validator_revision"] == validator_revision()
    assert json.loads(json.dumps(record)) == record


def test_the_admission_codes_the_ingress_surfaces_emit_are_all_in_the_vocabulary() -> None:
    """The reverse direction: every admission code a caller can receive is known.

    Enumerated from the documented ingress surface rather than scraped from
    source, so a code that reaches a client but was never added to the table (and
    would therefore fall back to a status-derived phase) fails here.
    """
    known = {code for codes in REASON_CODES.values() for code in codes}
    ingress_codes = {
        "input_path_invalid",
        "input_namespace_collision",
        "input_format_invalid",
        "input_logical_type_invalid",
        "input_file_count_limit",
        "input_file_size_limit",
        "input_total_size_limit",
        "input_snapshot_mismatch",
        "input_role_binding",
        "input_role_format",
        "input_role_unknown",
        "input_role_cardinality",
        "request_size_limit",
        "workspace_json_invalid",
        "validator_resource_limit",
        "contract_invalid",
        "gpu_credit_exhausted",
        "infrastructure_unavailable",
        "runner_not_ready",
        "admission_denied",
        "admission_limited",
        "admission_unavailable",
    }
    assert ingress_codes <= known
    # One spelling for the exhausted-credit fact, wherever it is reported.
    assert phase_for_code("gpu_credit_exhausted") == "admission"
    assert "credit_exhausted" not in known
