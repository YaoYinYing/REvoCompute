# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Derived, read-only operational readiness for active Runner SIFs."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from revocompute.admission import RunnerReadinessStatus
from revocompute.artifact_evidence import (
    read_build_evidence_for_provenance,
    read_receipt_for_digest,
    read_receipt_for_identity,
    read_staged_digest,
    receipt_digests,
    receipt_exists_for_provenance,
    staged_identity_describes,
)
from revocompute.doctor import diagnose
from revocompute.live_tests import LiveTestConfigurationError, receipt_matches
from revocompute.runner_live_test import load_validation_identity
from revocompute.runner_registry import (
    RegistryError,
    RuntimeFamily,
    _build_provenance,
    deployment_plugin_root,
    load_plugin_families,
    runner_enabled,
    sif_stale,
)
from revocompute.server_root import SERVER_ROOT


@dataclass(frozen=True, slots=True)
class ReadinessDiagnostic:
    code: str
    severity: str
    component: str
    message: str


@dataclass(frozen=True, slots=True)
class RunnerReadiness:
    runner_family: str
    status: RunnerReadinessStatus
    reason_code: str
    message: str
    doctor_ok: bool
    sif_path: str
    doctor_diagnostics: tuple[ReadinessDiagnostic, ...] = ()
    sif_exists: bool = False
    sif_sha256: str | None = None
    build_provenance_current: bool = False
    build_provenance_digest: str | None = None
    #: Runtime Bundle identity: what a new submission pins, and what the current
    #: receipt was issued against.  ``None`` for a family with no overlay.
    runtime_bundle_sha256: str | None = None
    receipt_exists: bool = False
    receipt_valid: bool = False
    receipt_tested_at: str | None = None
    receipt_sif_sha256: str | None = None
    receipt_runtime_bundle_sha256: str | None = None
    receipt_configuration_digest: str | None = None
    receipt_test_definition_digest: str | None = None
    required_smoke_cases: tuple[str, ...] = ()
    passed_smoke_cases: tuple[str, ...] = ()
    next_action: str = "none"

    @property
    def ready(self) -> bool:
        return self.status is RunnerReadinessStatus.READY

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["doctor_diagnostics"] = [asdict(item) for item in self.doctor_diagnostics]
        value["required_smoke_cases"] = list(self.required_smoke_cases)
        value["passed_smoke_cases"] = list(self.passed_smoke_cases)
        value["ready"] = self.ready
        return value


def _result(
    family: RuntimeFamily,
    status: RunnerReadinessStatus,
    reason_code: str,
    message: str,
    *,
    doctor_ok: bool,
    next_action: str | None = None,
    **evidence: Any,
) -> RunnerReadiness:
    default_action = {
        RunnerReadinessStatus.NOT_CONFIGURED: "doctor",
        RunnerReadinessStatus.NOT_BUILT: "build-sif",
        RunnerReadinessStatus.BUILD_STALE: "build-sif",
        RunnerReadinessStatus.NOT_VALIDATED: "live-test",
        RunnerReadinessStatus.VALIDATION_STALE: "live-test",
        RunnerReadinessStatus.READY: "none",
    }[status]
    return RunnerReadiness(
        runner_family=family.name,
        status=status,
        reason_code=reason_code,
        message=message,
        doctor_ok=doctor_ok,
        sif_path=family.slurm_image,
        next_action=default_action if next_action is None else next_action,
        **evidence,
    )


