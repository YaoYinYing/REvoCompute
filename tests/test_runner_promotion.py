# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Typed activation and rollback: plan-bound, reconstruable, and reversible.

Activation is the one control-plane transition that changes which artifact a new
submission binds, so these cases drive the real promotion core with fakes for the
expensive receipt validation. They prove that a plan binds the candidate, its
receipt, and the artifact it replaces; that a moved identity is refused rather
than silently activated; that a partial activation leaves an explainable active
identity; and that rollback restores only a control-core-known artifact and never
an arbitrary path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from revocompute import runner_promotion as promotion
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_registry import RuntimeFamily

DEMO_YAML = "api_version: 1\nid: demo\nversion: '1'\nruntime:\n  image_artifact: demo.sif\n  definition: demo.def\n"


def _family(root: Path) -> RuntimeFamily:
    family_root = root / "runners" / "demo"
    family_root.mkdir(parents=True, exist_ok=True)
    (family_root / "demo.def").write_text("Bootstrap: ubuntu\n", encoding="utf-8")
    (family_root / "plugin.yaml").write_text(DEMO_YAML, encoding="utf-8")
    image = root / "images" / "demo.sif"
    image.parent.mkdir(parents=True, exist_ok=True)
    return RuntimeFamily("demo", "1", "demo.def", "demo.sif", str(image), root=family_root)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def host(tmp_path) -> ServerHostPaths:
    return ServerHostPaths(server=str(tmp_path / "server"), config=str(tmp_path / "config"), root=str(tmp_path))


def _install_receipt(monkeypatch, *, valid: bool = True, identity: str = "sha256:receipt",
                     has_build_evidence: bool = True) -> dict:
    """Install the receipt validator, a fixed receipt identity, and build evidence."""
    state = {"valid": valid, "identity": identity}
    monkeypatch.setattr(promotion, "_receipt_validator", lambda: (lambda *_a, **_k: state["valid"]))
    monkeypatch.setattr(promotion, "_receipt_identity_for", lambda *_a, **_k: state["identity"])
    monkeypatch.setattr(promotion, "_evidence_digest", lambda *_a, **_k: "sha256:evidence")
    # A preserved artifact is only a rollback target when it carries build
    # evidence of its own.
    monkeypatch.setattr(promotion, "_is_validated", lambda *_a, **_k: has_build_evidence)
    return state


def _stage(family: RuntimeFamily, data: bytes = b"candidate") -> Path:
    staged = Path(f"{family.slurm_image}.next")
    staged.write_bytes(data)
    return staged


def test_activation_is_refused_without_a_staged_candidate(monkeypatch, host):
    family = _family(host.root and Path(host.server_root()))
    _install_receipt(monkeypatch)
    with pytest.raises(promotion.PromotionError, match="No staged candidate"):
        promotion.plan_promotion(host, family)


