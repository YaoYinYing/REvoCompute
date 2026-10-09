#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Merge-candidate identity, drift classification, and bounded evidence carry-forward.

A reviewed PR does not become unreviewed because unrelated commits landed on
``main``. This module computes the few identities that let the protocol decide
*which* evidence a base advance actually invalidates, instead of rebasing,
rerunning, and re-reviewing everything:

``patch_digest``
    sha256 of canonical NUL-delimited raw Git transitions against the merge base.
    Every record includes the exact path, old/new mode and full old/new blob ID.
    Rename detection is disabled: both deletion and addition are represented.
    Older human-patch receipts cannot authorize content-review carry-forward.

``changed_paths_digest``
    sha256 over the sorted three-dot changed paths.

``merge_tree_oid``
    the tree a real merge of head into base would produce
    (``git merge-tree --write-tree``), reported only when the merge has no
    conflicts. This is the current-base integration identity: it proves the
    exact head still composes with the exact base, without rewriting the PR's
    development branch.

Drift classification mirrors the protocol's Class 0-3 model. Given the paths
``main`` gained between the reviewed base and the current base, it answers
whether the advance is irrelevant (Class 0), same-subsystem but non-overlapping
(Class 1), directly overlapping or dependency-surface (Class 2), or a global
invalidator (Class 3). Unknown inputs fail closed to Class 3.

Every entry point is fail-closed: an unreadable repository, an unresolvable
range, or an unrecognized path produces the broader answer (fresh full review),
never the narrower one.

CLI::

    campaign_merge_candidate.py compute --pr 69 --base <sha> --head <sha>
    campaign_merge_candidate.py drift --pr 69 --base <new-base> --head <sha> --receipt <receipt.json>
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

# Base-drift classes, matching the Multi-agent Campaign Protocol.
CLASS_NONE = "C0"  # no relevant drift
CLASS_SUBSYSTEM = "C1"  # same subsystem, no content overlap
CLASS_OVERLAP = "C2"  # direct overlap or dependency-surface change
CLASS_GLOBAL = "C3"  # global invalidator

DRIFT_CLASSES = (CLASS_NONE, CLASS_SUBSYSTEM, CLASS_OVERLAP, CLASS_GLOBAL)

GATE_DELTA = "delta"  # bounded exact-head integration/delta gate
GATE_FULL = "full"  # fresh full merge-grade review

# Prior review outcomes that may be carried forward.
REVIEW_RESULTS_ADOPTABLE = frozenset({"approved", "clean", "pass"})

# Paths whose change on the base invalidates prior *integration* evidence for
# every PR: build system, dependency resolution, CI policy, shared trust and
# persistence boundaries, shared schema/protocol, and the campaign protocol
# itself. This is the protocol's Class 3 applied to base movement.
GLOBAL_INVALIDATOR_GLOBS = (
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    ".coveragerc",
    "codecov.yml",
    ".gitattributes",
    ".gitignore",
    ".github/*",
    ".github/**",
    "docker-compose.yml",
    "docker-compose.slurm.yml",
    ".dockerignore",
    ".env.example",
    "mkdocs.yml",
    "CLAUDE.md",
    "docs/agents/long-task-handling.md",
    "tools/classify_ci_scope.py",
    "tools/campaign_merge_candidate.py",
    "revocompute/static/openapi.json",
    "revocompute/schemas.py",
    "revocompute/schema_epoch.py",
    "revocompute/auth.py",
    "revocompute/access_control.py",
    "revocompute/access_guard.py",
    "revocompute/ingress_security.py",
    "revocompute/trusted_proxy.py",
    "revocompute/admission.py",
    "revocompute/db.py",
    "revocompute/storage.py",
    "revocompute/io_contracts.py",
    "revocompute/resource_*.py",
    "revocompute/input_validators/*",
    "revocompute/input_validators/**",
    "revocompute/plugins/*",
    "revocompute/plugins/**",
    "revocompute/task_types/*",
    "revocompute/task_types/**",
    "docker/runners/common/*",
    "docker/runners/common/**",
    "docker/server/*",
    "docker/nginx/*",
)


