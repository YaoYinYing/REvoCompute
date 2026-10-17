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

Two of the loaders it reads are addressed through module-private names --
``result_audit._required_sources`` and ``input_validators.profiles._DIALECTS``.
Neither has a public accessor today, and each is the exact predicate production
dispatches on, so re-deriving it here would be the second source of truth this
tool exists to avoid. The reads are inspect-only: the tool never mutates a
registry, and the one shared entry point ``validate_input_file`` stays the
Server's own dispatch.

The logical-type lifecycle is decided by *probing that same dispatch*, not by
naming a registry: each ``(logical type, format)`` pair a Task declares is
validated once with a payload Core is guaranteed to refuse (a single NUL byte,
which reads as binary content for every text validator and as an undecodable
document for every JSON one) and classified by *which* Core validator refused
it. A class therefore cannot be asserted by this file; it is whatever the
Server's own code does.

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
* **Evidence-level interchangeability.** The five levels are recorded as separate
  booleans per family and are never summed into one score. A pytest marker is its
  own level, and the CLI level is decided by a re-verified replay bundle rather
  than by test text: this scanner reads test files and never executes them, so no
  scan-derived fact can claim that a real program ran.

Usage::

    python tools/audit_runner_scientific_contracts.py --json
    python tools/audit_runner_scientific_contracts.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# The tool is also run directly (``python tools/audit_runner_scientific_contracts.py``),
# where only ``tools/`` is on ``sys.path``. Put the repository root first so the
# ``revocompute`` loaders this report consumes are importable either way.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from revocompute.input_validators import profiles as _input_profiles
from revocompute.input_validators import supported_input_formats
from revocompute.input_validators import validate_input_file, validate_logical_input
from revocompute.live_tests import LiveTestConfigurationError, load_live_test_plan
from revocompute.result_audit import _required_sources, audit_fleet
from revocompute.result_storyboard import expected_file_tree
from revocompute.task_types import isolated_discovery

#: Executable asset suffixes a Runner adapter can read a parameter or input role
#: from. Family ``tests/`` trees are excluded: a test that names a parameter is
#: evidence *about* the adapter, not the adapter itself.
_ADAPTER_SUFFIXES = frozenset({".sh", ".bash", ".py"})

#: Validation lifecycles, keyed by the registry that decides one
#: ``(logical type, format)`` pair. The names describe *which Core validator
#: refuses a bad payload*; they are not evidence levels and are never summed.
_LIFECYCLE_INLINE = "inline_logical_validation"
_LIFECYCLE_SPECIFICATION = "specification_validation"
_LIFECYCLE_DIALECT = "format_dialect_validation"
_LIFECYCLE_ABSENT = "no_semantic_validator"

LIFECYCLE_CLASSES = (
    _LIFECYCLE_INLINE,
    _LIFECYCLE_SPECIFICATION,
    _LIFECYCLE_DIALECT,
    _LIFECYCLE_ABSENT,
)

#: One NUL byte: no text validator accepts it, so every branch of the dispatch
#: refuses it and the refusal names the branch that ran.
_PROBE_PAYLOAD = bytes([0])

#: Wording Core's validators use for the *subject* of a refusal, i.e. the
#: ``kind=`` each validator is called with. These are refusal provenance, not
#: file content: they say which validator ran, which is exactly the fact being
#: classified. The pair matters: a dialect replaces the PASS-ONE validator with
#: registry wording, while the Boltz YAML serialization keeps the generic YAML
#: validator in pass one and is enforced by the logical arm in pass two. The
#: same wording in the two passes is therefore a different lifecycle, and the
#: classification below reads the pass, not just the wording.
_PHYSICAL_DIALECT_KINDS = ("Boltz specification", "Chai entity FASTA")
_LOGICAL_VERBATIM_KINDS = ("protein structure", "alignment", "Boltz specification")

#: The logical types whose remaining arm is the specification registry. Listed so
#: the registry read below is an identification of the arm that refused, not a
#: second place a lifecycle is asserted from.
_SPECIFICATION_LOGICAL_TYPES = ("alphafold3_specification", "foundry_specification", "opendde_specification")


#: The two modes a capture persists on itself, from ``frontend_fixtures``' own
#: vocabulary: ``reproduced_real_result`` for a capture that reproduced a real
#: finished result, ``synthetic`` for one that stood in for a result. The auditor
#: branches on these and nothing else -- not on scheduler prose, which a caller
#: supplies. ``test_fleet_scientific_contract_inventory`` asserts these two equal
#: the capture module's ``CAPTURE_MODES``, so the vocabulary cannot drift here.
_CAPTURE_MODE_REPRODUCED = "reproduced_real_result"
_CAPTURE_MODE_SYNTHETIC = "synthetic"

