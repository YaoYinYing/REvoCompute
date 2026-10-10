# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""The per-user durable-storage quota *policy* layer.

Durable ownership and the entitlement to retain it are different questions with
different owners.  :mod:`revocompute.resource_ledger` owns the first: an
append-only record of how many bytes a subject actually owns.  This module owns
the second: a closed, three-valued statement of what a subject is *allowed* to
retain, plus the exact SQLite encoding that statement round-trips through.

Three states, one representation, and never ``0`` meaning two things:

``INHERIT``
    no per-user decision exists, so the deployment default applies.  This is the
    state of an absent policy row, and it is deliberately not a stored ``0``:
    a deployment that later changes its default moves every inheriting subject
    with it, which a materialized copy of the old default could not do.
``LIMITED``
    an explicit ceiling in bytes.  ``0`` is a real ceiling of zero bytes — "you
    may retain nothing durable" — and is not a spelling of unlimited.
``UNLIMITED``
    no ceiling at all, so admission never refuses on storage.

A quota change is a *policy* fact.  It happens entirely in
``resource_policies`` plus ``resource_policy_audit`` and it never touches an
accounting fact: no ``resource_ledger`` row, no ``storage_usage`` fact, and no
change to ``logical_owned_bytes``.  :class:`~revocompute.db.TaskDatabase`
performs that write; this module only defines what a policy *is* and how it is
stored: ``INHERIT`` is the absent row, ``LIMITED`` is a non-negative
``allowance``, and ``UNLIMITED`` is the reserved sentinel below, so no two of
the three can collide in one integer column.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from revocompute import resource_ledger as rloan
from revocompute.resource_policy import ResourceValidationError

#: The ledger unit a stored storage-quota policy is filed under.  It is the same
#: value durable ownership uses: one unit vocabulary for one scarce resource, so
#: a policy and the usage it gates can never be read under two spellings.
STORAGE_QUOTA_UNIT = rloan.UNIT_STORAGE_BYTE

#: Bounded operation names recorded on a policy-audit row.  An auditor reads
#: these to tell "an explicit ceiling was set" from "the per-user override was
#: removed so the deployment default applies again"; the two are different
#: administrative acts even though both end as a current policy.
OPERATION_SET_STORAGE_QUOTA = "set_storage_quota"
OPERATION_CLEAR_STORAGE_QUOTA = "clear_storage_quota"

#: What an unlimited policy stores in the NOT NULL integer ``allowance`` column.
#:
#: A real limit is stored as itself, so ``0`` stays a ceiling of zero bytes.  The
#: sentinel is therefore a value no legitimate limit can produce, which is what
#: keeps "unlimited" and "a limit of zero" distinguishable in one column.
STORAGE_QUOTA_UNLIMITED_SENTINEL = -1

#: Messages are bounded so an admin request that echoes back a huge or hostile
#: state string cannot turn a validation error into an unbounded response.
_MESSAGE_CHARS = 60


def _bounded(value: Any) -> str:
    """A short, safe rendering of rejected input for a validation message."""
    text = repr(value)
    return text if len(text) <= _MESSAGE_CHARS else f"{text[:_MESSAGE_CHARS]}..."


class StorageQuotaState(str, Enum):
    """Which of the three distinguishable storage-quota decisions applies."""

    INHERIT = "inherit"
    LIMITED = "limited"
    UNLIMITED = "unlimited"