def _passed_case_ids(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    cases = receipt.get("cases", ())
    if not isinstance(cases, list):
        return ()
    return tuple(
        sorted(
            str(case["case_id"])
            for case in cases
            if isinstance(case, Mapping) and case.get("passed") is True and isinstance(case.get("case_id"), str)
        )
    )


def _string_field(receipt: Mapping[str, Any] | None, key: str) -> str | None:
    value = receipt.get(key) if receipt else None
    return value if isinstance(value, str) else None


def _bundle_root(state) -> str:
    """Deployment-owned Runtime Bundle store: a sibling of the image store."""
    configured = state.get("RUNTIME_BUNDLE_DIR")
    if configured:
        return configured
    return os.path.join(os.path.dirname(os.path.abspath(state.server_dir())), "runtime-bundles")


def bundle_digest(state, family: RuntimeFamily) -> str | None:
    """The Runtime Bundle digest a *new* submission for this family would pin."""
    if not family.runtime_overlay:
        return None
    from revocompute import runtime_bundle

    root = _bundle_root(state)
    try:
        # Ask the same question submission asks, so readiness cannot report
        # READY for a binding that a new submission would 503 on (an index
        # entry whose snapshot was pruned or removed).
        return runtime_bundle.resolve_for_submission(
            root, runtime_bundle.load_index(root), family.name, declares_overlay=True
        )
    except runtime_bundle.RuntimeBundleError:
        # No published (or no resolvable) binding: the digest of the current
        # source is what a live test would produce, so report that rather than
        # "unknown" — it cannot match the receipt, which is the honest answer.
        return runtime_bundle.overlay_digest(family.root.parent, family.runtime_overlay)


@dataclass(frozen=True, slots=True)
class _ReceiptEvidence:
    """The live-test evidence attributable under one build provenance.

    ``fields`` is exactly the evidence a verdict carries; ``receipt`` is the
    record those fields were read from.  ``failure`` names a configuration
    defect that prevents attributing any receipt to the artifact.
    """

    fields: dict[str, Any]
    receipt: Mapping[str, Any] | None
    failure: str | None = None


def _receipt_evidence(
    state, family: RuntimeFamily, build_digest: str, sif_sha256: str | None, *, artifact_bound: bool = False
) -> _ReceiptEvidence:
    """Read the live-test identity and receipt evidence under one build provenance.

    The lookup is the same one production evidence uses, so a verdict and the
    Fleet cannot describe the evidence differently.  It hashes nothing: the
    evidence model is content-addressed and path-agnostic.  ``artifact_bound``
    reads the receipt written for exactly ``sif_sha256`` instead of the first
    same-identity receipt, which can belong to a sibling artifact.
    """
    try:
        identity = load_validation_identity(family, state=state)
        required = tuple(sorted(case.id for case in identity.plan.select("smoke")))
    except (OSError, KeyError, TypeError, ValueError, StopIteration, LiveTestConfigurationError, RegistryError):
        return _ReceiptEvidence({}, None, "Runner live-test identity cannot be resolved")
    if identity.plan.omitted:
        # A narrowed scope runs fewer cases than the family declares.  Its
        # receipt cannot stand for the declared set, so it cannot authorize a
        # deployment that enables the families those cases run.
        omitted = ", ".join(sorted(case for case, _task in identity.plan.omitted))
        return _ReceiptEvidence({}, None, f"Declared live-test cases cannot run in this deployment: {omitted}")
    try:
        expected_uid = int(state.get("RUNNER_UID")) if state.get("RUNNER_UID") else None
        expected_gid = int(state.get("RUNNER_GID")) if state.get("RUNNER_GID") else None
        expected_scheduler_user = state.get("RUNNER_USERNAME") or None
    except (TypeError, ValueError):
        return _ReceiptEvidence({}, None, "Configured Runner UID/GID are not numeric")
    try:
        expected_bundle = bundle_digest(state, family)
    except (OSError, KeyError, TypeError, ValueError, RegistryError):
        # ``receipt_valid_for_artifact`` treats an unresolvable bundle as "no
        # valid receipt".  Substituting ``None`` here could instead validate a
        # bundle-less receipt, so a promotion verdict could name an activation
        # the host step refuses.  Fail the evidence attribution instead.
        return _ReceiptEvidence({}, None, "Runner Runtime Bundle binding cannot be resolved")
    expected_identity = {
        "build_provenance_digest": build_digest,
        "runtime_bundle_sha256": expected_bundle,
        "test_definition_digest": identity.plan.digest,
        "configuration_digest": identity.configuration_digest,
        "execution_uid": expected_uid,
        "execution_gid": expected_gid,
        "scheduler_user": expected_scheduler_user,
    }
    if artifact_bound and sif_sha256 is not None:
        receipt = read_receipt_for_digest(family, sif_sha256, expected_identity)
        receipt_exists = bool(receipt_digests(family, sif_sha256))
    else:
        receipt = read_receipt_for_identity(family, expected_identity)
        if sif_sha256 is None and receipt:
            sif_sha256 = _string_field(receipt, "sif_sha256")
        receipt_exists = receipt_exists_for_provenance(family, build_digest)
    passed = _passed_case_ids(receipt or {})
    valid = bool(receipt) and receipt_matches(
        receipt,
        sif_sha256=sif_sha256,
        build_provenance_digest=build_digest,
        test_definition_digest=identity.plan.digest,
        configuration_digest=identity.configuration_digest,
        required_case_ids=set(required),
        runtime_bundle_sha256=expected_bundle,
        expected_execution_uid=expected_uid,
        expected_execution_gid=expected_gid,
        expected_scheduler_user=expected_scheduler_user,
    )
    return _ReceiptEvidence(
        {
            "sif_sha256": sif_sha256,
            "build_provenance_current": True,
            "build_provenance_digest": build_digest,
            "runtime_bundle_sha256": expected_bundle,
            "receipt_exists": receipt_exists,
            "receipt_valid": valid,
            "receipt_tested_at": _string_field(receipt, "ended_at"),
            "receipt_sif_sha256": _string_field(receipt, "sif_sha256"),
            "receipt_configuration_digest": _string_field(receipt, "configuration_digest"),
            "receipt_test_definition_digest": _string_field(receipt, "test_definition_digest"),
            "receipt_runtime_bundle_sha256": _string_field(receipt, "runtime_bundle_sha256"),
            "required_smoke_cases": required,
            "passed_smoke_cases": passed,
        },
        receipt,
    )


def _staged_candidate_readiness(
    state,
    family: RuntimeFamily,
    build_digest: str,
    active_exists: bool,
) -> RunnerReadiness:
    """The submission verdict for a staged candidate, with the candidate's evidence.

    The candidate is not the artifact execution loads, so its digest is never
    presented as the active identity.  Its build/receipt evidence is the evidence
    ``promote-sifs`` requires, so it is reported rather than left at its default
    "no receipt" value.  The verdict only names promotion when the deployment-host
    step would accept the candidate; an unvalidated candidate is told to run the
    live test first.
    """
    # The record binds the staged bytes, so this is the same test ``promote_sifs``
    # applies.  A record that does not describe the staged bytes -- absent, from
    # another provenance, or left from before a rewrite -- cannot support a
    # promotion verdict; the live test is the one action that both validates the
    # bytes and records their identity, so it is the recovery in every case.
    candidate_sha256 = read_staged_digest(family)
    recorded = candidate_sha256 is not None and staged_identity_describes(family, candidate_sha256)
    if not recorded:
        return _result(
            family,
            RunnerReadinessStatus.NOT_VALIDATED,
            "RECEIPT_MISSING",
            "The staged Runner candidate's build identity is unrecorded or no longer describes its bytes; "
            "re-run the live test to bind and validate it",
            doctor_ok=True,
            sif_exists=active_exists,
            build_provenance_current=False,
            build_provenance_digest=build_digest,
        )
    evidence = _receipt_evidence(state, family, build_digest, candidate_sha256, artifact_bound=True)
    if evidence.failure is not None:
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "CONFIGURATION_INVALID",
            evidence.failure,
            doctor_ok=True,
            sif_exists=active_exists,
            # Same reason as the unrecorded-identity branch above: no evidence
            # was attributable to the candidate, so its build provenance is not
            # established as current.
            build_provenance_current=False,
            build_provenance_digest=build_digest,
        )
    fields = {
        **evidence.fields,
        # The evidence belongs to the candidate; this verdict does not establish
        # the installed artifact's identity, so the active digest stays unknown
        # while the receipt identifies the candidate.
        "sif_sha256": None,
        "build_provenance_current": True,
    }
    # The evidence check is at least as strong as the one ``promote_sifs``
    # applies: the recorded candidate digest is matched against the receipt, so
    # a promotion verdict is never one the host step would refuse.
    if not evidence.fields["receipt_valid"]:
        receipt = evidence.receipt
        if receipt is None and not evidence.fields["receipt_exists"]:
            return _result(
                family,
                RunnerReadinessStatus.NOT_VALIDATED,
                "RECEIPT_MISSING",
                "The staged Runner candidate has no live-test receipt; run the live test to validate it",
                doctor_ok=True,
                sif_exists=active_exists,
                **fields,
            )
        bundle_changed = (
            evidence.fields["runtime_bundle_sha256"] is not None
            and _string_field(receipt, "runtime_bundle_sha256") != evidence.fields["runtime_bundle_sha256"]
        )
        return _result(
            family,
            RunnerReadinessStatus.VALIDATION_STALE,
            "RUNTIME_BUNDLE_CHANGED" if bundle_changed else "RECEIPT_STALE",
            "The Runtime Bundle changed; run the live test against the staged Runner candidate to validate it"
            if bundle_changed
            else "The staged Runner candidate's live-test receipt does not match its current identity; "
            "run the live test to validate it",
            doctor_ok=True,
            sif_exists=active_exists,
            **fields,
        )
    return _result(
        family,
        RunnerReadinessStatus.BUILD_STALE,
        "CANDIDATE_AWAITING_PROMOTION",
        "A Runner image candidate is staged for promotion; activate it with the deployment-host "
        "promote-sifs step (which verifies the candidate's live-test receipt), or discard the candidate, "
        "before new submissions",
        doctor_ok=True,
        next_action="promote",
        sif_exists=active_exists,
        **fields,
    )