#: Evidence levels. Never interchangeable, never summed.
#: An evidence level is only ever in this tuple if it is *reachable*: every member
#: is produced by some fleet family today, so the tuple carries no dead merger.
EVIDENCE_LEVELS = (
    "static_contract",
    "fake_runner_contract",
    "declared_scientific_acceptance",
    "real_runner_cli",
    "target_host_slurm_apptainer",
)

#: Test primitive that spawns a program, matched against a family's ``tests/fast``
#: text. It decides ``fake_runner_contract`` only -- deliberately the weakest claim
#: text can carry. A substring in unstripped source (a comment, a docstring, a
#: literal) is not a call, and no token scan can establish the ABSENCE of a
#: substitution: ``MagicMock``, ``mocker.patch.object`` and a plain lambda
#: assignment all replace the upstream program without naming a mocking library.
#: ``real_runner_cli`` is therefore decided by a re-verified replay bundle alone.
_EXECUTION_PATTERNS = ("run_with_manifest", "subprocess.run", "Popen")

#: Test pattern that marks a family-owned scientific validation. The marker is a
#: *declaration*: alone it is a distinct, weaker level
#: (``declared_scientific_acceptance``) and never evidence that a real program ran.
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


def _input_dispatch_class(logical_type: str, format_name: str, probe_directory: Path) -> str:
    """Classify one ``(logical type, format)`` pair by probing Core's dispatch.

    The probe runs the Server's own validation -- the physical pass
    (``validate_input_file``, given the logical type so a registered dialect can
    replace the strict validator) and the logical pass
    (``validate_logical_input``), which are the two calls the upload path makes --
    over a one-byte binary payload that every branch refuses. Which validator
    refused is therefore the dispatch's own behaviour; this reads the refusal
    instead of carrying a roster of type names that could drift from Core.

    ``boltz_specification`` is the pair this keeps apart: its ``fasta``/``fa``/
    ``fas`` serializations are a registered physical *dialect*, so the physical
    pass refuses them under the dialect's own name, while its ``yaml``/``yml``
    serializations are handled by a logical arm and are not a dialect at all.
    Classifying the pair, rather than the type, is what lets those be reported as
    the two different things they are.
    """
    suffix = f".{format_name}"
    if format_name.lower().removeprefix(".") not in supported_input_formats():
        # The upload path fails closed on an unregistered extension, so no
        # semantic validator can observe the pair. The row records that fact
        # separately as ``formats_inside_core_boundary``.
        return _LIFECYCLE_ABSENT
    probe = _probe_payload(probe_directory, suffix)
    try:
        physical = validate_input_file(str(probe), probe.name, logical_type=logical_type)
        if physical is not None and any(kind in physical for kind in _PHYSICAL_DIALECT_KINDS):
            return _LIFECYCLE_DIALECT
        logical = validate_logical_input(str(probe), format_name, logical_type)
    except Exception:  # noqa: BLE001 - a validator that cannot classify its own input
        return _LIFECYCLE_ABSENT
    if logical is None:
        # Both passes accepted this payload, so no semantic validator observed
        # the pair -- whatever the physical pass happens to be named.
        return _LIFECYCLE_ABSENT
    if any(kind in logical for kind in _LOGICAL_VERBATIM_KINDS):
        return _LIFECYCLE_INLINE
    if logical_type in _SPECIFICATION_LOGICAL_TYPES:
        # The last document-level arm: the specification registry, which runs on
        # the parsed JSON document and returns the profile's own wording. The read
        # below is the *identification* of the arm that produced a refusal the
        # probe already observed, not an independent reason to assert one.
        specifications = {str(key) for key in _input_profiles._SPECIFICATION_VALIDATORS}
        if logical_type in specifications:
            return _LIFECYCLE_SPECIFICATION
    return _LIFECYCLE_ABSENT


def _probe_payload(probe_directory: Path, suffix: str) -> Path:
    """One deterministic probe file per format, reused across the inventory.

    The probe carries a NUL byte so it is invalid for every format -- an empty
    file would be refused by the transport pass for the wrong reason. Its name,
    size, and content are fixed, so a classification cannot depend on what the
    fleet happens to validate at the time.
    """
    probe_directory.mkdir(parents=True, exist_ok=True)
    probe = probe_directory / f"core-probe{suffix}"
    if not probe.is_file():
        probe.write_bytes(_PROBE_PAYLOAD)
    return probe


