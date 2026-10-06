# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Typed Runner activation and rollback, planned and verified before it runs.

Activation is the one control-plane transition that changes which artifact a new
submission will bind, so it is treated as an atomic, plan-bound operation rather
than a file move:

* the plan binds the candidate's content identity, the receipt that validated
  it, the identity of the artifact it replaces, and the evidence digest the plan
  was computed against;
* execution re-verifies that binding, so a candidate, receipt, or evidence
  identity that changed between planning and execution is refused rather than
  silently activated;
* the replaced artifact is preserved as a *known validated* rollback target
  before it is overwritten, so a rollback always has a concrete, provenance-carrying
  artifact to restore and never accepts an arbitrary filesystem path;
* neither operation touches already-running scientific Tasks: activation
  applies to later submissions only.

This is deliberately narrow.  It restores exactly one previous validated
artifact; it is not an artifact browser, and it does not invent a generic
version store.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from revocompute.artifact_evidence import read_artifact_evidence, _RECEIPT_IDENTITY_FIELDS
from revocompute.runner_host import HostPaths
from revocompute.runner_registry import RegistryError
from revocompute.serialization import canonical_digest, sha256_file


class PromotionError(RegistryError):
    """An activation or rollback was refused; the message is operator-facing."""


class StalePromotionError(PromotionError):
    """The artifact, receipt, or evidence identity moved between plan and execute."""


@dataclass(frozen=True, slots=True)
class PromotionPlan:
    """What an activation will do, bound to the identities it was computed from."""

    runner_family: str
    candidate_path: str
    candidate_sha256: str
    #: The identity of the artifact the candidate replaces ("" when none is active).
    previous_active_sha256: str
    previous_active_path: str
    #: The live-test identity that validated the candidate.
    receipt_identity: str
    #: The evidence snapshot the plan was computed against.
    evidence_digest: str
    plan_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "runner_family": self.runner_family,
            "candidate_sha256": self.candidate_sha256,
            "previous_active_sha256": self.previous_active_sha256 or None,
            "receipt_identity": self.receipt_identity,
            "evidence_digest": self.evidence_digest,
            "plan_digest": self.plan_digest,
        }


@dataclass(frozen=True, slots=True)
class RollbackPlan:
    """What a rollback will restore, bound to current and target identities."""

    runner_family: str
    target_path: str
    target_sha256: str
    target_receipt_identity: str
    current_active_sha256: str
    plan_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "runner_family": self.runner_family,
            "target_sha256": self.target_sha256,
            "current_active_sha256": self.current_active_sha256 or None,
            "plan_digest": self.plan_digest,
        }


def _staged_path(family) -> Path:
    return Path(f"{family.slurm_image}.next")


def _rollback_root(family) -> Path:
    return Path(family.slurm_image).parent / ".rollback" / family.name


def _rollback_pointer(family) -> Path:
    return _rollback_root(family) / "current.json"


def _receipt_validator():
    from revocompute.runner_live_test import candidate_receipt_valid

    return candidate_receipt_valid


def _receipt_identity_for(family, artifact: Path) -> str | None:
    """The identity of the live-test receipt covering ``artifact``, if one exists.

    Read from the artifact's own receipt evidence rather than re-deriving it, so
    the plan binds the validation that actually ran.
    """
    sha256 = sha256_file(artifact)
    root = Path(family.slurm_image).parent / "evidence" / family.name
    digest = sha256.removeprefix("sha256:")
    matches = sorted(root.glob(f"{digest}.*.receipt.json"))
    if len(matches) != 1:
        return None
    try:
        value = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("runner_family") != family.name:
        return None
    return canonical_digest({field: value.get(field) for field in _RECEIPT_IDENTITY_FIELDS})


def _evidence_digest(state: HostPaths, family) -> str:
    from revocompute.runner_readiness import resolve_runner_readiness

    readiness = resolve_runner_readiness(state, family)
    return canonical_digest(
        {
            "family": readiness.runner_family,
            "sif_sha256": readiness.sif_sha256,
            "build_provenance_digest": readiness.build_provenance_digest,
            "runtime_bundle_sha256": readiness.runtime_bundle_sha256,
            "receipt_tested_at": readiness.receipt_tested_at,
        }
    )


def _is_validated(family, artifact: Path) -> bool:
    """Whether an artifact carries build evidence of its own.

    A preserved copy is only a rollback target when it is known validated, so an
    artifact with no evidence is never offered as one.
    """
    return read_artifact_evidence(family, artifact, "build")[1] is not None


