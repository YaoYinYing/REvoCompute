# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Runner Runtime Bundle materialization and binding.

The Runtime Bundle is the non-build counterpart of the SIF: repository-owned
executable code snapshotted content-addressably and pinned by a new submission.
``materialize_runner_bundles`` is shared, because the deployment CLI materializes
a bundle to validate it and the readiness core must ask the same question about
which bundle a new submission would pin.
"""

from __future__ import annotations

import os

from revocompute.runner_registry import RuntimeFamily, runner_enabled


def runner_bundle_root(state) -> str:
    """Deployment-owned Runtime Bundle store.

    A sibling of the image store, never inside ``SERVER_DIR``: the runner tree
    is atomically replaced on every deployment, and a bundle pinned by a queued
    task must not be deleted with it.
    """
    configured = state.get("RUNTIME_BUNDLE_DIR")
    if configured:
        return configured
    return os.path.join(os.path.dirname(os.path.abspath(state.server_dir())), "runtime-bundles")


def materialize_runner_bundles(
    state, families: list[RuntimeFamily], *, activate: bool = True, digests: dict[str, str] | None = None
) -> dict[str, str]:
    """Snapshot each enabled family's declared overlay; return family → digest.

    Snapshots are always written: materializing is idempotent and never mutates
    an existing bundle.  ``activate`` additionally publishes the deployment
    index, which is what makes a bundle eligible for a *new* submission — so
    candidate validation creates the snapshot without changing what a queued
    task or the running deployment resolves.

    ``digests`` publishes already-materialized candidates instead of recomputing
    them.  That is what activation must do: publishing a freshly recomputed
    digest would let a source edit between validation and activation put a
    bundle the receipt never covered into the index.
    """
    from revocompute import runtime_bundle

    store_root = runner_bundle_root(state)
    index = runtime_bundle.load_index(store_root)
    candidate: dict[str, str] = {}
    for family in families:
        # Activation is what makes a bundle eligible for a *new* submission, so
        # a disabled family is never published.  Candidate mode still snapshots
        # it: a family is live-tested before it is enabled, and a validation
        # that could not pin the code it just materialized would fall back to
        # the published binding — exactly the mutable `current` the design
        # forbids.
        if activate and not runner_enabled(state, family.name):
            index.pop(family.name, None)
            continue
        if not family.runtime_overlay:
            index.pop(family.name, None)
            continue
        if digests is not None and family.name in digests:
            candidate[family.name] = digests[family.name]
        elif digests is not None:
            continue  # not part of the validated candidate set
        else:
            if family.root is None:
                raise FileNotFoundError(f"Runner family {family.name} has no source root")
            candidate[family.name], _path = runtime_bundle.materialize(
                family.root.parent, family.runtime_overlay, store_root
            )
        if activate:
            index[family.name] = candidate[family.name]
            print(f"[SLURM] Runtime bundle {family.name}: {candidate[family.name]}")
    if activate:
        runtime_bundle.write_index(store_root, index)
    return candidate
