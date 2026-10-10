# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Behavior coverage for the CI affected-lane classifier (tools/classify_ci_scope.py).

The classifier is the single source of truth for which expensive CI lane a change
set must pay for, and it must fail closed: an unrecognized, empty, or
undeterminable change set selects every lane. These tests drive the real
classification functions and the real command-line contract the workflow
consumes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_classifier():
    spec = importlib.util.spec_from_file_location("classify_ci_scope", ROOT / "tools" / "classify_ci_scope.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classify = _load_classifier()

ALL = frozenset(classify.LANES)


# --------------------------------------------------------------------------- #
# Lane selection per path class
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "paths,expected",
    [
        # Documentation: the docs page, the site config, and the docs workflow are
        # validated by the docs lane itself.
        (["docs/agents/long-task-handling.md"], {"docs"}),
        (["mkdocs.yml"], {"docs"}),
        ([".github/workflows/docs.yml"], {"docs"}),
        (["GOAL_GMX_MMPBSA.md"], {"docs"}),
        (["docker/runners/fpocket/README.md"], {"docs"}),
        # An isolated frontend surface runs the browser lane only.
        (["frontend/src/routes/results.ts"], {"browser"}),
        (["frontend/package-lock.json"], {"browser"}),
        # The published OpenAPI document and other trust/persistence boundaries
        # are cross-cutting, so they run every lane.
        (["revocompute/api_receipt.py"], ALL),
        # An isolated backend leaf module runs the server lane only.
        (["revocompute/result_audit.py"], {"server"}),
        # A server projection the browser renders also runs the browser lane.
        (["revocompute/result_projection.py"], {"server", "browser"}),
        (["revocompute/templates/index.html"], {"server", "browser"}),
        # Scheduling/controller surfaces run the Compose full-stack lane too.
        (["revocompute/task_runtime.py"], {"server", "compose"}),
        (["revocompute/operator_jobs.py"], {"server", "compose"}),
        # Scientific families keep their scientific acceptance and never degrade
        # to generic backend-only.
        (["docker/runners/gremlin_lh/task.yaml"], {"server", "runner_fast", "runner_scientific"}),
        (["docker/runners/gremlin_lh/runner.yaml"], {"server", "runner_fast", "runner_scientific"}),
        (["docker/runners/gremlin_lh/tests/scientific/references/upstream_reference.json"], {"server", "runner_fast", "runner_scientific"}),
        (["docker/runners/gremlin_lh/tests/scientific/test_upstream_equivalence.py"], {"server", "runner_fast", "runner_scientific"}),
        # Scientific fixtures that still live under the shared tests/data corpus.
        (["tests/data/evosplit/minimal.a3m"], {"server", "runner_fast", "runner_scientific"}),
        (["docker/runners/common/runner_common.py"], {"server", "runner_fast", "runner_scientific"}),
        # An ordinary Runner receives both generic and family-owned contracts.
        (["docker/runners/fpocket/fpocket.def"], {"server", "runner_fast"}),
        (["docker/runners/fpocket/tests/fast/test_adapter.py"], {"server", "runner_fast"}),
        (["docker/runners/evosplit/tests/scientific/test_adapter.py"], {"server", "runner_fast", "runner_scientific"}),
        (["docker/runner_testkit/pytest_plugin.py"], {"server", "runner_fast", "runner_scientific"}),
        (["tests/fleet/test_manifest_projection.py"], {"server", "runner_fast", "browser"}),
        (["tools/check_test_boundaries.py"], ALL),
        # Deployment and controller paths run the Compose lane.
        (["docker-compose.yml"], {"compose"}),
        (["docker-compose.slurm.yml"], {"compose"}),
        (["run/restart.sh"], {"server", "compose"}),
        (["config/access_policies/README.md"], {"docs"}),  # markdown stays docs
        (["config/access_policies/default.yaml"], {"server", "compose"}),
        (["docker/server/Dockerfile"], {"compose"}),
        (["nginx_sites/REvoCompute.app"], {"compose"}),
        # Frontend fixtures and Playwright contracts need a browser.
        (["tests/frontend_fixtures/builders.py"], {"server", "browser"}),
        (["tests/test_playwright_results.py"], {"server", "browser"}),
        # The landing-page contract renders the built frontend bundle, so a
        # change here needs the frontend build the browser lane provides.
        (["tests/test_tasks.py"], {"server", "browser"}),
        # The landing-page contract asserts the built frontend bundle.
        (["tests/test_tasks.py"], {"server", "browser"}),
        # Ordinary server tests stay server-only.
        (["tests/test_auth.py"], {"server"}),
        (["tools/audit_runtime_sizes.py"], {"server"}),
    ],
)
def test_lane_selection(paths, expected):
    assert classify.classify_paths(paths) == frozenset(expected)


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        "Makefile",
        ".coveragerc",
        ".github/workflows/tests.yml",
        ".github/dependabot.yml",
        "revocompute/static/openapi.json",
        "revocompute/schemas.py",
        "revocompute/auth.py",
        "revocompute/db.py",
        "revocompute/storage.py",
        "revocompute/resource_ledger.py",
        "revocompute/input_validators/pdb.py",
        "revocompute/plugins/kernel.py",
        # A brand-new top-level area the policy does not recognize: fail closed.
        "some/new/area.py",
        "newarea/module.py",
        "unexpected.txt",
    ],
)
def test_cross_cutting_and_unknown_paths_select_every_lane(path):
    assert classify.classify_paths([path]) == ALL


