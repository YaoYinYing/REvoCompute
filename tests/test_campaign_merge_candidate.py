# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Behavior coverage for merge-candidate identity and evidence carry-forward.

Every test here drives the real functions against real git repositories built in
a temporary directory, so the identity rules are exercised end to end: the
merge-base patch digest, the merge-tree integration identity, and the Class 0-3
drift decision that decides whether prior content review may be carried forward.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "campaign_merge_candidate", ROOT / "tools" / "campaign_merge_candidate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


candidate = _load_module()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )
    return result.stdout.strip()


def _write(repo: Path, relative: str, content: str) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _write(work, "revocompute/result_audit.py", "value = 1\n")
    _write(work, "frontend/src/app.js", "console.log('a');\n")
    _commit(work, "base")
    return work


# --------------------------------------------------------------------------- #
# Patch identity
# --------------------------------------------------------------------------- #


def test_patch_digest_is_stable_across_a_content_identical_rebase(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "revocompute/result_audit.py", "value = 2\n")
    reviewed_head = _commit(repo, "pr change")
    reviewed_digest = candidate.patch_digest(base, reviewed_head, repo)

    # main advances with an unrelated commit.
    _git(repo, "checkout", "-q", "main")
    _write(repo, "frontend/src/app.js", "console.log('b');\n")
    new_base = _commit(repo, "unrelated main advance")

    # Rebase the PR onto the new main: ancestry changes, content does not.
    _git(repo, "checkout", "-q", "pr")
    _git(repo, "rebase", "-q", "main")
    rebased_head = _git(repo, "rev-parse", "HEAD")
    assert rebased_head != reviewed_head

    # The three-dot (merge-base) digest is content identity across the rebase.
    assert candidate.patch_digest(new_base, rebased_head, repo) == reviewed_digest
    # A two-dot range would have changed -- that is exactly the false escalation
    # this definition avoids.
    assert candidate.patch_digest(reviewed_head, reviewed_head, repo) != reviewed_digest


def test_patch_digest_changes_when_the_content_changes(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "revocompute/result_audit.py", "value = 2\n")
    first = _commit(repo, "pr change")
    before = candidate.patch_digest(base, first, repo)
    _write(repo, "revocompute/result_audit.py", "value = 3\n")
    second = _commit(repo, "pr change, amended")
    assert candidate.patch_digest(base, second, repo) != before


def test_changed_paths_digest_is_order_independent():
    assert candidate.changed_paths_digest(["b.py", "a.py"]) == candidate.changed_paths_digest(["a.py", "b.py"])


# --------------------------------------------------------------------------- #
# Merge-tree integration identity
# --------------------------------------------------------------------------- #


def test_clean_merge_reports_a_tree_and_no_conflicts(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "revocompute/result_audit.py", "value = 2\n")
    head = _commit(repo, "pr change")
    tree_oid, conflicts = candidate.merge_tree(base, head, repo)
    assert len(tree_oid) == 40
    assert conflicts == []


def test_conflicting_merge_is_reported_as_unmergeable(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "revocompute/result_audit.py", "value = 2\n")
    head = _commit(repo, "pr change")
    _git(repo, "checkout", "-q", "main")
    _write(repo, "revocompute/result_audit.py", "value = 9\n")
    new_base = _commit(repo, "competing main change")

    receipt = candidate.compute_candidate(1, base, head, repo)
    outcome = candidate.evaluate_candidate(receipt, new_base, head, repo)
    assert outcome["candidate"]["mergeable"] is False
    assert outcome["candidate"]["conflicted_paths"] == ["revocompute/result_audit.py"]
    # A conflicting candidate can never carry evidence forward.
    assert outcome["decision"]["carry_forward"] is False
    assert outcome["decision"]["required_gate"] == candidate.GATE_FULL


# --------------------------------------------------------------------------- #
# Drift classification
# --------------------------------------------------------------------------- #


def _drift(**kwargs):
    arguments = {
        "pr_paths": ["revocompute/result_audit.py"],
        "advanced_paths": [],
        "patch_identity_unchanged": True,
        "dependency_surface": (),
        "previous_review_result": "approved",
    }
    arguments.update(kwargs)
    return candidate.classify_drift(**arguments)


def test_unrelated_main_advance_is_class_zero_and_carries_review_forward():
    decision = _drift(advanced_paths=["frontend/src/routes/catalog.ts"])
    assert decision["drift_class"] == candidate.CLASS_NONE
    assert decision["carry_forward"] is True
    assert decision["required_gate"] == candidate.GATE_DELTA


def test_same_subsystem_advance_is_class_one_and_keeps_a_delta_gate():
    decision = _drift(advanced_paths=["revocompute/result_inventory.py"])
    assert decision["drift_class"] == candidate.CLASS_SUBSYSTEM
    assert decision["carry_forward"] is True
    assert decision["required_gate"] == candidate.GATE_DELTA