def _preserve_previous(family, active: Path) -> str:
    """Copy the artifact being replaced into the rollback store, immutably.

    A preserved copy is only a rollback target when it is itself *known
    validated*: it must carry build evidence and a live-test receipt for its own
    content.  An artifact with no receipt is not preserved as a target, so
    rollback can never restore an unvalidated file.
    """
    digest = sha256_file(active)
    if not _is_validated(family, active):
        return ""
    destination = _rollback_root(family) / f"{digest.removeprefix('sha256:')}.sif"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        shutil.copy2(active, destination)
        os.chmod(destination, 0o444)
    return digest


def plan_promotion(state: HostPaths, family) -> PromotionPlan:
    """Plan the activation of a staged candidate, or refuse with a reason.

    Nothing is staged, the candidate has no valid receipt, or the receipt covers
    a different identity: each is a refusal, not an approximation.
    """
    staged = _staged_path(family)
    if not staged.is_file():
        raise PromotionError(f"No staged candidate to activate for {family.name}")
    if not _receipt_validator()(state, family):
        raise PromotionError(f"Staged candidate has no valid live-test receipt: {family.name}")
    candidate_sha256, _ = read_artifact_evidence(family, staged, "build")
    active = Path(family.slurm_image)
    previous = sha256_file(active) if active.is_file() else ""
    receipt_identity = _receipt_identity_for(family, staged) or ""
    if not receipt_identity:
        raise PromotionError(f"Staged candidate receipt identity cannot be resolved: {family.name}")
    evidence = _evidence_digest(state, family)
    digest = canonical_digest(
        {
            "action": "promote",
            "runner_family": family.name,
            "candidate_sha256": candidate_sha256,
            "previous_active_sha256": previous,
            "receipt_identity": receipt_identity,
            "evidence_digest": evidence,
        }
    )
    return PromotionPlan(
        runner_family=family.name,
        candidate_path=str(staged),
        candidate_sha256=candidate_sha256,
        previous_active_sha256=previous,
        previous_active_path=str(active),
        receipt_identity=receipt_identity,
        evidence_digest=evidence,
        plan_digest=digest,
    )


def verify_promotion(plan: PromotionPlan, state: HostPaths, family) -> None:
    """Re-check the plan's binding against current artifacts.  Stale means refused."""
    staged = _staged_path(family)
    if not staged.is_file():
        raise StalePromotionError("The staged candidate is gone; replan before activating")
    if sha256_file(staged) != plan.candidate_sha256:
        raise StalePromotionError("The candidate changed since it was planned; replan before activating")
    if not _receipt_validator()(state, family):
        raise StalePromotionError("The candidate's live-test receipt is no longer valid; replan before activating")
    if (_receipt_identity_for(family, staged) or "") != plan.receipt_identity:
        raise StalePromotionError("The candidate's receipt identity changed; replan before activating")
    active = Path(family.slurm_image)
    current = sha256_file(active) if active.is_file() else ""
    if current != plan.previous_active_sha256:
        raise StalePromotionError("The active artifact changed since it was planned; replan before activating")
    if _evidence_digest(state, family) != plan.evidence_digest:
        raise StalePromotionError("Runner evidence changed since it was planned; replan before activating")


def promote(state: HostPaths, family, plan: PromotionPlan) -> dict[str, Any]:
    """Activate the planned candidate atomically, preserving the replaced artifact.

    The replaced artifact is preserved *before* the swap, so an activation that
    fails part-way still leaves a reconstruable active identity: either the new
    candidate is in place, or the previous artifact is restored from its
    immutable copy.
    """
    verify_promotion(plan, state, family)
    staged = Path(plan.candidate_path)
    active = Path(family.slurm_image)
    backup = f"{family.slurm_image}.promote-backup"
    if os.path.lexists(backup):
        raise PromotionError(f"Stale promotion backup requires operator recovery: {backup}")
    preserved = _preserve_previous(family, active) if active.is_file() else ""
    if os.stat(staged).st_mode & 0o222:
        os.chmod(staged, 0o444)
    had_active = active.is_file()
    if had_active:
        os.replace(active, backup)
    try:
        os.replace(staged, active)
    except Exception:
        if had_active and os.path.isfile(backup):
            os.replace(backup, active)
        raise
    if os.path.isfile(backup):
        os.remove(backup)
    os.chmod(active, 0o444)
    if os.path.isfile(f"{staged}.source"):
        os.remove(f"{staged}.source")
    _write_pointer(family, active, plan.receipt_identity, preserved)
    return {
        "runner_family": family.name,
        "active_sha256": sha256_file(active),
        "previous_active_sha256": preserved or None,
        "receipt_identity": plan.receipt_identity,
    }