def resolve_runner_readiness(state, family: RuntimeFamily) -> RunnerReadiness:
    """Derive readiness for the artifact execution would load, without mutating state."""
    plugin_root = family.root.parent if family.root is not None else Path(state.get("RUNNER_SOURCE_ROOT"))
    doctor = diagnose(plugin_root, runner=family.name, repo_root=SERVER_ROOT)
    if not doctor.ok:
        errors = tuple(
            ReadinessDiagnostic(item.code, item.severity, item.component, item.message)
            for item in doctor.diagnostics
            if item.severity == "error"
        )
        messages = "; ".join(item.message for item in errors)
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "DOCTOR_FAILED",
            messages or "Runner contract validation failed",
            doctor_ok=False,
            doctor_diagnostics=errors,
            sif_exists=Path(family.slurm_image).is_file(),
        )

    active = Path(family.slurm_image)
    staged = Path(f"{family.slurm_image}.next")
    active_exists = active.is_file()
    if not active_exists and not staged.is_file():
        return _result(
            family,
            RunnerReadinessStatus.NOT_BUILT,
            "SIF_MISSING",
            "Active Runner SIF is missing",
            doctor_ok=True,
        )

    sif_sha256 = None
    build_record = None
    try:
        provenance = _build_provenance(state, family)
        build_digest = str(provenance["build_provenance_digest"])
        build_record = read_build_evidence_for_provenance(family, build_digest)
        if build_record:
            sif_sha256 = build_record.get("sif_sha256")
    except (OSError, KeyError, TypeError, ValueError, RegistryError):
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "CONFIGURATION_INVALID",
            "Runner build inputs or provenance cannot be resolved",
            doctor_ok=True,
            sif_exists=active_exists,
            sif_sha256=sif_sha256,
        )

    # A staged candidate is not the artifact execution loads.  The build/live-
    # test evidence is content-addressed and path-agnostic, so a candidate built
    # under the current provenance would otherwise make readiness adopt its
    # digest while ``<sif>`` still holds the old file (or no file at all, in the
    # first-enablement flow).  Submission readiness is a verdict about the
    # artifact that will execute, so it fails closed until the candidate is
    # promoted; the live-test action itself is unaffected because it validates
    # the candidate through the worker, not through this verdict.
    if staged.is_file():
        return _staged_candidate_readiness(state, family, build_digest, active_exists)

    try:
        build_current = not sif_stale(state, family, str(active))
    except (OSError, KeyError, TypeError, ValueError, RegistryError):
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "CONFIGURATION_INVALID",
            "Runner build inputs or provenance cannot be resolved",
            doctor_ok=True,
            sif_exists=active_exists,
            sif_sha256=sif_sha256,
        )
    if not build_current:
        return _result(
            family,
            RunnerReadinessStatus.BUILD_STALE,
            "BUILD_PROVENANCE_STALE",
            "Active Runner SIF does not match current build inputs",
            doctor_ok=True,
            sif_exists=active_exists,
            sif_sha256=sif_sha256,
            build_provenance_digest=build_digest,
        )

    evidence = _receipt_evidence(state, family, build_digest, sif_sha256)
    if evidence.failure is not None:
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "CONFIGURATION_INVALID",
            evidence.failure,
            doctor_ok=True,
            sif_exists=active_exists,
            sif_sha256=sif_sha256,
            build_provenance_current=True,
            build_provenance_digest=build_digest,
        )
    fields = evidence.fields
    receipt = evidence.receipt
    sif_sha256 = fields["sif_sha256"]
    if receipt is None and not fields["receipt_exists"]:
        return _result(
            family,
            RunnerReadinessStatus.NOT_VALIDATED,
            "RECEIPT_MISSING",
            "Active Runner SIF has no live-test receipt",
            doctor_ok=True,
            sif_exists=active_exists,
            sif_sha256=sif_sha256,
            build_provenance_current=True,
            build_provenance_digest=build_digest,
            required_smoke_cases=fields["required_smoke_cases"],
        )
    common = {"sif_exists": active_exists, **fields}
    if not fields["receipt_valid"]:
        # Distinguish "the SIF is fine, only the runtime code moved" from the
        # generic receipt mismatch: the operator action is the same live test,
        # but the diagnosis is not.
        bundle_changed = (
            fields["runtime_bundle_sha256"] is not None
            and _string_field(receipt, "runtime_bundle_sha256") != fields["runtime_bundle_sha256"]
        )
        return _result(
            family,
            RunnerReadinessStatus.VALIDATION_STALE,
            "RUNTIME_BUNDLE_CHANGED" if bundle_changed else "RECEIPT_STALE",
            "Runtime bundle changed; reuse the current SIF and rerun the live test"
            if bundle_changed
            else "Live-test receipt does not match the active Runner identity",
            doctor_ok=True,
            **common,
        )
    return _result(
        family,
        RunnerReadinessStatus.READY,
        "READY",
        "Active Runner SIF passed all required current smoke cases",
        doctor_ok=True,
        **common,
    )