class CandidateError(RuntimeError):
    """The candidate identity or drift class cannot be established safely."""


# --------------------------------------------------------------------------- #
# git plumbing
# --------------------------------------------------------------------------- #


def _git(args, cwd=None):
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd) if cwd else None,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError(f"git {' '.join(args)} failed: {error}") from error
    return result.stdout


def _git_bytes(args, cwd=None) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            check=True,
            cwd=str(cwd) if cwd else None,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateError(f"git {' '.join(args)} failed: {error}") from error
    return result.stdout


def _require_sha(value: str, label: str) -> str:
    candidate = (value or "").strip()
    if not candidate or set(candidate) == {"0"}:
        raise CandidateError(f"{label} is missing or a zero SHA")
    return candidate


def merge_base(base: str, head: str, cwd=None) -> str:
    """Return the merge base of ``base`` and ``head``."""
    return _git(["merge-base", _require_sha(base, "base"), _require_sha(head, "head")], cwd).strip()


def _transition_policy():
    spec = importlib.util.spec_from_file_location("classify_ci_scope", TOOLS_DIR / "classify_ci_scope.py")
    if spec is None or spec.loader is None:
        raise CandidateError("transition policy unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _transitions(base: str, head: str, cwd=None, *, merge_base=True):
    try:
        return _transition_policy().file_transitions(
            _require_sha(base, "base"), _require_sha(head, "head"), cwd, merge_base=merge_base,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise CandidateError(f"cannot establish file transitions: {error}") from error


def changed_paths(base: str, head: str, cwd=None):
    """All endpoints of the PR's canonical raw file transitions."""
    return _transition_policy().transition_paths(_transitions(base, head, cwd))


def patch_digest(base: str, head: str, cwd=None) -> str:
    """Exact path/mode/type/before-and-after blob transition identity."""
    records = _transitions(base, head, cwd)
    _transition_policy().transition_paths(records)
    fields = records.split(b"\0")
    pairs = sorted(zip(fields[0:-1:2], fields[1:-1:2]), key=lambda pair: pair[1])
    canonical = b"".join(metadata + b"\0" + path + b"\0" for metadata, path in pairs)
    return hashlib.sha256(b"git-raw-transition-v1\0" + canonical).hexdigest()


def changed_paths_digest(paths) -> str:
    """sha256 over the sorted changed-path list."""
    payload = json.dumps(sorted(paths), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def merge_tree(base: str, head: str, cwd=None):
    """Return ``(merged_tree_oid, conflicted_paths)`` for merging head into base.

    The merged tree is reported even when the merge conflicts -- it is the
    candidate tree the merge would produce -- but callers must treat a non-empty
    conflict list as a hard stop: an unmergeable candidate cannot enter the
    merge frontier, and its integration evidence cannot be trusted.
    """
    base_sha = _require_sha(base, "base")
    head_sha = _require_sha(head, "head")
    try:
        result = subprocess.run(
            ["git", "merge-tree", "--write-tree", "--name-only", base_sha, head_sha],
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
    except OSError as error:
        raise CandidateError(f"git merge-tree failed: {error}") from error
    # Exit status 1 with usable output means conflicts; anything else with no
    # parseable tree is an error, not an empty conflict list.
    lines = [line.strip() for line in result.stdout.splitlines()]
    if not lines or len(lines[0]) != 40:
        raise CandidateError(f"git merge-tree produced no tree: {result.stderr.strip()}")
    tree_oid = lines[0]
    conflicts = sorted(
        line for line in lines[1:] if line and not line.startswith("Auto-merging") and not line.startswith("CONFLICT")
    )
    if result.returncode not in (0, 1):
        raise CandidateError(f"git merge-tree exited {result.returncode}: {result.stderr.strip()}")
    if result.returncode == 0:
        conflicts = []
    return tree_oid, conflicts


def advance_paths(old_base: str, new_base: str, cwd=None):
    """Return the paths ``main`` gained between two base commits.

    ``None`` when the relationship cannot be established (the old base is not an
    ancestor of the new base, or the range is unreadable), which callers must
    treat as unclassifiable rather than as "no drift".
    """
    old_sha = _require_sha(old_base, "reviewed base")
    new_sha = _require_sha(new_base, "current base")
    if old_sha == new_sha:
        return []
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", old_sha, new_sha],
            capture_output=True,
            cwd=str(cwd) if cwd else None,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        output = _transitions(old_sha, new_sha, cwd, merge_base=False)
    except CandidateError:
        return None
    return _transition_policy().transition_paths(output)


# --------------------------------------------------------------------------- #
# Drift classification
# --------------------------------------------------------------------------- #


def _subsystem(path: str) -> str:
    """Return a coarse subsystem key for one changed path.

    Two paths share a subsystem when they touch the same area of the repository:
    the same top-level tree, the same runner family, or the same significant
    subpackage. This is what the Class 1 drift class means in practice — the base
    moved nearby without touching the PR's own files, so a bounded delta review
    is enough but unrelated CI lanes need not rerun.

    Helper module names collapse to their tree, because ``result_audit.py`` and
    ``result_inventory.py`` are the same area while ``result_audit.py`` and
    ``task_runtime.py`` are not.
    """
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "unknown"
    head = parts[0]
    if head == "docker":
        if len(parts) >= 3 and parts[1] == "runners":
            return f"docker/runners/{parts[2]}" if parts[2] != "common" else "docker/runners/common"
        return "/".join(parts[:2]) if len(parts) > 1 else "docker"
    if head in ("tests", "docs", "frontend", "tools", "run", "config", "image", "nginx_sites"):
        return head
    if head == "revocompute":
        if len(parts) < 2:
            return "revocompute"
        leaf = parts[1]
        if len(parts) > 2 and leaf in ("job", "maintenance", "plugins", "task_types", "input_validators", "templates", "legal"):
            return f"revocompute/{leaf}"
        if leaf.endswith(".py"):
            # Two modules that differ only by a trailing part share a subsystem.
            stem = leaf[:-3]
            for token in ("result_", "runner_", "resource_", "operator_", "tool_"):
                if stem.startswith(token):
                    return f"revocompute/{token}"
            return leaf
        return f"revocompute/{leaf}"
    if head.lower().endswith((".md", ".toml", ".yml", ".yaml", ".json", ".sh")):
        return "<root>"
    return head


def _matches(path: str, patterns) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def is_global_invalidator(path: str) -> bool:
    """True when a base change to ``path`` invalidates every PR's integration evidence."""
    return _matches(path, GLOBAL_INVALIDATOR_GLOBS)


def dependency_overlap(paths, dependency_surface) -> bool:
    """True when any advanced path matches a declared dependency-surface pattern."""
    return any(_matches(path, dependency_surface) for path in paths)


def classify_drift(
    *,
    pr_paths,
    advanced_paths,
    patch_identity_unchanged: bool,
    dependency_surface=(),
    previous_review_result: str = "approved",
):
    """Classify a base advance and decide whether prior content review carries forward.

    Pure function: callers supply the PR's changed paths and the paths the base
    gained. Returns a decision dictionary. Unknown or missing inputs fail closed.
    """
    decision = {
        "drift_class": CLASS_GLOBAL,
        "drift_paths": [],
        "carry_forward": False,
        "required_gate": GATE_FULL,
        "reason": "",
    }
    if advanced_paths is None or pr_paths is None:
        decision["reason"] = "base advance could not be classified; fail closed"
        return decision

    advanced = sorted({path for path in advanced_paths if path})
    decision["drift_paths"] = advanced

    if not patch_identity_unchanged:
        decision["drift_class"] = CLASS_OVERLAP
        decision["reason"] = "patch content changed since the reviewed digest; prior review is stale"
        return decision

    if (previous_review_result or "").strip().lower() not in REVIEW_RESULTS_ADOPTABLE:
        decision["drift_class"] = CLASS_OVERLAP
        decision["reason"] = "previous review did not reach an adoptable result"
        return decision

    if any(is_global_invalidator(path) for path in advanced):
        decision["drift_class"] = CLASS_GLOBAL
        decision["reason"] = "base gained a global invalidator"
        return decision

    overlap = sorted(set(advanced) & set(pr_paths))
    if overlap:
        decision["drift_class"] = CLASS_OVERLAP
        decision["reason"] = f"base changed the same files: {', '.join(overlap[:5])}"
        return decision

    if dependency_overlap(advanced, dependency_surface):
        decision["drift_class"] = CLASS_OVERLAP
        decision["reason"] = "base changed a declared dependency surface"
        return decision

    if not advanced:
        decision["drift_class"] = CLASS_NONE
        decision["reason"] = "base did not move"
    else:
        pr_subsystems = {_subsystem(path) for path in pr_paths}
        advanced_subsystems = {_subsystem(path) for path in advanced}
        if pr_subsystems & advanced_subsystems:
            decision["drift_class"] = CLASS_SUBSYSTEM
            decision["reason"] = "base moved inside the PR's subsystem without touching its files"
        else:
            decision["drift_class"] = CLASS_NONE
            decision["reason"] = "base moved in unrelated subsystems"

    if decision["drift_class"] in (CLASS_NONE, CLASS_SUBSYSTEM):
        decision["carry_forward"] = True
        decision["required_gate"] = GATE_DELTA
    return decision


# --------------------------------------------------------------------------- #
# Receipt / candidate
# --------------------------------------------------------------------------- #


def _classify_lanes(paths):
    """Ask the single CI-scope classifier which validation lanes these paths reach."""
    spec = importlib.util.spec_from_file_location("classify_ci_scope", TOOLS_DIR / "classify_ci_scope.py")
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise CandidateError("CI-scope classifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return sorted(module.classify_paths(paths))


def compute_candidate(pr: int | None, base: str, head: str, cwd=None, private_recheck: bool = False) -> dict:
    """Compute the merge-candidate identity for one PR at an exact base and head.

    ``private_recheck`` marks a merge candidate reconstructed in review-private
    storage rather than in a Campaign worktree, so only that class is disclosed.
    """
    base_sha = _require_sha(base, "base")
    head_sha = _require_sha(head, "head")
    paths = changed_paths(base_sha, head_sha, cwd)
    tree_oid, conflicts = merge_tree(base_sha, head_sha, cwd)
    return {
        "pr": pr,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "merge_base_sha": merge_base(base_sha, head_sha, cwd),
        "patch_digest": patch_digest(base_sha, head_sha, cwd),
        "identity_format": "git-raw-transition-v1",
        "changed_paths": paths,
        "changed_paths_digest": changed_paths_digest(paths),
        "merge_tree_oid": tree_oid,
        "mergeable": not conflicts,
        "conflicted_paths": conflicts,
        "lanes": (sorted(_transition_policy().ALL_LANES)
                  if _transition_policy().transition_requires_full(_transitions(base_sha, head_sha, cwd))
                  else _classify_lanes(paths)),
        "merges_main": False,
        "private_recheck": bool(private_recheck),
    }


def load_receipt(source: str) -> dict:
    """Load a prior review receipt from a path or an inline JSON object."""
    text = source
    if not source.lstrip().startswith("{"):
        candidate = Path(source)
        if not candidate.is_file():
            raise CandidateError(f"receipt not found: {source}")
        text = candidate.read_text(encoding="utf-8")
    try:
        receipt = json.loads(text)
    except json.JSONDecodeError as error:
        raise CandidateError(f"receipt is not valid JSON: {error.msg}") from error
    if not isinstance(receipt, dict):
        raise CandidateError("receipt must be a JSON object")
    return receipt


REQUIRED_RECEIPT_FIELDS = ("patch_digest", "base_sha", "head_sha")


def evaluate_candidate(receipt: dict, current_base: str, head: str, cwd=None) -> dict:
    """Produce a fresh exact-head candidate receipt plus a drift decision.

    Fails closed: when any input is missing, unknown, or unclassifiable, the
    decision requires a fresh full review and ``mergeable`` is False.
    """
    for field in REQUIRED_RECEIPT_FIELDS:
        if not receipt.get(field):
            raise CandidateError(f"prior receipt is missing {field}")

    try:
        candidate = compute_candidate(receipt.get("pr"), current_base, head, cwd)
        advanced = advance_paths(receipt["base_sha"], current_base, cwd)
    except CandidateError as error:
        return {
            "decision": {
                "drift_class": CLASS_GLOBAL,
                "drift_paths": [],
                "carry_forward": False,
                "required_gate": GATE_FULL,
                "reason": f"unclassifiable: {error}",
            },
            "candidate": None,
            "mergeable": False,
        }

    decision = classify_drift(
        pr_paths=candidate["changed_paths"],
        advanced_paths=advanced,
        patch_identity_unchanged=(receipt.get("identity_format") == "git-raw-transition-v1"
                                  and candidate["patch_digest"] == receipt["patch_digest"]),
        dependency_surface=receipt.get("dependency_surface") or (),
        previous_review_result=receipt.get("review_result", "approved"),
    )
    if advanced is not None and _transition_policy().transition_requires_full(
        _transitions(receipt["base_sha"], current_base, cwd, merge_base=False)
    ):
        decision.update(drift_class=CLASS_GLOBAL, carry_forward=False, required_gate=GATE_FULL,
                        reason="base gained a mode/type transition")
    decision["patch_identity_unchanged"] = (receipt.get("identity_format") == "git-raw-transition-v1"
                                            and candidate["patch_digest"] == receipt["patch_digest"])
    decision["reviewed_head_sha"] = receipt["head_sha"]
    decision["current_head_sha"] = candidate["head_sha"]

    # A conflicting merge is a hard stop regardless of drift class.
    if not candidate["mergeable"]:
        decision["carry_forward"] = False
        decision["required_gate"] = GATE_FULL
        decision["reason"] = f"{decision['reason']}; merge conflicts in {', '.join(candidate['conflicted_paths'][:5])}"

    candidate["review"] = decision
    return {"decision": decision, "candidate": candidate, "mergeable": candidate["mergeable"]}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _cmd_compute(args) -> int:
    candidate = compute_candidate(args.pr, args.base, args.head, private_recheck=args.private_recheck)
    print(json.dumps(candidate, indent=2, sort_keys=True))
    return 0


def _cmd_drift(args) -> int:
    receipt = load_receipt(args.receipt)
    outcome = evaluate_candidate(receipt, args.base, args.head)
    print(json.dumps(outcome, indent=2, sort_keys=True))
    decision = outcome["decision"]
    if not outcome["mergeable"]:
        return 4
    if decision["required_gate"] == GATE_DELTA and decision["carry_forward"]:
        return 0
    return 3


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    compute = sub.add_parser("compute", help="candidate identity for an exact base/head")
    compute.add_argument("--pr", type=int, default=None)
    compute.add_argument("--base", required=True)
    compute.add_argument("--head", required=True)
    compute.add_argument("--private-recheck", action="store_true", help="candidate lives in review-private storage")
    compute.set_defaults(func=_cmd_compute)

    drift = sub.add_parser("drift", help="classify base drift against a prior review receipt")
    drift.add_argument("--base", required=True, help="current base (main) SHA")
    drift.add_argument("--head", required=True, help="PR head SHA")
    drift.add_argument("--receipt", required=True, help="prior review receipt (path or inline JSON)")
    drift.set_defaults(func=_cmd_drift)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CandidateError as error:
        print(f"cannot establish candidate safely: {error}", file=sys.stderr)
        # Exit 4 is the fail-closed answer: run the full merge-grade gate.
        return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
