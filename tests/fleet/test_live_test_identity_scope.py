# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A deployment's enabled families decide which validation cases it can run."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from revocompute.resource_policy import ResourcePolicyValues
from revocompute.runner_live_test import load_validation_identity
from revocompute.runner_registry import load_plugin_families

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "docker" / "runners"


def _deployment_tree(tmp_path: Path, families: tuple[str, ...]) -> Path:
    """A runner tree holding only ``families`` plus the shared runtime overlay."""
    root = tmp_path / "runners"
    root.mkdir()
    for family in (*families, "common"):
        shutil.copytree(RUNNERS / family, root / family)
    return root


def _identity(root: Path):
    family = next(item for item in load_plugin_families(root) if item.name == "gremlin")
    return load_validation_identity(family, resource_provider=ResourcePolicyValues({}, {}), repo_root=ROOT)


def test_a_gremlin_only_deployment_omits_the_composed_case(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLED_TASKRUNNERS", "gremlin")
    root = _deployment_tree(tmp_path, ("pssm_gremlin",))

    identity = _identity(root)

    assert [(case.id, case.task) for case in identity.plan.select("smoke")] == [("minimal-gremlin", "gremlin")]
    # The omitted case is named in the identity, so a filtered plan never reads
    # as a pass for the cross-family path it could not run.
    assert identity.plan.omitted == (("minimal-gremlin-msa-to-lh-fit", "gremlin_msa_to_lh_fit"),)


def test_both_families_enabled_require_the_composed_case(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLED_TASKRUNNERS", "gremlin,gremlin_lh")
    root = _deployment_tree(tmp_path, ("pssm_gremlin", "gremlin_lh"))

    identity = _identity(root)

    assert [case.task for case in identity.plan.select("smoke")] == ["gremlin", "gremlin_msa_to_lh_fit"]
    assert identity.plan.omitted == ()


def test_a_family_that_does_not_exist_is_refused_when_all_are_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("ENABLED_TASKRUNNERS", raising=False)
    root = _deployment_tree(tmp_path, ("pssm_gremlin",))

    with pytest.raises(ValueError, match="unknown runtime family"):
        _identity(root)
