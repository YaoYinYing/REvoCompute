#!/usr/bin/env python3
# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Report one evidence-backed inventory row per discovered Runner TaskType.

This tool is deliberately inspect-only, like ``tools/audit_runtime_sizes.py``: it
never builds, pulls, or runs an image. It is not a second semantic registry and
it does not restate the manifests. It *consumes* the loaders production already
uses -- ``task_types.isolated_discovery`` for Task/ResultView/input-role/parameter
declarations, ``result_audit.audit_fleet`` for the result contract,
``result_storyboard`` for the result tree and storyboard, ``live_tests`` for the
family test plan, and the ``input_validators`` registries for the input-format and
logical-type lifecycle -- so a row can never disagree with what the Server
accepts, and the inventory reruns against another fleet revision without editing
a roster.

Three things this tool deliberately does NOT claim:

* **Scientifically validated.** A row records which declarations exist and which
  evidence artifacts are present on disk. It never asserts a Runner executed or
  that an output is correct; that belongs to SIF ``%test``, Doctor, smoke, and
  target-host live acceptance.
* **Parameter forwarding.** The server owns no param->upstream-flag mapping: the
  mapping is arbitrary adapter code (string concatenation, an allow-list, a
  conditional branch). A static scan can therefore only produce *candidates* for
  a parameter that is never forwarded, never a verdict. The field is named
  ``forwarding_candidates`` and carries that caveat; the only executable
  forward-path verdict is a family's own ``tests/fast`` case that runs the real
  ``run.sh`` against a fake executable and asserts the exact argv.
* **Evidence-level interchangeability.** ``static_contract``, ``fake_runner``,
  ``real_cli``, and ``target_host_slurm_apptainer`` are recorded as separate
  booleans per row and are never summed into one score.

Usage::

    python tools/audit_runner_scientific_contracts.py --json
    python tools/audit_runner_scientific_contracts.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# The tool is also run directly (``python tools/audit_runner_scientific_contracts.py``),
# where only ``tools/`` is on ``sys.path``. Put the repository root first so the
# ``revocompute`` loaders this report consumes are importable either way.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from revocompute.input_validators import _DIALECTS as _INPUT_DIALECTS
from revocompute.input_validators import profiles as _input_profiles
from revocompute.input_validators import supported_input_formats
from revocompute.live_tests import LiveTestConfigurationError, load_live_test_plan
from revocompute.result_audit import _required_sources, audit_fleet
from revocompute.result_storyboard import expected_file_tree
from revocompute.task_types import isolated_discovery

#: Executable asset suffixes a Runner adapter can read a parameter or input role
#: from. Family ``tests/`` trees are excluded: a test that names a parameter is
#: evidence *about* the adapter, not the adapter itself.
_ADAPTER_SUFFIXES = frozenset({".sh", ".bash", ".py"})

#: Logical input types whose semantics a real Core validator enforces, keyed by
#: the lifecycle the validator registry gives them. ``inline`` names the types
#: ``profiles.validate_logical_input`` checks directly; a type absent from all
#: three registries has no semantic validator (only transport and physical-format
#: safety), which is a legitimate state the audit reports rather than a defect.
_INLINE_LOGICAL_TYPES = frozenset({"protein_structure", "alignment"})

#: Evidence levels. Never interchangeable, never summed.
EVIDENCE_LEVELS = (
    "static_contract",
    "fake_runner_contract",
    "real_runner_cli",
    "target_host_slurm_apptainer",
)

#: Test pattern a family must have under ``tests/fast`` for its evidence level to
#: include ``fake_runner_contract``: it runs the real adapter and asserts behavior.
_FAKE_RUNNER_PATTERNS = ("run_with_manifest", "subprocess.run", "Popen")

#: Test pattern that marks a family-owned scientific validation, which is what the
#: ``real_runner_cli`` level records when a checked-in replay bundle is absent.
_SCIENTIFIC_PATTERN = "scientific_acceptance"