def test_activation_is_refused_without_a_valid_receipt(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    _stage(family)
    _install_receipt(monkeypatch, valid=False)
    with pytest.raises(promotion.PromotionError, match="receipt"):
        promotion.plan_promotion(host, family)


def test_a_plan_binds_candidate_receipt_and_previous_identity(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    active = Path(family.slurm_image)
    active.write_bytes(b"active")
    _stage(family, b"candidate")
    _install_receipt(monkeypatch, identity="sha256:receipt-1")

    plan = promotion.plan_promotion(host, family)

    assert plan.candidate_sha256 == _sha256(Path(f"{family.slurm_image}.next"))
    assert plan.previous_active_sha256 == _sha256(active)
    assert plan.receipt_identity == "sha256:receipt-1"
    assert plan.as_dict()["plan_digest"] == plan.plan_digest
    # The plan digest is deterministic for identical inputs.
    assert promotion.plan_promotion(host, family).plan_digest == plan.plan_digest


def test_a_candidate_that_changed_after_planning_is_refused(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    Path(family.slurm_image).write_bytes(b"active")
    _stage(family, b"candidate")
    _install_receipt(monkeypatch)
    plan = promotion.plan_promotion(host, family)

    Path(f"{family.slurm_image}.next").write_bytes(b"tampered")
    with pytest.raises(promotion.StalePromotionError, match="candidate changed"):
        promotion.promote(host, family, plan)
    assert Path(family.slurm_image).read_bytes() == b"active"  # nothing was activated


def test_a_receipt_that_moved_after_planning_is_refused(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    Path(family.slurm_image).write_bytes(b"active")
    _stage(family)
    state = _install_receipt(monkeypatch, identity="sha256:receipt-1")
    plan = promotion.plan_promotion(host, family)

    state["identity"] = "sha256:receipt-2"
    with pytest.raises(promotion.StalePromotionError, match="receipt identity changed"):
        promotion.promote(host, family, plan)


def test_active_artifact_identity_change_is_refused(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    Path(family.slurm_image).write_bytes(b"active")
    _stage(family)
    _install_receipt(monkeypatch)
    plan = promotion.plan_promotion(host, family)

    Path(family.slurm_image).write_bytes(b"someone-else-activated")
    with pytest.raises(promotion.StalePromotionError, match="active artifact changed"):
        promotion.promote(host, family, plan)


def test_evidence_change_is_refused(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    Path(family.slurm_image).write_bytes(b"active")
    _stage(family)
    _install_receipt(monkeypatch)
    plan = promotion.plan_promotion(host, family)

    monkeypatch.setattr(promotion, "_evidence_digest", lambda *_a, **_k: "sha256:moved")
    with pytest.raises(promotion.StalePromotionError, match="evidence changed"):
        promotion.promote(host, family, plan)


def test_activation_is_atomic_and_preserves_the_replaced_artifact(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    active = Path(family.slurm_image)
    active.write_bytes(b"active")
    _stage(family, b"candidate")
    _install_receipt(monkeypatch)

    plan = promotion.plan_promotion(host, family)
    outcome = promotion.promote(host, family, plan)

    assert active.read_bytes() == b"candidate"
    assert active.stat().st_mode & 0o222 == 0  # activated artifact is immutable
    assert not Path(f"{family.slurm_image}.next").exists()
    assert outcome["previous_active_sha256"] == _sha256_from(b"active")
    # The replaced artifact is preserved for rollback, not deleted.
    preserved = promotion.rollback_target(host, family)
    assert preserved is not None and preserved["sha256"] == _sha256_from(b"active")


def test_a_failed_activation_restores_the_previous_artifact(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    active = Path(family.slurm_image)
    active.write_bytes(b"active")
    _stage(family, b"candidate")
    _install_receipt(monkeypatch)
    plan = promotion.plan_promotion(host, family)

    real_replace = promotion.os.replace

    def replace(source, destination):
        if str(source) == f"{family.slurm_image}.next":
            raise OSError("activation failed mid-swap")
        real_replace(source, destination)

    monkeypatch.setattr(promotion.os, "replace", replace)
    with pytest.raises(OSError, match="activation failed"):
        promotion.promote(host, family, plan)
    monkeypatch.undo()

    # The active identity is explainable: the previous artifact is back in place.
    assert active.read_bytes() == b"active"
    assert Path(f"{family.slurm_image}.next").read_bytes() == b"candidate"
    assert not list(tmp_path.rglob("*.promote-backup"))


def test_rollback_is_refused_without_a_preserved_target(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    Path(family.slurm_image).write_bytes(b"active")
    with pytest.raises(promotion.PromotionError, match="No known validated previous artifact"):
        promotion.plan_rollback(host, family)


def test_an_unvalidated_artifact_is_never_preserved_as_a_rollback_target(monkeypatch, host, tmp_path):
    """Rollback may only restore an artifact that carried its own validation."""
    family = _family(tmp_path)
    Path(family.slurm_image).write_bytes(b"unvalidated-active")
    _stage(family, b"candidate")
    _install_receipt(monkeypatch, has_build_evidence=False)

    promotion.promote(host, family, promotion.plan_promotion(host, family))

    assert promotion.rollback_target(host, family) is None


def test_rollback_restores_the_previous_validated_artifact(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    active = Path(family.slurm_image)
    active.write_bytes(b"active")
    _stage(family, b"candidate")
    _install_receipt(monkeypatch)
    promotion.promote(host, family, promotion.plan_promotion(host, family))

    plan = promotion.plan_rollback(host, family)
    outcome = promotion.rollback(host, family, plan)

    assert active.read_bytes() == b"active"
    assert outcome["rolled_back_from"] == _sha256_from(b"candidate")
    assert outcome["active_sha256"] == _sha256_from(b"active")
    # The preserved copy remains available, so the same rollback target is
    # still reachable after the restore.
    assert promotion.rollback_target(host, family)["sha256"] == _sha256_from(b"active")


def test_rollback_refuses_an_arbitrary_or_changed_target(monkeypatch, host, tmp_path):
    family = _family(tmp_path)
    Path(family.slurm_image).write_bytes(b"active")
    _stage(family, b"candidate")
    _install_receipt(monkeypatch)
    promotion.promote(host, family, promotion.plan_promotion(host, family))
    plan = promotion.plan_rollback(host, family)

    # A caller cannot point the plan at an unrelated file: the target must still
    # be the control core's known rollback artifact.
    forged = promotion.RollbackPlan(
        runner_family="demo",
        target_path=str(tmp_path / "evil.sif"),
        target_sha256="sha256:" + "0" * 64,
        target_receipt_identity="",
        current_active_sha256=plan.current_active_sha256,
        plan_digest=plan.plan_digest,
    )
    with pytest.raises(promotion.StalePromotionError):
        promotion.rollback(host, family, forged)

    # A changed active artifact since planning also fails closed.
    promotion.os.chmod(family.slurm_image, 0o644)
    Path(family.slurm_image).write_bytes(b"changed-again")
    with pytest.raises(promotion.StalePromotionError, match="active artifact changed"):
        promotion.rollback(host, family, plan)


def test_the_plan_binds_the_receipt_that_actually_validated_the_candidate(tmp_path):
    """The receipt identity comes from the candidate's own evidence, not a guess."""
    family = _family(tmp_path)
    staged = _stage(family, b"candidate")
    digest = hashlib.sha256(staged.read_bytes()).hexdigest()
    root = tmp_path / "images" / "evidence" / "demo"
    root.mkdir(parents=True)
    identity = {
        "build_provenance_digest": "sha256:build",
        "runtime_bundle_sha256": None,
        "test_definition_digest": "sha256:test",
        "configuration_digest": "sha256:config",
        "execution_uid": 1000,
        "execution_gid": 1000,
        "scheduler_user": "runner",
    }
    (root / f"{digest}.abc.receipt.json").write_text(
        json.dumps({**identity, "runner_family": "demo", "sif_sha256": "sha256:" + digest}), encoding="utf-8"
    )

    resolved = promotion._receipt_identity_for(family, staged)
    assert resolved is not None

    # A receipt belonging to another family is not this candidate's validation.
    (root / f"{digest}.abc.receipt.json").write_text(
        json.dumps({**identity, "runner_family": "other", "sif_sha256": "sha256:" + digest}), encoding="utf-8"
    )
    assert promotion._receipt_identity_for(family, staged) is None

    # No receipt at all is not a resolved identity either.
    (root / f"{digest}.abc.receipt.json").unlink()
    assert promotion._receipt_identity_for(family, staged) is None


def _sha256_from(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()