def _classify_declared_pairs(pairs: set[tuple[str, str]], probe_directory: Path) -> dict[str, str]:
    """Lifecycle per declared ``(logical type, format)`` pair.

    The pair is the unit Core dispatches on -- ``_DIALECTS`` is keyed by
    ``(format, logical type)``, and the ``_SPECIFICATION_VALIDATORS`` arm is
    reached only under the ``json`` format -- so a per-type label alone drops the
    dimension the two registries are keyed by.
    """
    return {
        _pair_key(logical_type, format_name): _input_dispatch_class(logical_type, format_name, probe_directory)
        for logical_type, format_name in sorted(pairs)
    }


def _pair_key(logical_type: str, format_name: str) -> str:
    return f"{logical_type}|{format_name}"


def _role_lifecycles(pair_classes: Mapping[str, str], logical_type: str, formats: Sequence[str]) -> list[str]:
    """The distinct lifecycles a role's declared ``(type, format)`` pairs occupy.

    A single label per type would have to pick one of several true answers -- the
    Boltz type is *both* dialect-validated (FASTA) and logically validated (YAML)
    -- so the role carries the set, ordered by :data:`LIFECYCLE_CLASSES` for a
    stable report. ``no_semantic_validator`` is reported only when no pair
    reached a validator at all, which is the case the plural form makes explicit.
    """
    present = {pair_classes.get(_pair_key(logical_type, name), _LIFECYCLE_ABSENT) for name in formats}
    return [name for name in LIFECYCLE_CLASSES if name in present]


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

    The label is decided, not declared. Three facts are read off the artifact,
    each of which the *capture* wrote and the canonical loader re-validated:

    * a production-receipt pointer whose fields agree, field for field, with the
      pointer the canonical receipt parser recomputes from the cited receipt --
      target-host evidence;
    * otherwise a capture whose persisted mode says it reproduced a real result
      rather than standing in for one -- real-CLI evidence;
    * otherwise a synthetic capture -- ``synthetic_mock``, which carries no
      scientific claim. This is the only branch a ``require_finished=False``
      capture can reach, so a mock can never be presented as validation.

    A bundle that fails the canonical load is downgraded to
    ``unverified_declaration`` rather than trusted. A caller-supplied string is
    never the deciding fact: the capture mode is written by the capture function
    from its own argument and its own verified outcome, and the scheduler prose
    the capture records is context, not proof.
    """
    relative = path.relative_to(repo_root).as_posix()
    bundle = _load_bundle(repo_root, path)
    if bundle is None:
        return {"path": relative, "label": "unverified_declaration", "detail": "bundle failed canonical load"}
    provenance = bundle.get("provenance") if isinstance(bundle.get("provenance"), dict) else {}
    pointer = provenance.get("production_receipt")
    if isinstance(pointer, dict):
        return _label_receipt_pointer(repo_root, relative, bundle, pointer)
    capture = provenance.get("capture") if isinstance(provenance.get("capture"), dict) else {}
    if capture.get("mode") == _CAPTURE_MODE_REPRODUCED:
        return {
            "path": relative,
            "label": "real_runner_local_no_scheduler",
            "task_type": str(bundle.get("task", {}).get("type") or ""),
            "detail": str(capture.get("scheduler") or ""),
        }
    if capture.get("mode") == _CAPTURE_MODE_SYNTHETIC:
        return {
            "path": relative,
            "label": "synthetic_mock",
            "task_type": str(bundle.get("task", {}).get("type") or ""),
        }
    # No stored capture mode: either a hand-authored declaration, or a bundle
    # captured before the capture recorded its own mode. Not trusted as evidence
    # either way -- the point of the label is that it cannot be declared.
    return {
        "path": relative,
        "label": "unverified_declaration",
        "detail": "no capture mode and no production receipt; the capture's own evidence is absent",
    }


def _label_receipt_pointer(
    repo_root: Path, relative: str, bundle: Mapping[str, Any], pointer: Mapping[str, Any]
) -> dict[str, Any]:
    """The strongest label, only when the STORED pointer re-verifies unchanged.

    Calling ``production_receipt_pointer`` and discarding its return value proves
    only that the cited receipt parses and names this task; a stored pointer whose
    digest, deployment, or runtime fields had drifted from the receipt it cites
    would still be promoted. The recomputed canonical pointer is therefore
    compared against the stored one field for field, and any disagreement -- or
    any failure to recompute at all -- downgrades the item instead of promoting it.
    """
    task_id = str(bundle.get("task", {}).get("id") or "")
    receipt_path = pointer.get("receipt_path")
    if not (isinstance(receipt_path, str) and receipt_path and task_id):
        return {
            "path": relative,
            "label": "unverified_declaration",
            "detail": "the stored production-receipt pointer cites no resolvable receipt",
        }
    candidate = repo_root / receipt_path
    if not candidate.is_file():
        return {
            "path": relative,
            "label": "unverified_declaration",
            "detail": f"the cited production receipt is not present: {receipt_path}",
        }
    try:
        from frontend_fixtures.provenance import production_receipt_pointer

        canonical = production_receipt_pointer(candidate, task_id=task_id, receipt_path=receipt_path)
    except Exception:  # noqa: BLE001 - any receipt failure downgrades the label
        return {
            "path": relative,
            "label": "unverified_declaration",
            "detail": "the cited production receipt did not re-verify",
        }
    if dict(pointer) != canonical:
        mismatched = sorted(key for key in set(pointer) | set(canonical) if pointer.get(key) != canonical.get(key))
        return {
            "path": relative,
            "label": "unverified_declaration",
            "detail": "the stored production-receipt pointer disagrees with the receipt it cites on: "
            + ", ".join(mismatched),
        }
    return {
        "path": relative,
        "label": "real_target_host_slurm_apptainer",
        "task_type": str(bundle.get("task", {}).get("type") or ""),
        "receipt_path": receipt_path,
    }


def _corpus_label_reason(label: str) -> str:
    return {
        "real_target_host_slurm_apptainer": (
            "a real result captured from the canonical finished task store whose production API "
            "acceptance receipt re-verifies through the canonical receipt parser. The receipt's own "
            "``complete`` flag is not part of the predicate, so a successful but partial run reaches "
            "this label; the level establishes provenance, never completeness"
        ),
        "real_runner_local_no_scheduler": (
            "a real Runner result produced by the pinned SIF through the family run.sh/normalizer, "
            "captured with no batch-scheduler allocation"
        ),
        "synthetic_mock": (
            "fixture bytes from a capture whose own persisted mode says it stood in for a result "
            "rather than reproduced one (capture_replay_bundle(require_finished=False)). Carries no "
            "scientific claim and must never be presented as validation"
        ),
        "unverified_declaration": "a declaration whose provenance could not be re-verified",
    }[label]


def build_inventory(runners_dir: str | Path, repo_root: str | Path) -> dict[str, Any]:
    """Build the machine-readable inventory for every discovered TaskType."""
    runners_path = Path(runners_dir).resolve()
    repo_path = Path(repo_root).resolve()
    report = audit_fleet(str(runners_path), server_dir=str(repo_path))
    known_formats = supported_input_formats()

    with isolated_discovery(str(runners_path)) as manager:
        tasks = sorted(
            (value for _identifier, value in manager.contributions.items("tasks")), key=lambda task: task.name
        )
        by_family: dict[str, list[Any]] = {}
        for task in tasks:
            by_family.setdefault(task.runtime.name, []).append(task)

        # Classify only the (logical type, format) pairs the fleet actually
        # declares, by probing Core's own dispatch once per pair.
        declared_pairs = {
            (str(role.type), str(format_name)) for task in tasks for role in task.inputs for format_name in role.formats
        }
        with tempfile.TemporaryDirectory(prefix="runner-contract-probe-") as probe_root:
            pair_lifecycle = _classify_declared_pairs(declared_pairs, Path(probe_root))

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
                    "fast_contract_executes_adapter": any(pattern in fast_text for pattern in _EXECUTION_PATTERNS),
                    # Reading a test file is not running it, so a family's scientific
                    # acceptance is recorded as a DECLARATION only. No text scan can
                    # decide that a real program ran, so nothing scan-derived feeds
                    # ``real_runner_cli`` and no ``executes_program`` fact is published.
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
                        "lifecycles": _role_lifecycles(pair_lifecycle, str(role.type), formats),
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
            # The marker is a declaration. It is recorded as its own level so a
            # pytest marker can never stand in for execution.
            "declared_scientific_acceptance": bool(row["declares_scientific_acceptance"]),
            # Real CLI evidence is decided by ONE class of artifact: a checked-in
            # replay bundle whose provenance re-verifies. Test text is not evidence
            # here -- a comment naming subprocess.run is not a call, and the absence
            # of a substitution cannot be established by a token scan (MagicMock,
            # mocker.patch.object and a lambda assignment all mock silently). A
            # family that genuinely runs the program but ships no bundle is
            # deliberately under-claimed rather than over-claimed.
            "real_runner_cli": bool(family_task_names & cli_tasks),
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
                "Slurm+Apptainer acceptance. ``declared_scientific_acceptance`` is a marker, "
                "which is a declaration rather than execution, so it is not the CLI level."
            ),
        },
        "evidence_corpus": {
            "labels": list(CORPUS_LABELS),
            "items": corpus_items,
            "note": (
                "Each label is decided by the item's own re-verified provenance. Synthetic fixtures and "
                "unverified declarations carry scientific_claim=none and are never presented as validation. "
                "The five evidence levels are recorded separately and are never summed."
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