def test_direct_file_overlap_is_class_two_and_refuses_carry_forward():
    decision = _drift(advanced_paths=["revocompute/result_audit.py"])
    assert decision["drift_class"] == candidate.CLASS_OVERLAP
    assert decision["carry_forward"] is False
    assert decision["required_gate"] == candidate.GATE_FULL


def test_declared_dependency_surface_overlap_is_class_two():
    decision = _drift(
        advanced_paths=["revocompute/runtime_bundle.py"],
        dependency_surface=["revocompute/runtime_bundle.py"],
    )
    assert decision["drift_class"] == candidate.CLASS_OVERLAP
    assert decision["carry_forward"] is False


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/tests.yml",
        "revocompute/static/openapi.json",
        "revocompute/auth.py",
        "tools/classify_ci_scope.py",
    ],
)
def test_global_invalidator_escalates_to_full_review(path):
    decision = _drift(advanced_paths=[path])
    assert decision["drift_class"] == candidate.CLASS_GLOBAL
    assert decision["carry_forward"] is False
    assert decision["required_gate"] == candidate.GATE_FULL


def test_changed_patch_content_invalidates_prior_review():
    decision = _drift(patch_identity_unchanged=False, advanced_paths=["frontend/src/x.ts"])
    assert decision["drift_class"] == candidate.CLASS_OVERLAP
    assert decision["carry_forward"] is False
    assert decision["required_gate"] == candidate.GATE_FULL


def test_non_adoptable_prior_review_cannot_carry_forward():
    decision = _drift(previous_review_result="changes_requested")
    assert decision["carry_forward"] is False
    assert decision["required_gate"] == candidate.GATE_FULL


def test_unclassifiable_base_relationship_fails_closed():
    decision = _drift(advanced_paths=None)
    assert decision["drift_class"] == candidate.CLASS_GLOBAL
    assert decision["carry_forward"] is False
    assert decision["required_gate"] == candidate.GATE_FULL


# --------------------------------------------------------------------------- #
# End-to-end: the content-identical rebase scenario
# --------------------------------------------------------------------------- #


def test_content_identical_rebase_carries_review_and_records_a_fresh_gate(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "revocompute/result_audit.py", "value = 2\n")
    head = _commit(repo, "pr change")

    # A real merge-grade review receipt at the reviewed head/base.
    receipt = candidate.compute_candidate(69, base, head, repo)
    receipt["review_result"] = "approved"
    assert receipt["lanes"] == ["server"]
    assert receipt["mergeable"] is True

    # main advances elsewhere and the PR is rebased: content identical.
    _git(repo, "checkout", "-q", "main")
    _write(repo, "frontend/src/app.js", "console.log('b');\n")
    new_base = _commit(repo, "unrelated advance")
    _git(repo, "checkout", "-q", "pr")
    _git(repo, "rebase", "-q", "main")
    rebased_head = _git(repo, "rev-parse", "HEAD")

    outcome = candidate.evaluate_candidate(receipt, new_base, rebased_head, repo)
    decision = outcome["decision"]
    assert decision["patch_identity_unchanged"] is True
    assert decision["drift_class"] == candidate.CLASS_NONE
    assert decision["carry_forward"] is True
    assert decision["required_gate"] == candidate.GATE_DELTA
    # The audit trail names both heads explicitly: the carried review is not
    # relabeled as a review of the new SHA.
    assert decision["reviewed_head_sha"] == head
    assert decision["current_head_sha"] == rebased_head
    assert outcome["candidate"]["base_sha"] == new_base


def test_global_invalidator_after_rebase_escalates(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "pr")
    _write(repo, "revocompute/result_audit.py", "value = 2\n")
    head = _commit(repo, "pr change")
    receipt = candidate.compute_candidate(69, base, head, repo)

    _git(repo, "checkout", "-q", "main")
    _write(repo, "pyproject.toml", "[project]\nname = 'x'\n")
    new_base = _commit(repo, "dependency policy change")
    _git(repo, "checkout", "-q", "pr")
    _git(repo, "rebase", "-q", "main")
    rebased_head = _git(repo, "rev-parse", "HEAD")

    outcome = candidate.evaluate_candidate(receipt, new_base, rebased_head, repo)
    assert outcome["decision"]["drift_class"] == candidate.CLASS_GLOBAL
    assert outcome["decision"]["carry_forward"] is False
    assert outcome["decision"]["required_gate"] == candidate.GATE_FULL


def test_evaluate_rejects_an_incomplete_receipt(repo):
    with pytest.raises(candidate.CandidateError):
        candidate.evaluate_candidate({"head_sha": "a" * 40}, "b" * 40, "c" * 40, repo)


def test_cli_fails_closed_with_exit_four_on_unreadable_range(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"patch_digest": "x" * 64, "base_sha": "not-a-sha", "head_sha": "also-not"}), encoding="utf-8")
    assert candidate.main(["drift", "--base", "nope", "--head", "nope", "--receipt", str(receipt)]) == 4