@dataclass(frozen=True, slots=True)
class StorageQuotaPolicy:
    """One subject's storage-quota decision.

    The two fields are not independent: ``limit_bytes`` is meaningful only for
    :data:`StorageQuotaState.LIMITED`.  Enforcing that in ``__post_init__`` is
    what makes the state the single source of truth — an INHERIT policy that also
    carried a number would invite a reader to apply the number and silently skip
    the deployment default.
    """

    state: StorageQuotaState
    limit_bytes: int | None = None

    def __post_init__(self) -> None:
        state = self.state
        if not isinstance(state, StorageQuotaState):
            try:
                state = StorageQuotaState(state)
            except ValueError:
                raise ResourceValidationError(f"unknown storage quota state: {_bounded(state)}") from None
            object.__setattr__(self, "state", state)
        limit = self.limit_bytes
        if state is StorageQuotaState.LIMITED:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise ResourceValidationError("a limited storage quota requires a non-negative integer limit_bytes")
        elif limit is not None:
            raise ResourceValidationError(f"an {state.value} storage quota takes no limit_bytes")

    def effective_limit_bytes(self, deployment_default_bytes: int | None) -> int | None:
        """The ceiling admission actually applies, in bytes, or ``None``.

        ``None`` is "no ceiling", which is exactly what :data:`UNLIMITED` means
        and also what an INHERIT policy means when the deployment configures no
        default.  Callers therefore never special-case a state: they compare
        against the one number admission refuses on.
        """
        if self.state is StorageQuotaState.INHERIT:
            return deployment_default_bytes
        return self.limit_bytes

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "limit_bytes": self.limit_bytes}


#: The policy of a subject with no stored row, and the policy that removes one.
INHERIT_POLICY = StorageQuotaPolicy(StorageQuotaState.INHERIT)

#: The policy that removes a ceiling without falling back to the deployment one.
UNLIMITED_POLICY = StorageQuotaPolicy(StorageQuotaState.UNLIMITED)


def stored_allowance(policy: StorageQuotaPolicy) -> int:
    """The ``resource_policies.allowance`` value encoding *policy*.

    Only the two stored states have an encoding; ``INHERIT`` is represented by
    the *absence* of a row, so asking for its allowance is a programming error
    rather than a value.
    """
    if policy.state is StorageQuotaState.LIMITED and policy.limit_bytes is not None:
        return policy.limit_bytes
    if policy.state is StorageQuotaState.UNLIMITED:
        return STORAGE_QUOTA_UNLIMITED_SENTINEL
    raise ResourceValidationError("an inherit storage quota has no stored row")


def policy_from_stored_allowance(allowance: Any) -> StorageQuotaPolicy:
    """The policy one stored ``allowance`` encodes, or a bounded refusal.

    A stored value below the unlimited sentinel cannot be produced by
    :func:`parse_quota_input`, so it means the row was written by something else.
    Reading it as a limit would let external state decide admission, so it fails
    closed instead.
    """
    try:
        value = int(allowance)
    except (TypeError, ValueError):
        raise ResourceValidationError("stored storage quota is not a recognisable policy") from None
    if value == STORAGE_QUOTA_UNLIMITED_SENTINEL:
        return UNLIMITED_POLICY
    if value < 0:
        raise ResourceValidationError("stored storage quota is not a recognisable policy")
    return StorageQuotaPolicy(StorageQuotaState.LIMITED, value)


def parse_quota_input(state: str, limit_bytes: Any) -> StorageQuotaPolicy:
    """Validate one admin request into a policy, failing closed with a bounded message.

    ``limit_bytes`` is a *typed* field, not a free string: a ``"limited"`` request
    must name a non-negative integer, and a non-limited request must not carry a
    number at all.  Accepting ``None`` as "unlimited" would make the absent value
    mean a decision the admin never made, and accepting ``0`` for the same thing
    would steal the one honest spelling of an empty ceiling.
    """
    if isinstance(state, StorageQuotaState):
        normalized = state
    elif isinstance(state, str):
        try:
            normalized = StorageQuotaState(state.strip().lower())
        except ValueError:
            raise ResourceValidationError(f"unknown storage quota state: {_bounded(state)}") from None
    else:
        raise ResourceValidationError(f"unknown storage quota state: {_bounded(state)}")

    if normalized is StorageQuotaState.LIMITED:
        if isinstance(limit_bytes, bool) or not isinstance(limit_bytes, int):
            raise ResourceValidationError("a limited storage quota requires an integer limit_bytes")
        if limit_bytes < 0:
            raise ResourceValidationError("limit_bytes must be non-negative; 0 means no durable storage")
        return StorageQuotaPolicy(normalized, limit_bytes)
    if limit_bytes is not None:
        raise ResourceValidationError(f"an {normalized.value} storage quota takes no limit_bytes")
    return StorageQuotaPolicy(normalized)
