# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Result-contract regression for the CodonTransformer ``codon_optimize`` Task.

The Task's only view is an ``evidence-bundle``. The auditor's required-source
invariant exempts an evidence bundle's ``items`` (``_COVERAGE_EXEMPT_SOURCES``
in ``revocompute.result_audit``), so the audit reports the Task as
``no_required_source`` even though ``expected_files.yaml`` declares every file
the view selects as required. This test pins the contract the audit cannot
evaluate on its own: every declared required logical file resolves on the
observed result tree, the primary view's required sources are claimed only by
required declarations, and removing a primary artifact breaks the contract.

Observed paths are the exact regular-file list captured for the Nov 3 2026
target-host Slurm/Apptainer live test ``2fdcd8499362ad487d8c02cb64ddc17b`` at
SIF ``973fd01ced8b`` (``/tmp/pr133-evidence/trees/codon_optimize.txt``).
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from revocompute.result_audit import audit_task
from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
FAMILY = "codontransformer"
TASK = "codon_optimize"

OBSERVED_FILES = (
    "citations.bib",
    "debug/inputs/sequence/minimal.fasta",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-codon_optimize-2fdcd8499362ad487d8c02cb64ddc17b.resource.json",
    "execution/slurm-unknown-user-codon_optimize-2fdcd8499362ad487d8c02cb64ddc17b.stderr.log",
    "execution/slurm-unknown-user-codon_optimize-2fdcd8499362ad487d8c02cb64ddc17b.stdout.log",
    "manifest.json",
    "optimized_sequences.fasta",
    "results.json",
    "task_finished",
)


def _discover(monkeypatch):
    monkeypatch.delenv("RUNNERS_DIR", raising=False)
    with isolated_discovery(str(ROOT / "docker" / "runners"), {FAMILY}) as manager:
        task = manager.contributions.resolve("tasks", TASK)
        tree = expected_file_tree(task, str(ROOT))
    return task, tree


def _resolve(tree, observed):
    return resolve_expected_files(tree, [{"path": path, "size": 1} for path in observed])


def test_every_declared_required_file_resolves_on_the_observed_tree(monkeypatch):
    _, tree = _discover(monkeypatch)
    resolved, checks, problems = _resolve(tree, OBSERVED_FILES)

    assert problems == []
    for logical_id, definition in tree.items():
        if definition["required"]:
            assert resolved[logical_id], logical_id
    assert all(check["status"] == "passed" for check in checks if check["required"])


def test_primary_view_sources_resolve_to_required_declarations(monkeypatch):
    task, tree = _discover(monkeypatch)
    resolved, _, _ = _resolve(tree, OBSERVED_FILES)
    required_paths = {
        item["path"]
        for logical_id, definition in tree.items()
        if definition["required"]
        for item in resolved[logical_id]
    }

    view = next(view for view in task.result_workspace if view.role == "primary")
    assert view.plugin == "evidence-bundle"
    required_selectors = [
        selector
        for selectors in view.sources.values()
        for selector in selectors
        if selector.required
    ]
    assert required_selectors
    for selector in required_selectors:
        matching = [path for path in OBSERVED_FILES if fnmatchcase(path, selector.value)]
        assert matching, selector.value
        assert set(matching) <= required_paths, selector.value


def test_task_reports_no_concrete_audit_finding(monkeypatch):
    task, _ = _discover(monkeypatch)

    assert audit_task(task, server_dir=str(ROOT)) == []


def test_removing_the_primary_artifact_breaks_the_declared_contract(monkeypatch):
    _, tree = _discover(monkeypatch)
    before, _, _ = _resolve(tree, OBSERVED_FILES)
    primary = "optimized_sequences.fasta"
    owning = {
        logical_id
        for logical_id, items in before.items()
        if any(item["path"] == primary for item in items)
    }
    assert owning
    observed = [path for path in OBSERVED_FILES if path != primary]

    resolved, checks, problems = _resolve(tree, observed)

    assert any(not resolved[logical_id] for logical_id in owning)
    assert any(
        problem.startswith(f"{logical_id}: required output is missing") for logical_id in owning for problem in problems
    )
    assert any(check["file_id"] in owning and check["status"] == "failed" for check in checks)
