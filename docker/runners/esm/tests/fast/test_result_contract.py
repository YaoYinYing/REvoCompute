# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Result-contract regression for the ESM ``esm_extract`` Task.

The Task's only view is an ``evidence-bundle``. The auditor's required-source
invariant exempts an evidence bundle's ``items`` (``_COVERAGE_EXEMPT_SOURCES``
in ``revocompute.result_audit``), so the audit reports the Task as
``no_required_source`` even though ``expected_files.yaml`` declares the opaque
``*.pt`` representation bundle as required. This test pins the contract the
audit cannot evaluate on its own: every declared required logical file resolves
on the observed result tree, and the primary representation bundle is declared
required.

Observed paths are the authentic result captured for the Nov 3 2026 target-host
Slurm/Apptainer live test ``2a326225cf9f1598f0e9dc0392471088`` at SIF
``553493ba5b1a`` (in-repo capture: ``tests/data/storyboards/esm_extract``).
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
FAMILY = "esm"
TASK = "esm_extract"

OBSERVED_FILES = (
    "2KL8.pt",
    "citations.bib",
    "debug/inputs/sequence/2KL8.fasta",
    "debug/submission.json",
    "execution/slurm-status.execution.json",
    "execution/slurm-unknown-user-esm_extract-a2f8bf35d28c881fd85b759378623155.resource.json",
    "execution/slurm-unknown-user-esm_extract-a2f8bf35d28c881fd85b759378623155.stderr.log",
    "execution/slurm-unknown-user-esm_extract-a2f8bf35d28c881fd85b759378623155.stdout.log",
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


def test_primary_scientific_artifact_is_a_required_declaration(monkeypatch):
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

    assert "2KL8.pt" in OBSERVED_FILES
    assert tree["embeddings"]["required"] is True


def test_task_reports_no_concrete_audit_finding(monkeypatch):
    task, _ = _discover(monkeypatch)

    assert audit_task(task, server_dir=str(ROOT)) == []


def test_removing_the_primary_artifact_breaks_the_declared_contract(monkeypatch):
    _, tree = _discover(monkeypatch)
    observed = [path for path in OBSERVED_FILES if path != "2KL8.pt"]

    resolved, checks, problems = _resolve(tree, observed)

    assert resolved["embeddings"] == []
    assert "embeddings: required output is missing or empty" in problems
    assert any(check["file_id"] == "embeddings" and check["status"] == "failed" for check in checks)
