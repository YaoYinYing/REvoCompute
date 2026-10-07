# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The per-Runner admin projection: readiness beside capacity and access.

Three states that must never be collapsed into one "available" flag:

* **readiness** — whether the deployed family has current, valid evidence for a
  new submission (the derived six-state verdict; this module never sets it);
* **capacity** — transient execution availability (scheduler/GPU occupancy),
  which changes without changing readiness;
* **access** — whether the calling user could submit to a restricted family,
  which also changes without changing readiness.

Infrastructure readiness is a fourth, separate state owned by
``revocompute.infrastructure`` and only referenced here.
"""

from __future__ import annotations

from typing import Any

from revocompute.access_control import AccessPolicy, load_policy_documents, resolve_policy
from revocompute.runner_host import HostPaths
from revocompute.runner_readiness import (
    RunnerReadiness,
    load_instance_families,
    resolve_runner_readiness,
)
from revocompute.runner_registry import deployment_plugin_root, runner_enabled

#: Infrastructure summary groups whose ``capacity`` field describes transient
#: execution availability rather than whether a family can accept work.
_CAPACITY_GROUPS = ("scheduler", "gpu")


def _family_access_policies(state: HostPaths) -> dict[str, AccessPolicy | None]:
    """Resolve each deployed family's declared access policy, if any.

    The policy reference lives in the plugin's ``runtime.access_policy`` and the
    document under the family tree's ``common/policy``, so the admin view resolves
    it from the same tree the evaluator reads — never from a second configuration
    source.
    """
    from pathlib import Path

    from revocompute.plugins import PluginManager

    root = deployment_plugin_root(state)
    resolved: dict[str, AccessPolicy | None] = {}
    for manifest in PluginManager().discover(root):
        policy_id = (manifest.runtime or {}).get("access_policy")
        if not policy_id:
            resolved[manifest.id] = None
            continue
        documents: dict[str, AccessPolicy] = {}
        refs = manifest.access_policies
        if isinstance(refs, str):
            refs = (refs,)
        for ref in refs:
            documents.update(load_policy_documents(manifest.path.parent / Path(str(ref))))
        resolved[manifest.id] = resolve_policy(str(policy_id), documents) if policy_id in documents else None
    return resolved



def capacity_view(infrastructure: dict[str, Any] | None) -> dict[str, Any]:
    """Transient capacity, read from infrastructure evidence but never merged with readiness."""
    if not infrastructure:
        return {"available": None, "reason": "infrastructure_evidence_unavailable"}
    summary = infrastructure.get("summary") or {}
    for key in _CAPACITY_GROUPS:
        group = summary.get(key)
        if isinstance(group, dict) and isinstance(group.get("capacity"), str):
            capacity = group["capacity"]
            return {"available": capacity == "AVAILABLE", "reason": f"{key}_{capacity.lower()}"}
    return {"available": None, "reason": "capacity_unknown"}


def access_view(policy: AccessPolicy | None, database: Any, user_id: int | None) -> dict[str, Any]:
    """Whether the given user may submit to this family, as a separate field.

    A family with no policy is open, so the field never reads as a denial.  A
    restricted family reports entitlement state without touching readiness.
    """
    if policy is None:
        return {"restricted": False, "granted": True, "policy_id": None}
    if user_id is None:
        return {"restricted": True, "granted": False, "policy_id": policy.id, "reason": "unauthenticated"}
    effective = database.get_effective_entitlements(user_id)
    missing = [item for item in policy.requires if item not in effective]
    return {"restricted": True, "granted": not missing, "policy_id": policy.id, "missing_entitlements": missing}


def _readiness_view(row: RunnerReadiness) -> dict[str, Any]:
    return {
        "status": row.status.value,
        "reason_code": row.reason_code,
        "message": row.message,
        "next_action": row.next_action,
        "evidence": {
            "sif_path": row.sif_path,
            "sif_exists": row.sif_exists,
            "sif_sha256": row.sif_sha256,
            "build_provenance_current": row.build_provenance_current,
            "build_provenance_digest": row.build_provenance_digest,
            "runtime_bundle_sha256": row.runtime_bundle_sha256,
            "receipt_exists": row.receipt_exists,
            "receipt_valid": row.receipt_valid,
            "receipt_tested_at": row.receipt_tested_at,
            "required_smoke_cases": list(row.required_smoke_cases),
            "passed_smoke_cases": list(row.passed_smoke_cases),
            "doctor_ok": row.doctor_ok,
        },
    }


def fleet_view(
    state: HostPaths,
    *,
    infrastructure: dict[str, Any] | None = None,
    database: Any = None,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Every enabled family's admin projection, in deterministic family order.

    Readiness, capacity, and access are computed independently and returned as
    sibling fields, so a family that is READY while no GPU is free, or
    VALIDATION_STALE while GPUs are idle, reports both facts without either one
    rewriting the other.
    """
    capacity = capacity_view(infrastructure)
    policies = _family_access_policies(state)
    rows: list[dict[str, Any]] = []
    for family in sorted(load_instance_families(state), key=lambda item: item.name):
        if not runner_enabled(state, family.name):
            continue
        rows.append(
            {
                "runner_family": family.name,
                "readiness": _readiness_view(resolve_runner_readiness(state, family)),
                "capacity": capacity,
                "access": access_view(policies.get(family.name), database, user_id),
            }
        )
    return rows


__all__ = ["RunnerReadiness", "access_view", "capacity_view", "fleet_view"]
