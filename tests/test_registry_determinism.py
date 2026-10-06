# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Registry determinism: discovery is explicit, order-independent, and atomic.

The recurring pytest-xdist ``Unknown task type`` failure came from discovery
mutating shared module state non-atomically and from callers depending on
another test having populated that state first.  These cases pin the invariants
that make the snapshot reproducible regardless of which test ran before.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from revocompute.access_control import list_policies, set_active_policies
from revocompute.task_types import (
    active_plugin_manager,
    discover_plugins,
    get,
    isolated_discovery,
    list_categories,
    list_types,
)

INPUTS = "inputs:\n  source:\n    type: text\n    formats: [json]\n    cardinality: {min: 1, max: 1}\n"


def _family(root: Path, family_id: str, *, task_id: str | None = None, policy: str | None = None) -> None:
    task_id = task_id or f"{family_id}_task"
    family = root / family_id
    task_dir = family / "tasks" / task_id
    task_dir.mkdir(parents=True)
    policy_yaml = ""
    if policy:
        (root / "common" / "policy").mkdir(parents=True, exist_ok=True)
        (root / "common" / "policy" / f"{policy}.yaml").write_text(
            f"id: {policy}\nlabel: {policy}\ndescription: restricted\nrequires: [{policy}_terms]\n"
            "match: all\nrequestable: true\n",
            encoding="utf-8",
        )
        policy_yaml = f"access_policies: [common/policy/{policy}.yaml]\ncontributions:\n  access_policies: [{policy}]\n"
    (family / "plugin.yaml").write_text(
        f"api_version: 1\nid: {family_id}\nversion: '1'\n"
        "runtime:\n  image_artifact: img.sif\n  definition: runner.def\n"
        f"tasks:\n  - tasks/{task_id}/task.yaml\n{policy_yaml}",
        encoding="utf-8",
    )
    (family / "runner.def").write_text("Bootstrap: ubuntu\n", encoding="utf-8")
    (task_dir / "task.yaml").write_text(
        f"id: {task_id}\ndisplay_name: {task_id}\ncategory: folding\n{INPUTS}", encoding="utf-8"
    )


def _snapshot() -> tuple[tuple[str, ...], tuple[tuple[str, str], ...], tuple[str, ...]]:
    return (
        tuple(task.name for task in list_types()),
        tuple((category.name, category.label) for category in list_categories()),
        tuple(policy.id for policy in list_policies()),
    )


def test_repeated_discovery_of_the_same_tree_is_idempotent(tmp_path):
    _family(tmp_path, "alpha", policy="alpha_policy")
    _family(tmp_path, "beta")

    discover_plugins(str(tmp_path))
    first = _snapshot()
    discover_plugins(str(tmp_path))
    discover_plugins(str(tmp_path))

    assert _snapshot() == first
    assert first[0] == ("alpha_task", "beta_task")


def test_snapshot_does_not_depend_on_directory_enumeration_order(tmp_path):
    """Two trees with the same content in different creation order match."""
    forward = tmp_path / "forward"
    reverse = tmp_path / "reverse"
    for root, order in ((forward, ("alpha", "beta", "gamma")), (reverse, ("gamma", "beta", "alpha"))):
        for name in order:
            _family(root, name)

    discover_plugins(str(forward))
    forward_snapshot = _snapshot()
    discover_plugins(str(reverse))

    assert _snapshot() == forward_snapshot


def test_enabled_family_selection_is_honored_deterministically(tmp_path):
    _family(tmp_path, "alpha")
    _family(tmp_path, "beta")

    discover_plugins(str(tmp_path), {"beta"})

    assert tuple(task.name for task in list_types()) == ("beta_task",)
    with pytest.raises(KeyError, match="Unknown task type"):
        get("alpha_task")


def test_unknown_family_and_task_lookup_fail_deterministically(tmp_path):
    _family(tmp_path, "alpha")
    discover_plugins(str(tmp_path))

    for name in ("missing", "", "alpha-task", "../alpha"):
        with pytest.raises(KeyError):
            get(name)


def test_isolated_discovery_restores_the_active_snapshot_exactly(tmp_path):
    _family(tmp_path / "installed", "installed")
    discover_plugins(str(tmp_path / "installed"))
    before = (_snapshot(), active_plugin_manager())

    other = tmp_path / "other"
    _family(other, "other")
    with isolated_discovery(str(other)) as manager:
        assert manager is active_plugin_manager()
        assert tuple(task.name for task in list_types()) == ("other_task",)
        assert list_policies() == []

    assert _snapshot() == before[0]
    assert active_plugin_manager() is before[1]


def test_isolated_discovery_is_reentrant(tmp_path):
    outer = tmp_path / "outer"
    inner = tmp_path / "inner"
    _family(outer, "outer")
    _family(inner, "inner")

    with isolated_discovery(str(outer)):
        assert tuple(task.name for task in list_types()) == ("outer_task",)
        with isolated_discovery(str(inner)):
            assert tuple(task.name for task in list_types()) == ("inner_task",)
        assert tuple(task.name for task in list_types()) == ("outer_task",)


def test_failed_discovery_leaves_the_active_snapshot_readable(tmp_path):
    good = tmp_path / "good"
    _family(good, "alpha", policy="alpha_policy")
    discover_plugins(str(good))
    before = _snapshot()

    broken = tmp_path / "broken"
    _family(broken, "beta", policy="beta_policy")
    (broken / "common" / "policy" / "beta_policy.yaml").unlink()

    with pytest.raises(FileNotFoundError):
        discover_plugins(str(broken))

    # The rejected discovery never became active; the prior snapshot is intact.
    assert _snapshot() == before
    assert get("alpha_task")[0].name == "alpha_task"


def test_reads_without_an_installed_snapshot_are_empty_not_stale(tmp_path):
    """A fresh worker with no discovery must not observe another worker's state."""
    import revocompute.task_types as task_types

    original = task_types._state
    try:
        set_active_policies({})
        task_types._state = task_types._RegistryState()
        assert list_types() == []
        assert list_categories() == []
        assert list_policies() == []
        with pytest.raises(KeyError, match="Unknown task type"):
            get("alpha")
    finally:
        task_types._install_snapshot(original)