def _write_pointer(family, active: Path, receipt_identity: str, previous_sha256: str) -> None:
    """Record what is active and what can be rolled back to."""
    root = _rollback_root(family)
    root.mkdir(parents=True, exist_ok=True)
    preserved = _rollback_root(family) / f"{previous_sha256.removeprefix('sha256:')}.sif" if previous_sha256 else None
    payload: dict[str, Any] = {
        "runner_family": family.name,
        "active_sha256": sha256_file(active),
        "active_receipt_identity": receipt_identity,
        "previous_sha256": previous_sha256 or None,
        "previous_receipt_identity": _receipt_identity_for(family, preserved) if preserved else None,
    }
    pointer = _rollback_pointer(family)
    temp = pointer.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, pointer)


def _read_pointer(family) -> dict[str, Any] | None:
    try:
        value = json.loads(_rollback_pointer(family).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("runner_family") == family.name else None


def rollback_target(state: HostPaths, family) -> dict[str, Any] | None:
    """The immediately previous known-validated artifact, if one is preserved."""
    pointer = _read_pointer(family)
    if not pointer or not pointer.get("previous_sha256"):
        return None
    sha256 = str(pointer["previous_sha256"])
    path = _rollback_root(family) / f"{sha256.removeprefix('sha256:')}.sif"
    if not path.is_file():
        return None
    return {
        "path": str(path),
        "sha256": sha256,
        "receipt_identity": pointer.get("previous_receipt_identity"),
    }


def plan_rollback(state: HostPaths, family) -> RollbackPlan:
    """Plan restoring the preserved previous artifact, or refuse with a reason."""
    target = rollback_target(state, family)
    if target is None:
        raise PromotionError(f"No known validated previous artifact is available for {family.name}")
    active = Path(family.slurm_image)
    current = sha256_file(active) if active.is_file() else ""
    if current == target["sha256"]:
        raise PromotionError(f"{family.name} is already running the rollback target")
    digest = canonical_digest(
        {
            "action": "rollback",
            "runner_family": family.name,
            "target_sha256": target["sha256"],
            "current_active_sha256": current,
        }
    )
    return RollbackPlan(
        runner_family=family.name,
        target_path=target["path"],
        target_sha256=target["sha256"],
        target_receipt_identity=str(target.get("receipt_identity") or ""),
        current_active_sha256=current,
        plan_digest=digest,
    )


def verify_rollback(plan: RollbackPlan, state: HostPaths, family) -> None:
    """Re-check a rollback plan against the artifacts it names."""
    target = Path(plan.target_path)
    if not target.is_file():
        raise StalePromotionError("The rollback target is gone; replan before restoring")
    if sha256_file(target) != plan.target_sha256:
        raise StalePromotionError("The rollback target changed; replan before restoring")
    active = Path(family.slurm_image)
    current = sha256_file(active) if active.is_file() else ""
    if current != plan.current_active_sha256:
        raise StalePromotionError("The active artifact changed; replan before restoring")
    # The target must still be the control core's known rollback artifact, not an
    # arbitrary path a caller supplied.
    known = rollback_target(state, family)
    if known is None or known["sha256"] != plan.target_sha256:
        raise StalePromotionError("The rollback target is no longer the known previous artifact")


def rollback(state: HostPaths, family, plan: RollbackPlan) -> dict[str, Any]:
    """Restore the planned previous artifact for later submissions."""
    verify_rollback(plan, state, family)
    active = Path(family.slurm_image)
    target = Path(plan.target_path)
    # The preserved copy stays immutable; the active path receives a fresh copy
    # so a later rollback still has the same known target available.
    working = active.with_suffix(".rollback-next")
    shutil.copy2(target, working)
    os.chmod(working, 0o444)
    backup = f"{family.slurm_image}.rollback-backup"
    if os.path.lexists(backup):
        raise PromotionError(f"Stale rollback backup requires operator recovery: {backup}")
    had_active = active.is_file()
    if had_active:
        os.replace(active, backup)
    try:
        os.replace(working, active)
    except Exception:
        if had_active and os.path.isfile(backup):
            os.replace(backup, active)
        raise
    if os.path.isfile(backup):
        os.remove(backup)
    after = sha256_file(active)
    if after != plan.target_sha256:
        raise PromotionError("Rollback did not restore the planned artifact identity")
    return {
        "runner_family": family.name,
        "active_sha256": after,
        "rolled_back_from": plan.current_active_sha256 or None,
        "receipt_identity": plan.target_receipt_identity or None,
    }


__all__ = [
    "PromotionError",
    "PromotionPlan",
    "RollbackPlan",
    "StalePromotionError",
    "plan_promotion",
    "plan_rollback",
    "promote",
    "rollback",
    "rollback_target",
    "verify_promotion",
    "verify_rollback",
]
