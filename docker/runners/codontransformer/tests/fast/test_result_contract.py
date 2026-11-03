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
observed result tree, and the primary optimized FASTA and parameter record are
declared required.

Observed paths are the authentic result captured for the Nov 3 2026 target-host
Slurm/Apptainer live test ``2fdcd8499362ad487d8c02cb64ddc17b`` at SIF
``973fd01ced8b`` (in-repo capture: ``tests/data/storyboards/codon_optimize``).
Server-owned ``manifest.json`` and ``task_finished`` are omitted because no
declared logical file names them.
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
    "execution/slurm-unknown-user-codon_optimize-0c1a643ac802b38207dfd04832c65f4a.resource.json",
    "execution/slurm-unknown-user-codon_optimize-0c1a643ac802b38207dfd04832c65f4a.stderr.log",
    "execution/slurm-unknown-user-codon_optimize-0c1a643ac802b38207dfd04832c65f4a.stdout.log",
    "optimized_sequences.fasta",
    "results.json",
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
    assert required_sources
    for _source_name, selector in required_sources:
        assert any(fnmatchcase(path, selector.value) for path in OBSERVED_FILES), selector.value
        covering = _covering_required_entries(tree, selector.value, OBSERVED_FILES)
        assert covering, selector.value
        assert all(tree[logical_id]["required"] for logical_id in covering), selector.value

    assert "optimized_sequences.fasta" in OBSERVED_FILES
    assert "results.json" in OBSERVED_FILES
    assert tree["optimized_sequences"]["required"] is True
    assert tree["results"]["required"] is True


def test_task_reports_no_concrete_audit_finding(monkeypatch):
    task, _ = _discover(monkeypatch)

    assert audit_task(task, server_dir=str(ROOT)) == []


def test_removing_the_primary_artifact_breaks_the_declared_contract(monkeypatch):
    _, tree = _discover(monkeypatch)
    observed = [path for path in OBSERVED_FILES if path != "optimized_sequences.fasta"]

    resolved, checks, problems = _resolve(tree, observed)

    assert resolved["optimized_sequences"] == []
    assert "optimized_sequences: required output is missing or empty" in problems
    assert any(check["file_id"] == "optimized_sequences" and check["status"] == "failed" for check in checks)