#: Labels for an evidence-corpus item, decided by the item's own verified
#: provenance rather than by a hand-maintained list.
CORPUS_LABELS = (
    "real_target_host_slurm_apptainer",
    "real_runner_local_no_scheduler",
    "synthetic_mock",
    "unverified_declaration",
)


def _adapter_corpus(family_root: Path) -> str:
    """The concatenated source of a family's executable adapter assets.

    Family ``tests/`` trees are excluded, so a test asserting a parameter's argv
    cannot make the named parameter look forwarded in the adapter itself.
    """
    parts: list[str] = []
    for path in sorted(family_root.rglob("*")):
        if not path.is_file() or path.suffix not in _ADAPTER_SUFFIXES:
            continue
        relative = path.relative_to(family_root)
        if relative.parts and relative.parts[0] == "tests":
            continue
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def _first_present(mapping: dict[str, Any], *keys: str) -> str:
    """The first non-empty string among ``keys`` in ``mapping``, else ``UNKNOWN``."""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "UNKNOWN"


def _upstream_pin(repo_root: Path, family_root: Path) -> dict[str, str]:
    """Project a family-owned ``upstream.json`` into pin/license fields.

    The key vocabulary differs per family (``upstream_commit``, ``commit``,
    ``revision``, ``github_revision``, ...), so the reader accepts the observed
    spellings and reports ``UNKNOWN`` for anything it cannot find rather than
    guessing. A family that ships no ``upstream.json`` is ``UNKNOWN`` too, not
    absent-from-the-report.
    """
    source = family_root / "upstream.json"
    if not source.is_file():
        return {"upstream_source": "none", "upstream_revision": "UNKNOWN", "code_license": "UNKNOWN"}
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"upstream_source": "unreadable", "upstream_revision": "UNKNOWN", "code_license": "UNKNOWN"}
    if not isinstance(document, dict):
        return {"upstream_source": "invalid", "upstream_revision": "UNKNOWN", "code_license": "UNKNOWN"}
    return {
        "upstream_source": source.relative_to(repo_root).as_posix(),
        "upstream_revision": _first_present(
            document, "upstream_commit", "commit", "github_revision", "revision", "upstream_version"
        ),
        "code_license": _first_present(document, "code_license", "license"),
    }


def _family_test_text(family_root: Path, name: str) -> str:
    """Concatenated source of one family test directory, or ``""`` when absent."""
    directory = family_root / "tests" / name
    if not directory.is_dir():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in sorted(directory.rglob("*.py")))


def _input_type_lifecycle() -> dict[str, str]:
    """Classify every logical input type by which registry enforces its semantics."""
    specification = {str(key) for key in _input_profiles._SPECIFICATION_VALIDATORS}
    dialects = {str(logical_type) for (_format_name, logical_type) in _INPUT_DIALECTS}
    lifecycle: dict[str, str] = {}
    for logical_type in _INLINE_LOGICAL_TYPES:
        lifecycle[logical_type] = "inline_logical_validation"
    for logical_type in specification:
        lifecycle[logical_type] = "specification_validation"
    for logical_type in dialects:
        lifecycle.setdefault(logical_type, "format_dialect_validation")
    return lifecycle


def _coverage_state(task: Any, repo_root: Path) -> str:
    """Which of the four result-contract coverage states a Task occupies.

    The states are exhaustive and mutually exclusive, and they reconcile with the
    audit's ``covered``/``unaudited`` partition: ``tree_audited``,
    ``no_required_source`` and ``no_views`` are covered; ``tree_absent`` is
    unaudited. ``no_required_source`` is a real state -- a Task whose views
    declare every source optional, or ship no views at all, imposes no tree
    obligation -- and it must not be read as "has a tree".
    """
    tree = _result_tree(task, repo_root)
    required = [1 for view in task.result_workspace for _source in _required_sources(view)]
    if not task.result_workspace:
        return "no_views"
    if tree and required:
        return "tree_audited"
    if required:
        return "tree_absent"
    return "no_required_source"


