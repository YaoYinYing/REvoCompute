# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""GeoDock result-contract regression, anchored to the observed live-test tree.

The contract is loaded through the same discovery, tree loader and resolver
production uses, so these assertions exercise the shipped declaration rather
than a copy of its YAML shape.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
RUNNERS = ROOT / "docker" / "runners"
TASK_ID = "geodock"
PRIMARY_OUTPUT = "geodock_raw.pdb"

# Observed output tree of the Nov 3 2026 target-host Slurm/Apptainer live-test
# 9676b7a8bc36d3ebea142aa307dddabd at SIF 778d1e07f831. That acceptance run used
# `refine=false`, so `geodock_refined.pdb` is absent: the optional branch must
# stay optional.
OBSERVED = (
    "citations.bib",
    "debug/inputs/partner_a/partner_a.pdb",
    "debug/inputs/partner_b/partner_b.pdb",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-geodock-9676b7a8bc36d3ebea142aa307dddabd.resource.json",
    "execution/slurm-unknown-user-geodock-9676b7a8bc36d3ebea142aa307dddabd.stderr.log",
    "execution/slurm-unknown-user-geodock-9676b7a8bc36d3ebea142aa307dddabd.stdout.log",
    "geodock-confidence.json",
    "geodock-model-assets.sha256",
    "geodock-run.json",
    "geodock_raw.pdb",
    "manifest.json",
    "task_finished",
)


def _load():
    with isolated_discovery(str(RUNNERS)) as manager:
        task = manager.contributions.resolve("tasks", TASK_ID)
    return task, expected_file_tree(task, str(ROOT))


def _resolve(tree, paths):
    return resolve_expected_files(tree, [{"path": path, "size": 1} for path in paths])


def _resolved_paths(resolved):
    return [artifact["path"] for artifacts in resolved.values() for artifact in artifacts]


def _primary_selectors(task):
    view = next(view for view in task.result_workspace if view.role == "primary")
    return [selector for selectors in view.sources.values() for selector in selectors]


def _owner(resolved, path):
    owners = [
        logical_id
        for logical_id, artifacts in resolved.items()
        if any(artifact["path"] == path for artifact in artifacts)
    ]
    assert len(owners) == 1
    return owners[0]


def test_declared_tree_resolves_the_observed_result() -> None:
    task, tree = _load()
    resolved, checks, problems = _resolve(tree, OBSERVED)

    assert tree
    assert problems == []
    assert all(check["status"] == "passed" for check in checks)
    assert PRIMARY_OUTPUT in _resolved_paths(resolved)


def test_primary_view_resolves_to_the_required_single_structure() -> None:
    task, tree = _load()
    resolved, checks, _problems = _resolve(tree, OBSERVED)
    required_sources = [selector for selector in _primary_selectors(task) if selector.required]

    assert any(fnmatchcase(PRIMARY_OUTPUT, selector.value) for selector in required_sources)
    primary_id = _owner(resolved, PRIMARY_OUTPUT)
    assert tree[primary_id]["required"] is True
    assert tree[primary_id]["cardinality"] == "one"
    assert tree[primary_id]["type"] == "structure"
    assert tree[primary_id]["role"] == "evidence"
    assert next(check for check in checks if check["file_id"] == primary_id)["status"] == "passed"


def test_optional_refinement_stays_optional_and_missing_primary_breaks_the_source() -> None:
    task, tree = _load()

    # The acceptance run has no refined pose, and adding one must not create a
    # cardinality or ownership conflict.
    assert _resolve(tree, OBSERVED)[2] == []
    resolved, _checks, problems = _resolve(tree, (*OBSERVED, "geodock_refined.pdb"))
    assert problems == []
    assert "geodock_refined.pdb" in _resolved_paths(resolved)

    without_primary = [path for path in OBSERVED if path != PRIMARY_OUTPUT]
    problems = _resolve(tree, without_primary)[2]
    assert len(problems) == 1 and problems[0].endswith("required output is missing or empty")
    misnamed = [
        path.replace(PRIMARY_OUTPUT, "geodock_raw_model.pdb") if path == PRIMARY_OUTPUT else path
        for path in OBSERVED
    ]
    problems = _resolve(tree, misnamed)[2]
    assert len(problems) == 1 and problems[0].endswith("required output is missing or empty")
