# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Result-contract regression for the ESMDynamic ``esmdynamic`` Task.

The Task's only view is an ``evidence-bundle``. The auditor's required-source
invariant exempts an evidence bundle's ``items`` (``_COVERAGE_EXEMPT_SOURCES``
in ``revocompute.result_audit``), so the audit reports the Task as
``no_required_source`` even though ``expected_files.yaml`` declares every
required plot, table and structure pattern. This test pins the contract the
audit cannot evaluate on its own: every declared required logical file resolves
on the observed result tree, the primary view's three required sources are
claimed only by required declarations, and removing them breaks the contract.

Observed paths are a one-temperature representative subset of the 174-file
regular-file list captured for the Nov 3 2026 target-host Slurm/Apptainer live
test ``40881cad5bfa6799f7895cde9824b58b`` at SIF ``6a357433c22e``
(``/tmp/pr133-evidence/trees/esmdynamic.txt``). The subset retains all three
required-view selectors (320 K dynamic, frequency and kinetics plots) and at
least one file for every declared required pattern.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from revocompute.result_audit import audit_task
from revocompute.result_storyboard import expected_file_tree, resolve_expected_files
from revocompute.task_types import isolated_discovery

ROOT = Path(__file__).resolve().parents[5]
FAMILY = "esmdynamic"
TASK = "esmdynamic"

OBSERVED_FILES = (
    "2KL8/2KL8.pdb",
    "2KL8/dynamic/2KL8_dynamic_confidence_320K.csv",
    "2KL8/dynamic/2KL8_dynamic_confidence_320K.png",
    "2KL8/dynamic/2KL8_dynamic_pred_320K.html",
    "2KL8/dynamic_nonnative/2KL8_dynamic_nonnative_320K.png",
    "2KL8/frequency/2KL8_frequency_error_320K.png",
    "2KL8/frequency/2KL8_frequency_pred_320K.png",
    "2KL8/kinetics/2KL8_kinetics_confidence_320K.csv",
    "2KL8/kinetics/2KL8_kinetics_confidence_320K.png",
    "2KL8/kinetics/2KL8_kinetics_off_class_320K.png",
    "2KL8/kinetics/2KL8_kinetics_off_probabilities_320K.npz",
    "2KL8/kinetics/2KL8_kinetics_on_class_320K.png",
    "2KL8/kinetics/2KL8_kinetics_on_probabilities_320K.npz",
    "2KL8/native/2KL8_native_contacts.png",
    "citations.bib",
    "debug/inputs/sequence/2KL8.fasta",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-esmdynamic-40881cad5bfa6799f7895cde9824b58b.resource.json",
    "execution/slurm-unknown-user-esmdynamic-40881cad5bfa6799f7895cde9824b58b.stderr.log",
    "execution/slurm-unknown-user-esmdynamic-40881cad5bfa6799f7895cde9824b58b.stdout.log",
)


def _discover(monkeypatch):
    monkeypatch.delenv("RUNNERS_DIR", raising=False)
    with isolated_discovery(str(ROOT / "docker" / "runners"), {FAMILY}) as manager:
        task = manager.contributions.resolve("tasks", TASK)
        tree = expected_file_tree(task, str(ROOT))
    return task, tree


def _resolve(tree, observed):
    return resolve_expected_files(tree, [{"path": path, "size": 1} for path in observed])


def _required_selectors(task):
    view = next(view for view in task.result_workspace if view.role == "primary")
    assert view.plugin == "evidence-bundle"
    return [selector for selectors in view.sources.values() for selector in selectors if selector.required]


def test_every_declared_required_file_resolves_on_the_observed_tree(monkeypatch):
    _, tree = _discover(monkeypatch)
    resolved, checks, problems = _resolve(tree, OBSERVED_FILES)

    assert problems == []
    for logical_id, definition in tree.items():
        if definition["required"]:
            assert resolved[logical_id], logical_id
    assert all(check["status"] == "passed" for check in checks if check["required"])


def test_required_plot_table_and_structure_patterns_resolve(monkeypatch):
    _, tree = _discover(monkeypatch)
    resolved, _, problems = _resolve(tree, OBSERVED_FILES)

    assert problems == []
    required_kinds = [
        logical_id
        for logical_id, definition in tree.items()
        if definition["required"] and definition.get("type") in {"image", "table", "structure"}
    ]
    assert required_kinds
    for logical_id in required_kinds:
        assert resolved[logical_id], logical_id


def test_primary_view_sources_resolve_to_required_declarations(monkeypatch):
    task, tree = _discover(monkeypatch)
    resolved, _, _ = _resolve(tree, OBSERVED_FILES)
    required_paths = {
        item["path"]
        for logical_id, definition in tree.items()
        if definition["required"]
        for item in resolved[logical_id]
    }

    selectors = _required_selectors(task)
    assert selectors
    for selector in selectors:
        matching = [path for path in OBSERVED_FILES if fnmatchcase(path, selector.value)]
        assert matching, selector.value
        assert set(matching) <= required_paths, selector.value


def test_task_reports_no_concrete_audit_finding(monkeypatch):
    task, _ = _discover(monkeypatch)

    assert audit_task(task, server_dir=str(ROOT)) == []


def test_removing_the_primary_artifacts_breaks_the_declared_contract(monkeypatch):
    task, tree = _discover(monkeypatch)
    primary_paths = {
        path
        for selector in _required_selectors(task)
        for path in OBSERVED_FILES
        if fnmatchcase(path, selector.value)
    }
    assert primary_paths
    before, _, _ = _resolve(tree, OBSERVED_FILES)
    owning = {
        logical_id
        for logical_id, items in before.items()
        if any(item["path"] in primary_paths for item in items)
    }
    assert owning
    observed = [path for path in OBSERVED_FILES if path not in primary_paths]

    resolved, checks, problems = _resolve(tree, observed)

    assert any(not resolved[logical_id] for logical_id in owning)
    assert any(
        problem.startswith(f"{logical_id}: required output is missing") for logical_id in owning for problem in problems
    )
    assert any(check["file_id"] in owning and check["status"] == "failed" for check in checks)
