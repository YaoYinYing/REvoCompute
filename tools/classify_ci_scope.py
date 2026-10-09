#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Classify a change set into the CI validation lanes it can affect.

This module is the single source of truth for which expensive CI lane a change
set must pay for. Workflows consume its output instead of carrying their own
path filters, so there is exactly one place to audit the policy.

Lanes
-----

``docs``               documentation site build and repository layout check
``server``             server/contract pytest suite, coverage, registry determinism
``runner_scientific``  GREMLIN_LH upstream-equivalence scientific acceptance
``browser``            frontend typecheck/unit/build plus Playwright contracts
``compose``            deployment-controller contracts and the Compose full stack

Policy
------

A lane runs when the change set can reach the behavior it validates. The
classifier is deliberately conservative and **fails closed**: a path it cannot
place in the taxonomy, an empty or undeterminable change set, or a manual
dispatch selects every lane. Narrowing is only ever allowed for a path the
policy can prove is isolated.

Groups, in resolution order: a documentation-only file (``mkdocs.yml`` and the
docs workflow stay documentation because their own lane validates them); a
build/CI/coverage file or anything under ``.github/``; documentation paths
(``docs/**`` and markdown anywhere); the server system-boundary set (auth,
ingress, input validation, schema/plugin kernel, resource accounting, database
and storage, the published OpenAPI document) which selects every lane because a
defect there invalidates unrelated lanes' assumptions; container and deployment
paths; the deployment controller and server configuration; Tool runtimes; runner
families (scientific families also select the scientific lane, shared runner
infrastructure selects it too); the frontend tree; test trees; and the server
package, where controller/scheduler surfaces additionally select ``compose`` and
the surfaces the Playwright contracts exercise additionally select ``browser``.

Run from a workflow as::

    python3 tools/classify_ci_scope.py --event <name> --base <sha> --head <sha>

It prints ``lanes=``, ``full=``, and one ``<lane>=true|false`` line per lane to
stdout and appends the same lines to ``$GITHUB_OUTPUT``. ``--paths`` classifies
an explicit comma-separated change set instead of reading git, which is how a
manual check and the merge-candidate tool ask the same question.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

# --------------------------------------------------------------------------- #
# Lane vocabulary
# --------------------------------------------------------------------------- #

LANES = ("docs", "server", "runner_scientific", "browser", "compose")

ALL_LANES = frozenset(LANES)

# --------------------------------------------------------------------------- #
# Policy tables
# --------------------------------------------------------------------------- #

# Documentation-only exact paths. The docs site config and the docs workflow are
# validated by the docs lane itself, so they do not imply code lanes. Every other
# workflow is a build-system change and selects every lane.
DOC_ONLY_FILES = frozenset({"mkdocs.yml", ".github/workflows/docs.yml"})

# Build-system, dependency-resolution, coverage, and CI-policy paths: any change
# invalidates the assumptions every lane makes.
FULL_MATRIX_FILES = frozenset(
    {"pyproject.toml", "uv.lock", ".coveragerc", "codecov.yml", "Makefile", ".gitattributes", ".gitignore"}
)
FULL_MATRIX_PREFIXES = (".github/",)

# Server system-boundary surfaces. A defect here can invalidate unrelated lanes'
# assumptions (trust, persistence, shared schema, accounting), so they select
# every lane rather than a narrower set.
SYSTEM_BOUNDARY_FILES = frozenset(
    {
        "revocompute/api_receipt.py",
        "revocompute/admission.py",
        "revocompute/auth.py",
        "revocompute/access_control.py",
        "revocompute/access_guard.py",
        "revocompute/client_ip.py",
        "revocompute/db.py",
        "revocompute/ingress_security.py",
        "revocompute/io_contracts.py",
        "revocompute/manage_db.py",
        "revocompute/ratelimit.py",
        "revocompute/resource_audit.py",
        "revocompute/resource_ledger.py",
        "revocompute/resource_lifecycle.py",
        "revocompute/resource_model.py",
        "revocompute/resource_observations.py",
        "revocompute/resource_policy.py",
        "revocompute/schema_epoch.py",
        "revocompute/schemas.py",
        "revocompute/serialization.py",
        "revocompute/static/openapi.json",
        "revocompute/storage.py",
        "revocompute/trusted_proxy.py",
    }
)
SYSTEM_BOUNDARY_PREFIXES = (
    "revocompute/input_validators/",
    "revocompute/plugins/",
    "revocompute/task_types/",
)

# Container, deployment, and host-facing configuration.
COMPOSE_FILES = frozenset(
    {".dockerignore", ".env.example", "docker-compose.yml", "docker-compose.slurm.yml"}
)
COMPOSE_PREFIXES = ("docker/nginx/", "docker/server/", "image/", "nginx_sites/")

# Runner families whose scientific acceptance the ``runner_scientific`` lane
# validates, and the Runner infrastructure it shares.
SCIENTIFIC_RUNNER_FAMILIES = frozenset({"gremlin_lh", "pssm_gremlin"})
SCIENTIFIC_RUNNER_PREFIXES = tuple(f"docker/runners/{family}/" for family in sorted(SCIENTIFIC_RUNNER_FAMILIES))
SCIENTIFIC_FIXTURE_PREFIXES = tuple(f"tests/data/{family}/" for family in sorted(SCIENTIFIC_RUNNER_FAMILIES))
SCIENTIFIC_TEST_PREFIXES = tuple(f"tests/runners/{family}/" for family in sorted(SCIENTIFIC_RUNNER_FAMILIES))

# Server surfaces the deployment controller and full-stack gate exercise end to
# end (submission, scheduling, bundles, maintenance, operator control).
CONTROL_PREFIXES = (
    "revocompute/job/",
    "revocompute/maintenance/",
    "revocompute/operator_",
    "revocompute/runner_bundles.py",
    "revocompute/runner_host.py",
    "revocompute/runtime_bundle.py",
    "revocompute/task_runtime.py",
)
CONTROL_FILES = frozenset({"revocompute/compose.py"})

# Server surfaces an API or projection change reaches through the browser.
BROWSER_SURFACE_FILES = frozenset(
    {
        "revocompute/app.py",
        "revocompute/result_projection.py",
        "revocompute/result_storyboard.py",
        "revocompute/routes.py",
        "revocompute/runner_admin_view.py",
        "revocompute/workspace_contracts.py",
    }
)
BROWSER_SURFACE_PREFIXES = ("revocompute/templates/",)

# Test paths that the Playwright contracts consume.
BROWSER_TEST_PREFIXES = ("tests/frontend_fixtures/",)
BROWSER_TEST_FILES = frozenset({"tests/browser_frontend_assets.py"})

EVENTS = ("workflow_dispatch", "push", "pull_request")

_ZERO_SHA = "0" * 40


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def _normalize(path: str) -> str:
    candidate = path
    while candidate.startswith("./"):
        candidate = candidate[2:]
    return candidate.lstrip("/")


def _under(path: str, prefixes) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in prefixes)


def _classify_path(path: str) -> frozenset[str]:
    """Return the lanes one path selects, or every lane when it is unrecognized."""
    candidate = _normalize(path)
    if not candidate:
        return ALL_LANES
    if candidate in DOC_ONLY_FILES:
        return frozenset({"docs"})
    if candidate in FULL_MATRIX_FILES or _under(candidate, FULL_MATRIX_PREFIXES):
        return ALL_LANES
    if candidate == "docs" or candidate.startswith("docs/") or candidate.lower().endswith(".md"):
        return frozenset({"docs"})
    if candidate in SYSTEM_BOUNDARY_FILES or _under(candidate, SYSTEM_BOUNDARY_PREFIXES):
        return ALL_LANES
    if candidate in COMPOSE_FILES or _under(candidate, COMPOSE_PREFIXES):
        return frozenset({"compose"})
    if candidate == "config" or candidate.startswith("config/") or candidate == "run" or candidate.startswith("run/"):
        return frozenset({"server", "compose"})
    if candidate == "docker/tools" or candidate.startswith("docker/tools/"):
        return frozenset({"server", "compose"})
    if candidate == "docker/runners/common" or candidate.startswith("docker/runners/common/"):
        return frozenset({"server", "runner_scientific"})
    if _under(candidate, SCIENTIFIC_RUNNER_PREFIXES):
        return frozenset({"server", "runner_scientific"})
    if candidate == "docker/runners" or candidate.startswith("docker/runners/"):
        return frozenset({"server"})
    if candidate == "frontend" or candidate.startswith("frontend/"):
        return frozenset({"browser"})
    if _under(candidate, SCIENTIFIC_FIXTURE_PREFIXES) or _under(candidate, SCIENTIFIC_TEST_PREFIXES):
        return frozenset({"server", "runner_scientific"})
    if _under(candidate, BROWSER_TEST_PREFIXES) or candidate in BROWSER_TEST_FILES:
        return frozenset({"server", "browser"})
    if candidate == "tests" or candidate.startswith("tests/"):
        if candidate.startswith("tests/test_playwright_") or any(
            surface in candidate for surface in ("task", "result", "workspace")
        ):
            return frozenset({"server", "browser"})
        return frozenset({"server"})
    if candidate == "tools" or candidate.startswith("tools/"):
        return frozenset({"server"})
    if candidate == "revocompute" or candidate.startswith("revocompute/"):
        lanes = {"server"}
        if candidate in CONTROL_FILES or _under(candidate, CONTROL_PREFIXES):
            lanes.add("compose")
        if candidate in BROWSER_SURFACE_FILES or _under(candidate, BROWSER_SURFACE_PREFIXES):
            lanes.add("browser")
        return frozenset(lanes)
    # Unrecognized path: fail closed.
    return ALL_LANES


def classify_paths(paths) -> frozenset[str]:
    """Return the union of lanes selected by ``paths``.

    An empty or missing change set is unknown, not empty: every lane runs.
    """
    if not paths:
        return ALL_LANES
    lanes: set[str] = set()
    for path in paths:
        lanes |= _classify_path(path)
    return frozenset(lanes)


def file_transitions(base: str, head: str, cwd=None, *, merge_base=True) -> bytes:
    """Canonical raw transitions: exact paths, modes and full before/after blob IDs.

    Disable rename detection deliberately: a rename is a deletion plus addition,
    so both endpoints remain visible regardless of Git similarity heuristics.
    NUL delimiters preserve whitespace and newlines in paths.
    """
    if not base or not head or base == _ZERO_SHA or head == _ZERO_SHA:
        raise ValueError("missing or zero revision")
    revision = [f"{base}...{head}"] if merge_base else [base, head]
    return subprocess.run(
        ["git", "diff", "--raw", "--no-abbrev", "--no-renames", "--no-ext-diff",
         "--no-textconv", "--no-relative", "--ignore-submodules=none", "-z", *revision, "--"],
        capture_output=True, check=True, cwd=cwd,
    ).stdout


def transition_paths(records: bytes):
    fields = records.split(b"\0")
    if fields[-1] != b"" or (len(fields) - 1) % 2:
        raise ValueError("malformed raw transitions")
    paths = []
    for metadata, path in zip(fields[0:-1:2], fields[1:-1:2]):
        if not metadata.startswith(b":") or len(metadata.split()) != 5 or not path:
            raise ValueError("malformed raw transition")
        paths.append(os.fsdecode(path))
    return sorted(paths)


def transition_requires_full(records: bytes) -> bool:
    """Executable/type/submodule transitions are not provably documentation-only."""
    transition_paths(records)  # validate the shared representation first
    for metadata in records.split(b"\0")[0:-1:2]:
        old, new, *_ = metadata[1:].split()
        ordinary = {b"000000", b"100644", b"100755"}
        if old not in ordinary or new not in ordinary:
            return True
        if old != b"000000" and new != b"000000" and old != new:
            return True
    return False


def changed_paths(base: str, head: str):
    """Return all transition endpoints, or None to widen validation on failure."""
    try:
        return transition_paths(file_transitions(base, head))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def classify(event: str, base: str = "", head: str = "", paths=None) -> frozenset[str]:
    """Return the lanes to run for an event, a base/head range, or explicit paths."""
    if event == "workflow_dispatch":
        return ALL_LANES
    if paths is not None:
        return classify_paths(paths)
    if event in ("push", "pull_request"):
        try:
            records = file_transitions(base, head)
            if transition_requires_full(records):
                return ALL_LANES
            return classify_paths(transition_paths(records))
        except (OSError, ValueError, subprocess.CalledProcessError):
            return ALL_LANES
    # Unknown event: fail closed.
    return ALL_LANES


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
        help="Path to append the classification to (defaults to $GITHUB_OUTPUT)",
    )
    args = parser.parse_args(argv)

    paths = None
    if args.paths is not None:
        paths = [p for p in (item.strip() for item in args.paths.split(",")) if p]

    lanes = classify(args.event, args.base, args.head, paths)
    ordered = [lane for lane in LANES if lane in lanes]
    lines = [f"lanes={','.join(ordered)}", f"full={'true' if lanes == ALL_LANES else 'false'}"]
    lines.extend(f"{lane}={'true' if lane in lanes else 'false'}" for lane in LANES)

    for line in lines:
        print(line)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
