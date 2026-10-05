# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Unit coverage for the CI change-set classifier (tools/classify_ci_scope.py).

The classifier decides whether the expensive test matrix may be skipped for a
documentation-only change. It must fail safe: anything not provably a safe
documentation path keeps the full suite enabled.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_classifier():
    spec = importlib.util.spec_from_file_location(
        "classify_ci_scope", ROOT / "tools" / "classify_ci_scope.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classify = _load_classifier()


@pytest.mark.parametrize(
    "paths,expected",
    [
        # A: guidance + design contract are documentation-only.
        (["docs/agents/long-task-handling.md", "TODO.md"], True),
        # B: a runner README (markdown anywhere) is documentation-only.
        (["docker/runners/fpocket/README.md"], True),
        # C: mixed docs + Python source forces the full matrix.
        (["docs/foo.md", "revocompute/api_receipt.py"], False),
        # D: changing this workflow's own file forces the full matrix.
        ([".github/workflows/tests.yml"], False),
        # E: the server-owned OpenAPI schema forces the full matrix.
        (["revocompute/static/openapi.json"], False),
    ],
)
def test_documentation_only_classification(paths, expected):
    assert classify.is_documentation_only(paths) is expected


@pytest.mark.parametrize(
    "paths",
    [
        ["revocompute/api_receipt.py"],
        ["docker/runners/gremlin_lh/task.yaml"],
        ["docker/runners/gremlin_lh/runner.yaml"],
        ["tests/data/gremlin_lh/upstream_reference.json"],
        ["tests/frontend_fixtures/bundle.json"],
        ["frontend/src/app.js"],
        ["run/restart.sh"],
        ["docker/runners/fpocket/fpocket.def"],
        ["uv.lock"],
        [".github/workflows/docs.yml.bak"],
        ["requirements.lock"],
    ],
)
def test_non_documentation_paths_force_full_matrix(paths):
    assert classify.is_documentation_only(paths) is False


def test_empty_change_set_is_not_documentation_only():
    # Unknown input must fail safe.
    assert classify.is_documentation_only([]) is False
    assert classify.is_documentation_only(None) is False


def test_workflow_dispatch_always_runs_full_matrix():
    # F: a manual dispatch runs the full matrix regardless of the diff.
    assert classify.decide("workflow_dispatch", "", "", None) is True
    assert (
        classify.decide(
            "workflow_dispatch", "", "", ["docs/agents/long-task-handling.md"]
        )
        is True
    )


def test_doc_only_push_and_pull_request_skip_matrix():
    paths = ["docs/foo.md"]
    assert classify.decide("push", "a" * 40, "b" * 40, paths) is False
    assert classify.decide("pull_request", "a" * 40, "b" * 40, paths) is False


def test_missing_or_zero_sha_falls_back_to_full_matrix(monkeypatch):
    monkeypatch.setattr(classify, "changed_paths", lambda base, head: None)
    assert classify.decide("pull_request", "0" * 40, "b" * 40, None) is True
    assert classify.decide("push", "", "", None) is True


def test_git_error_falls_back_to_full_matrix():
    # A real git failure (undeterminable change set) must keep the matrix.
    assert classify.changed_paths("not-a-sha", "also-not-a-sha") is None
    assert classify.decide("pull_request", "not-a-sha", "also-not-a-sha", None) is True