def format_readiness_json(readiness: list[RunnerReadiness]) -> str:
    return json.dumps({"runners": [item.as_dict() for item in readiness]}, indent=2, sort_keys=True)


def format_readiness_text(readiness: list[RunnerReadiness], *, detailed: bool = False) -> str:
    if detailed and len(readiness) == 1:
        item = readiness[0]
        live = "CURRENT" if item.receipt_valid else ("STALE" if item.receipt_exists else "MISSING")
        build = (
            "UNKNOWN"
            if item.status is RunnerReadinessStatus.NOT_CONFIGURED
            else ("CURRENT" if item.build_provenance_current else ("STALE" if item.sif_exists else "MISSING"))
        )
        bundle = (
            "-"
            if item.runtime_bundle_sha256 is None
            else ("CURRENT" if item.receipt_runtime_bundle_sha256 == item.runtime_bundle_sha256 else "STALE")
        )
        action = (
            "reuse current SIF and rerun live-test"
            if item.reason_code == "RUNTIME_BUNDLE_CHANGED"
            else item.next_action
        )
        smoke = f"{len(item.passed_smoke_cases)}/{len(item.required_smoke_cases)} PASS"
        return "\n".join(
            (
                f"Runner Family: {item.runner_family}",
                f"Status: {item.status.value}",
                "",
                f"Doctor: {'PASS' if item.doctor_ok else 'FAIL'}",
                f"Active SIF: {item.sif_path}",
                f"SIF SHA256: {item.sif_sha256 or '-'}",
                f"Build provenance: {build}",
                f"Runtime bundle: {bundle}",
                f"Runtime bundle SHA256: {item.runtime_bundle_sha256 or '-'}",
                f"Live receipt: {live}",
                f"Last live validation: {item.receipt_tested_at or '-'}",
                f"Smoke cases: {smoke}",
                "",
                f"Reason: {item.message}",
                f"Next action: {action}",
            )
        )
    rows = [("Runner", "Doctor", "SIF", "Live test", "Status")]
    for item in readiness:
        sif = (
            "unknown"
            if item.status is RunnerReadinessStatus.NOT_CONFIGURED
            else ("current" if item.build_provenance_current else ("stale" if item.sif_exists else "missing"))
        )
        live = (
            "-"
            if item.status is RunnerReadinessStatus.NOT_CONFIGURED
            else ("current" if item.receipt_valid else ("stale" if item.receipt_exists else "missing"))
        )
        rows.append((item.runner_family, "PASS" if item.doctor_ok else "FAIL", sif, live, item.status.value))
    widths = [max(len(row[index]) for row in rows) for index in range(5)]
    return "\n".join("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in rows)


def load_instance_families(state) -> list[RuntimeFamily]:
    """Load the families and active SIF paths owned by the current deployment."""
    source_root = deployment_plugin_root(state)
    image_root = Path(state.server_dir()).parent / "images"
    return [
        replace(family, slurm_image=str(image_root / family.slurm_image))
        if not Path(family.slurm_image).is_absolute()
        else family
        for family in load_plugin_families(source_root)
    ]


def evaluate_runner_readiness(state, runner_family: str) -> RunnerReadiness:
    """Evaluate one named family against current evidence, or fail closed.

    This is the canonical entry point: the CLI, production admission, and the
    Admin API all resolve ``(state, runner_family) -> RunnerReadiness`` here, so
    they cannot disagree about a family's state, reason code, or evidence
    identity.  An unknown or disabled family is a *missing configuration*, never
    a readiness verdict another surface could read as permission.
    """
    families = [family for family in load_instance_families(state) if family.name == runner_family]
    if not families or not runner_enabled(state, runner_family):
        return RunnerReadiness(
            runner_family=runner_family,
            status=RunnerReadinessStatus.NOT_CONFIGURED,
            reason_code="RUNNER_UNKNOWN",
            message="Runner Family is not configured or not enabled on this deployment",
            doctor_ok=False,
            sif_path="",
            next_action="doctor",
        )
    return resolve_runner_readiness(state, families[0])


def evaluate_fleet_readiness(state) -> list[RunnerReadiness]:
    """Evaluate every enabled family in deterministic family order."""
    families = sorted(
        (family for family in load_instance_families(state) if runner_enabled(state, family.name)),
        key=lambda family: family.name,
    )
    return [resolve_runner_readiness(state, family) for family in families]


def runner_status_snapshot(state, *, runner: str | None, all_runners: bool) -> list[RunnerReadiness]:
    """The readiness rows the CLI status command reports, without rendering.

    Kept separate from rendering so the CLI JSON contract and any other surface
    read the same evaluated rows.
    """
    families = load_instance_families(state)
    enabled = [family for family in families if runner_enabled(state, family.name)]
    selected = enabled if all_runners else [family for family in enabled if family.name == runner]
    if not selected and not all_runners:
        raise RegistryError(f"Unknown or disabled Runner Family: {runner}")
    return [resolve_runner_readiness(state, family) for family in selected]


def run_runner_status(state, *, runner: str | None, all_runners: bool, as_json: bool) -> list[RunnerReadiness]:
    readiness = runner_status_snapshot(state, runner=runner, all_runners=all_runners)
    print(format_readiness_json(readiness) if as_json else format_readiness_text(readiness, detailed=not all_runners))
    return readiness


def _remove_host_attestation_files(state) -> None:
    """Remove files left by the pre-service publication implementation."""
    server_root = Path(state.server_dir())
    for path in (server_root / "readiness", server_root / ".readiness-publish"):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except (FileNotFoundError, PermissionError):
            continue


def invalidate_deployment_attestations(state) -> None:
    """Clear published readiness before a deployment mutation."""
    _remove_host_attestation_files(state)
