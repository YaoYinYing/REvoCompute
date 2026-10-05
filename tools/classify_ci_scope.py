#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Classify a change set as documentation-only so CI can skip the heavy matrix.

Documentation-only changes cannot affect the code, fixtures, or runtime behavior
the heavy suites exercise, so the ``REvoCompute Tests`` workflow runs them only
when the change set touches something else. The classifier is intentionally
narrow and fails safe: anything that is not provably a safe documentation path --
including an undeterminable, empty, or ambiguous change set -- keeps the full
suite enabled.

Run from the workflow as::

    python3 tools/classify_ci_scope.py --event <name> --base <sha> --head <sha>

and it writes ``run_tests=true|false`` to ``$GITHUB_OUTPUT`` (and stdout).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Exact paths that are documentation-only: the docs site config and the docs
# workflow. Every other workflow file, including this workflow's own
# ``.github/workflows/tests.yml``, forces the full matrix.
DOC_ONLY_FILES = frozenset({"mkdocs.yml", ".github/workflows/docs.yml"})

EVENTS = ("workflow_dispatch", "push", "pull_request")

_ZERO_SHA = "0" * 40


def _is_doc_only_path(path: str) -> bool:
    """Return True only for a path in an explicitly safe documentation class."""
    candidate = path.strip()
    if not candidate:
        return False
    if candidate in DOC_ONLY_FILES:
        return True
    if candidate == "docs" or candidate.startswith("docs/"):
        return True
    # Markdown anywhere, including runner READMEs.
    return candidate.lower().endswith(".md")


def is_documentation_only(paths) -> bool:
    """True when every changed path is documentation-only.

    An empty or missing change set is not documentation-only -- it is unknown, so
    the caller must keep the full matrix enabled.
    """
    if not paths:
        return False
    return all(_is_doc_only_path(path) for path in paths)


def _parse_name_only(output: str):
    return [line.strip() for line in output.splitlines() if line.strip()]


def changed_paths(base: str, head: str):
    """Return the changed paths for ``base..head``, or None if undeterminable.

    None (missing/zero SHAs, a git error) means the classifier cannot prove the
    change set is documentation-only, so the full suite must run.
    """
    if not base or not head:
        return None
    if base == _ZERO_SHA or head == _ZERO_SHA:
        return None
    # Three-dot diff against the merge base: the PR's own changes, not unrelated
    # commits that landed on the base branch meanwhile.
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return _parse_name_only(result.stdout)


def decide(event: str, base: str, head: str, paths) -> bool:
    """Return ``run_tests``: True keeps the full matrix, False skips it."""
    if event == "workflow_dispatch":
        return True
    if paths is not None:
        return not is_documentation_only(paths)
    if event in ("push", "pull_request"):
        return not is_documentation_only(changed_paths(base, head) or [])
    # Unknown event or explicit path list supplied for a manual check.
    return True


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, help="GitHub event name")
    parser.add_argument("--base", default="", help="Base SHA for the change range")
    parser.add_argument("--head", default="", help="Head SHA for the change range")
    parser.add_argument(
        "--paths",
        default=None,
        help="Comma-separated explicit paths (manual check; bypasses git)",
    )
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
        help="Path to write run_tests to (defaults to $GITHUB_OUTPUT)",
    )
    args = parser.parse_args(argv)

    paths = None
    if args.paths is not None:
        paths = [p for p in (item.strip() for item in args.paths.split(",")) if p]

    run_tests = decide(args.event, args.base, args.head, paths)
    value = "true" if run_tests else "false"
    print(f"run_tests={value}")
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"run_tests={value}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
