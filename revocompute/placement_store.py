# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deployment-owned store for the placement policy document.

Placement policy is deployment-local: it names this site's partitions, QoS,
accounts, and GRES classes.  It is therefore one operator-owned JSON document
beside the Runner tree and the image store, not a column in the admin
configuration database — that database holds the canonical per-task *resource*
vocabulary whose every value is a scalar, and a policy is a typed tree.

The store does exactly three things: read the document, validate a proposed
document against the deployment's allowed Slurm surface, and write it
atomically with a monotonically increasing revision.  It never resolves a
placement and never touches a plan; those belong to
:mod:`revocompute.placement_policy` and to its callers.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from revocompute.placement_policy import PlacementPolicy, PlacementPolicyInvalid
from revocompute.serialization import atomic_write_json

#: A deployment declares a handful of execution classes.  The bound exists so a
#: malformed or hostile document cannot become an unbounded policy read on the
#: dispatch path.
MAX_POLICY_BYTES = 256 * 1024

_DOCUMENT_KEYS = frozenset({"revision", "updated_at", "updated_by_user_id", "classes"})


class PlacementPolicyStoreError(RuntimeError):
    """The stored placement policy could not be read or written."""


def load_placement_policy_document(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read the raw document, or ``{}`` when the deployment declared none.

    An unreadable or malformed document is a hard error rather than an empty
    policy.  Treating a corrupt file as "no classes" would place every stage
    through the unmanaged path while the operator believes a policy is active —
    the failure would then be invisible exactly when it matters.
    """
    target = Path(path)
    if not target.exists():
        return {}
    try:
        raw_bytes = target.read_bytes()
    except OSError as exc:
        raise PlacementPolicyStoreError(f"Placement policy could not be read: {exc}") from exc
    if len(raw_bytes) > MAX_POLICY_BYTES:
        raise PlacementPolicyInvalid(f"Placement policy exceeds {MAX_POLICY_BYTES} bytes")
    try:
        document = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlacementPolicyInvalid(f"Placement policy is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise PlacementPolicyInvalid("Placement policy must be a JSON object")
    unknown = set(document) - _DOCUMENT_KEYS
    if unknown:
        raise PlacementPolicyInvalid(f"Unknown placement policy keys: {sorted(unknown)}")
    return document


def load_placement_policy(
    path: str | os.PathLike[str],
    *,
    allowed_queues: Sequence[str] = (),
) -> PlacementPolicy:
    """The policy in force for this deployment, validated against its surface."""
    document = load_placement_policy_document(path)
    if not document:
        return PlacementPolicy()
    return PlacementPolicy.validate(
        {"classes": document.get("classes", [])},
        allowed_queues=allowed_queues,
        revision=int(document.get("revision") or 0),
        updated_at=float(document.get("updated_at") or 0.0),
        updated_by_user_id=document.get("updated_by_user_id"),
    )


def write_placement_policy(
    path: str | os.PathLike[str],
    raw_classes: Any,
    *,
    allowed_queues: Sequence[str] = (),
    actor_user_id: int | None = None,
    at: float | None = None,
) -> PlacementPolicy:
    """Validate, revision, and atomically store a proposed policy.

    Validation happens before the write and against the *current* allowed
    surface, so a document that names an undeclared partition is refused with
    nothing on disk changed.  The revision is read-modify-written under a file
    lock so two concurrent admin updates cannot both claim the same revision
    number.
    """
    target = Path(path)
    timestamp = time.time() if at is None else at
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = f"{target}.lock"
    with open(lock_path, "a+b") as handle:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = load_placement_policy_document(target)
            revision = int(current.get("revision") or 0) + 1
            policy = PlacementPolicy.validate(
                {"classes": raw_classes},
                allowed_queues=allowed_queues,
                revision=revision,
                updated_at=timestamp,
                updated_by_user_id=actor_user_id,
            )
            atomic_write_json(
                target,
                {
                    "revision": policy.revision,
                    "updated_at": policy.updated_at,
                    "updated_by_user_id": policy.updated_by_user_id,
                    "classes": [cls_.public_dict() for cls_ in policy.classes],
                },
            )
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return policy


def policy_document(policy: PlacementPolicy) -> Mapping[str, Any]:
    """The stored shape of one policy, for the admin read route."""
    return {
        "revision": policy.revision,
        "updated_at": policy.updated_at,
        "updated_by_user_id": policy.updated_by_user_id,
        "policy_digest": policy.policy_digest,
        "declared": policy.declared,
        "classes": [cls_.public_dict() for cls_ in policy.classes],
    }


__all__ = [
    "MAX_POLICY_BYTES",
    "PlacementPolicyStoreError",
    "load_placement_policy",
    "load_placement_policy_document",
    "policy_document",
    "write_placement_policy",
]