def _result_tree(task: Any, repo_root: Path) -> dict[str, Any] | None:
    """The Task's declared result tree, or ``None`` when it ships no tree.

    ``expected_file_tree`` returns an empty mapping (not ``None``) for a family
    that ships no ``expected_files.yaml``, so a bare ``is not None`` would report a
    tree-less Task as tree-bearing. Normalizing the empty mapping to ``None`` here
    keeps one definition of "has a declared result tree" for the whole report.
    """
    try:
        tree = expected_file_tree(task, str(repo_root))
    except Exception:  # noqa: BLE001 - the fleet audit reports the loader failure
        return None
    return dict(tree) if tree else None


def _load_bundle(repo_root: Path, path: Path) -> dict[str, Any] | None:
    """Load a checked-in replay bundle through the real capture/load path."""
    import sys

    tests_dir = str(repo_root / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    try:
        from frontend_fixtures.replay_bundle import ReplayBundleError, load_bundle
    except ImportError:  # pragma: no cover - the fixture package ships with the repo
        return None
    try:
        return load_bundle(path)
    except ReplayBundleError:
        return None


def _label_corpus_item(repo_root: Path, path: Path) -> dict[str, Any]:
    """Label one replay bundle from its OWN verified provenance.

    The label is decided, not declared: a bundle whose production-receipt pointer
    re-verifies through the canonical receipt parser is target-host evidence; a
    bundle whose capture records no scheduler allocation is real-CLI evidence; a
    bundle that fails the canonical load is downgraded to ``unverified_declaration``
    rather than trusted. A hand-written label cannot drift into claiming more than
    the artifact proves, because there is no hand-written label.
    """
    relative = path.relative_to(repo_root).as_posix()
    bundle = _load_bundle(repo_root, path)
    if bundle is None:
        return {"path": relative, "label": "unverified_declaration", "detail": "bundle failed canonical load"}
    provenance = bundle.get("provenance") if isinstance(bundle.get("provenance"), dict) else {}
    pointer = provenance.get("production_receipt")
    if isinstance(pointer, dict):
        task_id = str(bundle.get("task", {}).get("id") or "")
        receipt_path = pointer.get("receipt_path")
        verified = False
        if isinstance(receipt_path, str) and receipt_path and task_id:
            candidate = repo_root / receipt_path
            if candidate.is_file():
                try:
                    from frontend_fixtures.provenance import production_receipt_pointer

                    production_receipt_pointer(candidate, task_id=task_id)
                    verified = True
                except Exception:  # noqa: BLE001 - any receipt failure downgrades the label
                    verified = False
        if verified:
            return {
                "path": relative,
                "label": "real_target_host_slurm_apptainer",
                "task_type": str(bundle.get("task", {}).get("type") or ""),
                "receipt_path": receipt_path,
            }
        return {
            "path": relative,
            "label": "unverified_declaration",
            "detail": "the cited production receipt did not re-verify",
        }
    capture = provenance.get("capture") if isinstance(provenance.get("capture"), dict) else {}
    scheduler = str(capture.get("scheduler") or "")
    if scheduler and "none" in scheduler.lower():
        return {
            "path": relative,
            "label": "real_runner_local_no_scheduler",
            "task_type": str(bundle.get("task", {}).get("type") or ""),
            "detail": scheduler,
        }
    return {
        "path": relative,
        "label": "unverified_declaration",
        "detail": "no production receipt and no recorded scheduler",
    }


def _corpus_label_reason(label: str) -> str:
    return {
        "real_target_host_slurm_apptainer": (
            "a real result captured from the canonical finished task store whose production API "
            "acceptance receipt re-verifies through the canonical receipt parser"
        ),
        "real_runner_local_no_scheduler": (
            "a real Runner result produced by the pinned SIF through the family run.sh/normalizer, "
            "captured with no batch-scheduler allocation"
        ),
        "synthetic_mock": (
            "fixture bytes that exercise rendering. Carries no scientific claim and must never be "
            "presented as validation"
        ),
        "unverified_declaration": "a declaration whose provenance could not be re-verified",
    }[label]


def build_inventory(runners_dir: str | Path, repo_root: str | Path) -> dict[str, Any]:
    """Build the machine-readable inventory for every discovered TaskType."""
    runners_path = Path(runners_dir).resolve()
    repo_path = Path(repo_root).resolve()
    report = audit_fleet(str(runners_path), server_dir=str(repo_path))
    lifecycle = _input_type_lifecycle()
    known_formats = supported_input_formats()

    with isolated_discovery(str(runners_path)) as manager:
        tasks = sorted(
            (value for _identifier, value in manager.contributions.items("tasks")), key=lambda task: task.name
        )
        by_family: dict[str, list[Any]] = {}
        for task in tasks:
            by_family.setdefault(task.runtime.name, []).append(task)

        rows: list[dict[str, Any]] = []
        for family_name in sorted(by_family):
            family_tasks = by_family[family_name]
            family_root = Path(family_tasks[0].runtime.root)
            if not family_root.is_dir():
                family_root = runners_path / family_name
            corpus = _adapter_corpus(family_root)
            pin = _upstream_pin(repo_path, family_root)
            plan_status = "absent"
            plan = None
            plan_error = ""
            declared = {task.name for task in family_tasks}
            test_yaml = family_root / "test.yaml"
            if test_yaml.is_file():
                try:
                    plan = load_live_test_plan(
                        test_yaml,
                        repo_root=repo_path,
                        task_schemas={task.name: (task.schema or {}) for task in family_tasks},
                    )
                    plan_status = "valid"
                except LiveTestConfigurationError as exc:
                    plan_status = "invalid"
                    plan_error = str(exc)
            smoke_covered = sorted({case.task for case in plan.select("smoke")}) if plan else []
            smoke_missing = sorted(declared - set(smoke_covered))
            fast_text = _family_test_text(family_root, "fast")
            scientific_text = _family_test_text(family_root, "scientific")
            policy = family_tasks[0].runtime.access_policy
            runner_yaml = family_root / "runner.yaml"
            rows.append(
                {
                    "family": family_name,
                    "tasks": [task.name for task in family_tasks],
                    "runtime_image_artifact": family_tasks[0].runtime.image_artifact,
                    "runtime_definition": family_tasks[0].runtime.definition,
                    **pin,
                    "build_inputs": list(family_tasks[0].runtime.build_inputs),
                    "access_policy": policy.id if policy is not None else None,
                    "access_policy_license": ((policy.license or {}).get("name") if policy is not None else None),
                    "runner_yaml": runner_yaml.is_file(),
                    "has_family_storyboard": (family_root / "storyboard" / "storyboard.yaml").is_file(),
                    "live_test_plan": plan_status,
                    "live_test_plan_error": plan_error,
                    "smoke_cases": smoke_covered,
                    "smoke_missing_tasks": smoke_missing,
                    "has_fast_tests": (family_root / "tests" / "fast").is_dir(),
                    "has_scientific_tests": (family_root / "tests" / "scientific").is_dir(),
                    "fast_contract_executes_adapter": any(pattern in fast_text for pattern in _FAKE_RUNNER_PATTERNS),
                    "declares_scientific_acceptance": _SCIENTIFIC_PATTERN in scientific_text,
                    "forwarding_candidates": [
                        name
                        for name in sorted(
                            {prop for task in family_tasks for prop in ((task.schema or {}).get("properties") or {})}
                        )
                        if name not in corpus
                    ],
                }
            )

        task_rows: list[dict[str, Any]] = []
        for task in tasks:
            family_root = Path(task.runtime.root)
            corpus = _adapter_corpus(family_root)
            parameters = sorted((task.schema or {}).get("properties") or {})
            roles = []
            for role in task.inputs:
                formats = list(role.formats)
                roles.append(
                    {
                        "name": role.name,
                        "type": role.type,
                        "lifecycle": lifecycle.get(str(role.type), "no_semantic_validator"),
                        "formats": formats,
                        "formats_inside_core_boundary": sorted(set(formats) - known_formats) == [],
                        "cardinality": [role.minimum, role.maximum],
                        "referenced_in_runner": role.name in corpus,
                    }
                )
            task_rows.append(
                {
                    "task": task.name,
                    "family": task.runtime.name,
                    "display_name": task.display_name,
                    "category": task.category,
                    "coverage_state": _coverage_state(task, repo_path),
                    "declares_result_tree": _result_tree(task, repo_path) is not None,
                    "view_count": len(task.result_workspace),
                    "views": [
                        {
                            "id": view.id,
                            "plugin": view.plugin,
                            "role": view.role,
                            "required_sources": [
                                {"source": source, "value": selector.value, "glob": selector.is_glob}
                                for source, selector in _required_sources(view)
                            ],
                        }
                        for view in task.result_workspace
                    ],
                    "input_roles": roles,
                    "parameters": parameters,
                    "citations": len(task.citations),
                    "gpus": task.gpus,
                    "requires_network": task.requires_network,
                    "workflow_stages": [stage.name for stage in task.workflow],
                }
            )

    corpus_items = [
        _label_corpus_item(repo_path, path) for path in sorted((repo_path / "tests" / "data").glob("*_replay/*.json"))
    ]
    for item in corpus_items:
        item["reason"] = _corpus_label_reason(str(item["label"]))
        item["scientific_claim"] = (
            "none" if item["label"] in {"synthetic_mock", "unverified_declaration"} else "runner_output_replayed"
        )

    real_tasks = {
        str(item.get("task_type") or "") for item in corpus_items if item["label"] == "real_target_host_slurm_apptainer"
    }
    cli_tasks = {
        str(item.get("task_type") or "")
        for item in corpus_items
        if item["label"] in {"real_target_host_slurm_apptainer", "real_runner_local_no_scheduler"}
    }
    evidence_levels: dict[str, dict[str, bool]] = {}
    for row in rows:
        family = str(row["family"])
        family_task_names = set(row["tasks"])
        evidence_levels[family] = {
            # Every discovered Task has a statically validated contract by virtue
            # of being discovered; that is the floor, never the goal.
            "static_contract": True,
            # A fake-runner contract requires a family test that actually executes
            # the adapter (a subprocess run), not merely a test directory.
            "fake_runner_contract": bool(row["fast_contract_executes_adapter"]),
            # Real CLI evidence comes from a checked-in replay bundle of a real run
            # OR a family-owned scientific acceptance that pins real execution.
            "real_runner_cli": bool(family_task_names & cli_tasks) or bool(row["declares_scientific_acceptance"]),
            "target_host_slurm_apptainer": bool(family_task_names & real_tasks),
        }

    level_summary = {
        level: sorted(family for family, present in evidence_levels.items() if present[level])
        for level in EVIDENCE_LEVELS
    }
    tasks_by_family = {str(row["family"]): list(row["tasks"]) for row in rows}
    runner_evidence = {
        task: [level for level in EVIDENCE_LEVELS if evidence_levels[family][level]]
        for family, tasks in tasks_by_family.items()
        for task in tasks
    }

    return {
        "schema_version": 1,
        "discovery": {
            "runners_dir": str(runners_path),
            "task_count": len(task_rows),
            "family_count": len(rows),
        },
        "coverage": {
            "covered": sorted(report.covered),
            "unaudited": sorted(report.unaudited),
            "defective": sorted(report.defective),
            "ok": report.ok,
            "states": {
                state: sorted(row["task"] for row in task_rows if row["coverage_state"] == state)
                for state in ("tree_audited", "tree_absent", "no_required_source", "no_views")
            },
        },
        "findings": [
            {"code": finding.code, "task": finding.task, "view": finding.view, "detail": finding.detail}
            for finding in report.findings
        ],
        "evidence_levels": {
            "levels": list(EVIDENCE_LEVELS),
            "by_family": evidence_levels,
            "families_at_level": level_summary,
            "by_task": runner_evidence,
            "note": (
                "The levels are ordered from weakest to strongest and are NEVER summed or "
                "substituted: a static contract is not a fake-runner contract, a fake-runner "
                "contract is not a real CLI run, and a real local CLI run is not target-host "
                "Slurm+Apptainer acceptance."
            ),
        },
        "evidence_corpus": {
            "labels": list(CORPUS_LABELS),
            "items": corpus_items,
            "note": (
                "Each label is decided by the item's own re-verified provenance. Synthetic fixtures and "
                "unverified declarations carry scientific_claim=none and are never presented as validation. "
                "The four evidence levels are recorded separately and are never summed."
            ),
        },
        "parameter_forwarding": {
            "caveat": (
                "declared-but-never-forwarded can only be proven per family by executing its adapter; the "
                "server owns no param->upstream-flag mapping and the adapter is arbitrary code, so this is a "
                "candidate list, not a verdict"
            ),
            "executable_forward_path_evidence": "a family's own tests/fast case that runs run.sh and asserts argv",
        },
        "families": rows,
        "tasks": task_rows,
    }


def render_table(inventory: dict[str, Any]) -> str:
    """A compact human-facing row per family plus the coverage/corpus summary."""
    lines = [
        (
            f"Runner scientific contract inventory: {inventory['discovery']['task_count']} tasks across "
            f"{inventory['discovery']['family_count']} families"
        ),
        "",
        "family\ttasks\tcoverage_states\tlive_test\tpin\tlicense\tpolicy\tlevels",
    ]
    coverage = inventory["coverage"]
    states_by_task = {task: state for state, tasks in coverage["states"].items() for task in tasks}
    for row in inventory["families"]:
        states = sorted({states_by_task.get(task, "?") for task in row["tasks"]})
        levels = [name for name, present in inventory["evidence_levels"]["by_family"][row["family"]].items() if present]
        lines.append(
            "\t".join(
                [
                    str(row["family"]),
                    str(len(row["tasks"])),
                    ",".join(states),
                    str(row["live_test_plan"]),
                    str(row["upstream_revision"])[:12],
                    str(row["code_license"]),
                    str(row["access_policy"] or "-"),
                    ",".join(levels),
                ]
            )
        )
    lines.extend(
        [
            "",
            (
                f"coverage: {len(coverage['covered'])} covered / {len(coverage['unaudited'])} unaudited; "
                f"defects {len(coverage['defective'])}: {', '.join(coverage['defective']) or 'none'}"
            ),
            "evidence corpus:",
        ]
    )
    for item in inventory["evidence_corpus"]["items"]:
        lines.append(f"  {item['label']}\t{item['path']}\tscientific_claim={item['scientific_claim']}")
    lines.extend(
        [
            "",
            (
                f"parameter-forwarding candidates (NOT verdicts): "
                f"{sum(len(row['forwarding_candidates']) for row in inventory['families'])}"
            ),
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    server_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--runners-dir", type=Path, default=server_root / "docker" / "runners")
    parser.add_argument("--repo-root", type=Path, default=server_root)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--require-audited",
        action="store_true",
        help="Exit non-zero when any Task carries a concrete result-contract defect",
    )
    args = parser.parse_args()
    inventory = build_inventory(args.runners_dir, args.repo_root)
    if args.json:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    else:
        print(render_table(inventory))
    return 1 if args.require_audited and inventory["coverage"]["defective"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
