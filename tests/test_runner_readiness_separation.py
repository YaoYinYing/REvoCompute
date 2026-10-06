# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Readiness, capacity, and access stay physically separate.

The control plane must never collapse them into one "available" flag: a family
can be READY while no GPU is free, or VALIDATION_STALE while four GPUs sit idle,
and neither fact may rewrite the other.  These cases pin that invariant against
the admin projection and the underlying evaluator.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from revocompute.access_control import AccessPolicy
from revocompute.infrastructure import CapacityStatus, InfrastructureStatus
from revocompute.runner_admin_view import access_view, capacity_view, fleet_view
from revocompute.runner_host import ServerHostPaths
from revocompute.runner_readiness import RunnerReadiness, evaluate_runner_readiness
from revocompute.runner_registry import RuntimeFamily


def _infrastructure(*, capacity: str, status: str = "READY") -> dict:
    return {
        "status": status,
        "summary": {
            "infrastructure": {"label": "Infrastructure", "status": status, "stale": False},
            "scheduler": {"label": "Scheduler", "status": status, "stale": False, "capacity": capacity},
            "gpu": {"label": "GPU", "status": status, "stale": False, "capacity": capacity},
        },
    }


def test_capacity_is_reported_independently_of_readiness():
    busy = capacity_view(_infrastructure(capacity=CapacityStatus.BUSY.value))
    idle = capacity_view(_infrastructure(capacity=CapacityStatus.AVAILABLE.value))
    unknown = capacity_view(None)

    assert busy == {"available": False, "reason": "scheduler_busy"}
    assert idle == {"available": True, "reason": "scheduler_available"}
    assert unknown == {"available": None, "reason": "infrastructure_evidence_unavailable"}


def test_open_family_access_is_not_a_denial():
    assert access_view(None, database=None, user_id=None) == {
        "restricted": False,
        "granted": True,
        "policy_id": None,
    }


def test_restricted_family_access_reports_entitlement_without_readiness():
    policy = AccessPolicy("af_noncommercial", "AlphaFold", "Restricted", ("af_terms",), True)

    class _Db:
        def get_effective_entitlements(self, _user_id):
            return {"af_terms"}

    class _MissingDb:
        def get_effective_entitlements(self, _user_id):
            return set()

    assert access_view(policy, _Db(), 7) == {
        "restricted": True,
        "granted": True,
        "policy_id": "af_noncommercial",
        "missing_entitlements": [],
    }
    assert access_view(policy, _MissingDb(), 7)["granted"] is False
    assert access_view(policy, _MissingDb(), None)["reason"] == "unauthenticated"


def _family(root: Path, name: str, *, restricted: bool = False) -> RuntimeFamily:
    family_root = root / "runners" / name
    family_root.mkdir(parents=True)
    (family_root / "runner.def").write_text("Bootstrap: ubuntu:24.04\n", encoding="utf-8")
    policy_fields = "  access_policy: af\n" if restricted else ""
    manifest = (
        "api_version: 1\nid: %s\nversion: '1'\n"
        "runtime:\n  image_artifact: %s.sif\n  definition: runner.def\n"
        "  entrypoint: [bash, run.sh]\n%s" % (name, name, policy_fields)
    )
    if restricted:
        # Access policies live under the Runner tree's common/policy, relative
        # to the plugin root (the family directory's parent).
        (root / "runners" / "common" / "policy").mkdir(parents=True, exist_ok=True)
        (root / "runners" / "common" / "policy" / "af.yaml").write_text(
            "id: af\nlabel: AlphaFold\ndescription: Restricted\nrequires: [af_terms]\n"
            "match: all\nrequestable: true\n",
            encoding="utf-8",
        )
        manifest += "access_policies: [common/policy/af.yaml]\ncontributions:\n  access_policies: [af]\n"
    (family_root / "plugin.yaml").write_text(manifest, encoding="utf-8")
    return RuntimeFamily(
        name, "1", "runner.def", f"{name}.sif", str(root / "images" / f"{name}.sif"), root=family_root
    )


def test_fleet_view_keeps_the_three_states_distinct(tmp_path, monkeypatch):
    from revocompute import runner_readiness as core

    _family(tmp_path, "openrunner")
    _family(tmp_path, "restrictedrunner", restricted=True)

    # Not-ready readiness, while capacity is AVAILABLE and access is granted.
    monkeypatch.setattr(core, "diagnose", lambda *_a, **_k: SimpleNamespace(ok=False, diagnostics=()))
    state = ServerHostPaths(
        server=str(tmp_path / "server"),
        config=str(tmp_path / "config"),
        root=str(tmp_path),
        settings={"RUNNER_SOURCE_ROOT": str(tmp_path / "runners")},
    )

    class _Db:
        def get_effective_entitlements(self, _user_id):
            return {"af_terms"}

    rows = fleet_view(
        state,
        infrastructure=_infrastructure(capacity=CapacityStatus.AVAILABLE.value),
        database=_Db(),
        user_id=1,
    )

    assert [row["runner_family"] for row in rows] == ["openrunner", "restrictedrunner"]
    for row in rows:
        assert row["readiness"]["status"] != "READY"  # doctor failed
        assert row["capacity"]["available"] is True  # capacity independent
    assert rows[0]["access"] == {"restricted": False, "granted": True, "policy_id": None}
    assert rows[1]["access"]["restricted"] is True and rows[1]["access"]["granted"] is True


def test_capacity_change_does_not_mutate_readiness(tmp_path, monkeypatch):
    from revocompute import runner_readiness as core

    _family(tmp_path, "demo")
    monkeypatch.setattr(core, "diagnose", lambda *_a, **_k: SimpleNamespace(ok=False, diagnostics=()))
    state = ServerHostPaths(
        server=str(tmp_path / "server"),
        config=str(tmp_path / "config"),
        root=str(tmp_path),
        settings={"RUNNER_SOURCE_ROOT": str(tmp_path / "runners")},
    )

    ready_eval = evaluate_runner_readiness(state, "demo")
    for capacity in (CapacityStatus.AVAILABLE, CapacityStatus.BUSY, CapacityStatus.UNKNOWN):
        rows = fleet_view(state, infrastructure=_infrastructure(capacity=capacity.value))
        assert rows[0]["readiness"]["status"] == ready_eval.status
        assert rows[0]["readiness"]["reason_code"] == ready_eval.reason_code


def test_infrastructure_status_change_does_not_rewrite_runner_readiness(tmp_path, monkeypatch):
    from revocompute import runner_readiness as core

    _family(tmp_path, "demo")
    monkeypatch.setattr(core, "diagnose", lambda *_a, **_k: SimpleNamespace(ok=False, diagnostics=()))
    state = ServerHostPaths(
        server=str(tmp_path / "server"),
        config=str(tmp_path / "config"),
        root=str(tmp_path),
        settings={"RUNNER_SOURCE_ROOT": str(tmp_path / "runners")},
    )

    baseline = evaluate_runner_readiness(state, "demo").status
    for status in (
        InfrastructureStatus.READY.value,
        InfrastructureStatus.DEGRADED.value,
        InfrastructureStatus.UNAVAILABLE.value,
    ):
        rows = fleet_view(state, infrastructure=_infrastructure(capacity="UNKNOWN", status=status))
        assert rows[0]["readiness"]["status"] == baseline
