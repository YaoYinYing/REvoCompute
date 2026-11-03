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
on the observed result tree, the three 320 K plots the primary view selects are
covered by required declarations, and the required plot/table patterns still
resolve.

Observed paths are a one-temperature representative subset of the authentic
result captured for the Nov 3 2026 target-host Slurm/Apptainer live test
``40881cad5bfa6799f7895cde9824b58b`` at SIF ``6a357433c22e`` (full tree: 174
files across five temperatures; in-repo capture:
``tests/data/storyboards/esmdynamic``). Server-owned ``manifest.json`` and
``task_finished`` are omitted because no declared logical file names them.
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
    "2KL8/dynamic/2KL8_dynamic_prob_320K.html",
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
    "execution/slurm-unknown-user-esmdynamic-86adfa8e017342d0f31dbef62a8e8a5f.resource.json",
    "execution/slurm-unknown-user-esmdynamic-86adfa8e017342d0f31dbef62a8e8a5f.stderr.log",
    "execution/slurm-unknown-user-esmdynamic-86adfa8e017342d0f31dbef62a8e8a5f.stdout.log",
)

#: The 320 K plots the primary view selects, in the order the view declares them.
PRIMARY_SOURCES = (
    "*/dynamic/*_dynamic_confidence_320K.png",
    "*/frequency/*_frequency_pred_320K.png",
    "*/kinetics/*_kinetics_confidence_320K.png",
)


def _discover(monkeypatch):
    monkeypatch.delenv("RUNNERS_DIR", raising=False)
    with isolated_discovery(str(ROOT / "docker" / "runners"), {FAMILY}) as manager:
        task = manager.contributions.resolve("tasks", TASK)
        tree = expected_file_tree(task, str(ROOT))
    return task, tree


def _resolve(tree, observed):
    artifacts = [{"path": path, "size": 1} for path in observed]
    return resolve_expected_files(tree, artifacts)


def _covering_required_entries(tree, selector, observed):
    matching = [path for path in observed if fnmatchcase(path, selector)]
    return [
        logical_id
        for logical_id, definition in tree.items()
        if any(fnmatchcase(path, definition.get("path") or definition["pattern"]) for path in matching)
    ]


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
    for logical_id in (
        "temperature_plots",
        "confidence_tables",
        "frequency_plots",
        "kinetics_plots",
        "kinetics_tables",
        "nonnative_plots",
        "native_contacts",
        "predicted_structure",
        "probability_arrays",
        "plot_html",
    ):
        assert resolved[logical_id], logical_id


def test_primary_scientific_artifacts_are_required_declarations(monkeypatch):
    task, tree = _discover(monkeypatch)
    view = next(view for view in task.result_workspace if view.role == "primary")

    assert view.plugin == "evidence-bundle"
    required_sources = [
        (source_name, selector)
        for source_name, selectors in view.sources.items()
        for selector in selectors
        if selector.required
    ]
    assert [selector.value for _source_name, selector in required_sources] == list(PRIMARY_SOURCES)
    for _source_name, selector in required_sources:
        assert any(fnmatchcase(path, selector.value) for path in OBSERVED_FILES), selector.value
        covering = _covering_required_entries(tree, selector.value, OBSERVED_FILES)
        assert covering, selector.value
        assert all(tree[logical_id]["required"] for logical_id in covering), selector.value

    assert tree["temperature_plots"]["required"] is True
    assert tree["frequency_plots"]["required"] is True
    assert tree["kinetics_plots"]["required"] is True


def test_task_reports_no_concrete_audit_finding(monkeypatch):
    task, _ = _discover(monkeypatch)

    assert audit_task(task, server_dir=str(ROOT)) == []


def test_removing_the_primary_artifacts_breaks_the_declared_contract(monkeypatch):
    _, tree = _discover(monkeypatch)
    observed = [path for path in OBSERVED_FILES if not any(fnmatchcase(path, pattern) for pattern in PRIMARY_SOURCES)]

    resolved, checks, problems = _resolve(tree, observed)

    assert not any(fnmatchcase(path, "*/dynamic/*_dynamic_confidence_320K.png") for path in observed)
    assert resolved["temperature_plots"] == []
    assert "temperature_plots: required output is missing or empty" in problems
    assert any(check["file_id"] == "temperature_plots" and check["status"] == "failed" for check in checks)