def test_union_of_paths_selects_every_affected_lane():
    lanes = classify.classify_paths(["frontend/src/app.js", "revocompute/result_audit.py"])
    assert lanes == frozenset({"browser", "server"})
    # A mixed change set never narrows below any single path's requirement.
    assert classify.classify_paths(["docs/x.md", "revocompute/api_receipt.py"]) == ALL


def test_empty_change_set_is_unknown_and_fails_closed():
    assert classify.classify_paths([]) == ALL
    assert classify.classify_paths(None) == ALL
    assert classify.classify_paths(["", "   "]) == ALL


# --------------------------------------------------------------------------- #
# Event and git-range behaviour
# --------------------------------------------------------------------------- #


def test_manual_dispatch_always_runs_every_lane():
    assert classify.classify("workflow_dispatch", "", "", None) == ALL
    assert classify.classify("workflow_dispatch", "", "", ["docs/foo.md"]) == ALL


def test_documentation_only_change_skips_the_code_lanes():
    assert classify.classify("pull_request", "a" * 40, "b" * 40, ["docs/foo.md"]) == frozenset({"docs"})
    assert classify.classify("push", "a" * 40, "b" * 40, ["docs/foo.md"]) == frozenset({"docs"})


def test_unknown_event_fails_closed():
    assert classify.classify("schedule", "", "", None) == ALL


def test_missing_or_zero_sha_falls_back_to_every_lane(monkeypatch):
    monkeypatch.setattr(classify, "changed_paths", lambda base, head: None)
    assert classify.classify("pull_request", "0" * 40, "b" * 40, None) == ALL
    assert classify.classify("push", "", "", None) == ALL


def test_git_error_falls_back_to_every_lane():
    assert classify.changed_paths("not-a-sha", "also-not-a-sha") is None
    assert classify.classify("pull_request", "not-a-sha", "also-not-a-sha", None) == ALL


def test_git_range_reads_the_prs_own_paths():
    """Classify a real commit range in this repository through the real git call."""
    base = "5e3e94889bc82cb3eeca6e696f419f82a95d7041"  # main at this PR's creation
    head = "53789f3f830b57bffd9f97c5744185915aa781e4"  # this PR's planning commit
    paths = classify.changed_paths(base, head)
    if paths is None:
        pytest.skip("base/head range is unavailable in this checkout")
    assert "TODO.md" in paths
    assert classify.classify("pull_request", base, head, None) == frozenset({"docs"})


def test_forged_lane_output_cannot_be_trusted_and_defaults_stay_broad():
    """The lane vocabulary is closed: a caller cannot invent a lane the gates ignore."""
    assert set(classify.LANES) == {"docs", "server", "runner_fast", "runner_scientific", "browser", "compose"}
    assert classify.ALL_LANES == frozenset(classify.LANES)


# --------------------------------------------------------------------------- #
# The command-line contract the workflow consumes
# --------------------------------------------------------------------------- #


def test_cli_writes_every_lane_key_and_a_broad_default(tmp_path, monkeypatch):
    """A workflow reads lane booleans from ``$GITHUB_OUTPUT``.

    Every lane key must be present on every run, and the default for a change set
    the classifier cannot place must be broad -- so a classifier error can only
    widen validation, never silently narrow it.
    """
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert classify.main(["--event", "pull_request", "--paths", "frontend/src/app.js"]) == 0
    lines = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in output.read_text().splitlines()}
    assert set(classify.LANES) <= set(lines)
    assert lines["browser"] == "true"
    assert lines["server"] == "false"
    assert lines["runner_scientific"] == "false"
    assert lines["full"] == "false"

    output.unlink()
    assert classify.main(["--event", "pull_request", "--paths", "unrecognized/new/path.c"]) == 0
    lines = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in output.read_text().splitlines()}
    assert all(lines[lane] == "true" for lane in classify.LANES)
    assert lines["full"] == "true"


def test_classifier_policy_change_requires_full_matrix():
    assert classify.classify_paths(["tools/classify_ci_scope.py"]) == classify.ALL_LANES
