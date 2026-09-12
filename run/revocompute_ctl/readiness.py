# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Derived, read-only operational readiness for active Runner SIFs."""

from __future__ import annotations

import json
import shlex
import shutil
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from revocompute.admission import RunnerReadinessStatus
from revocompute.doctor import diagnose
from revocompute.live_tests import LiveTestConfigurationError, receipt_matches, sha256_file
from revocompute_ctl.compose import container_fs
from revocompute_ctl import SERVER_ROOT
from revocompute_ctl.live_test import load_validation_identity
from revocompute_ctl.artifact_evidence import artifact_receipt_exists, read_artifact_evidence
from revocompute_ctl.registry import (
    RegistryError,
    RuntimeFamily,
    _build_provenance,
    deployment_plugin_root,
    load_plugin_families,
    runner_enabled,
    sif_stale,
)


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
    receipt_exists: bool = False
    receipt_valid: bool = False
    receipt_tested_at: str | None = None
    receipt_sif_sha256: str | None = None
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
    **evidence: Any,
) -> RunnerReadiness:
    return RunnerReadiness(
        runner_family=family.name,
        status=status,
        reason_code=reason_code,
        message=message,
        doctor_ok=doctor_ok,
        sif_path=family.slurm_image,
        next_action={
            RunnerReadinessStatus.NOT_CONFIGURED: "doctor",
            RunnerReadinessStatus.NOT_BUILT: "build-sif",
            RunnerReadinessStatus.BUILD_STALE: "build-sif",
            RunnerReadinessStatus.NOT_VALIDATED: "live-test",
            RunnerReadinessStatus.VALIDATION_STALE: "live-test",
            RunnerReadinessStatus.READY: "none",
        }[status],
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


def resolve_runner_readiness(state, family: RuntimeFamily) -> RunnerReadiness:
    """Derive readiness from current contracts and the active artifact without mutating state."""
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
    if not active.is_file():
        return _result(
            family,
            RunnerReadinessStatus.NOT_BUILT,
            "SIF_MISSING",
            "Active Runner SIF is missing",
            doctor_ok=True,
        )

    sif_sha256 = sha256_file(active)
    try:
        provenance = _build_provenance(state, family)
        build_digest = str(provenance["build_provenance_digest"])
        build_current = not sif_stale(state, family, str(active))
    except (OSError, KeyError, TypeError, ValueError, RegistryError):
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "CONFIGURATION_INVALID",
            "Runner build inputs or provenance cannot be resolved",
            doctor_ok=True,
            sif_exists=True,
            sif_sha256=sif_sha256,
        )
    if not build_current:
        return _result(
            family,
            RunnerReadinessStatus.BUILD_STALE,
            "BUILD_PROVENANCE_STALE",
            "Active Runner SIF does not match current build inputs",
            doctor_ok=True,
            sif_exists=True,
            sif_sha256=sif_sha256,
            build_provenance_digest=build_digest,
        )

    try:
        identity = load_validation_identity(family, state=state)
        required = tuple(sorted(case.id for case in identity.plan.select("smoke")))
    except (OSError, KeyError, TypeError, ValueError, StopIteration, LiveTestConfigurationError, RegistryError):
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "CONFIGURATION_INVALID",
            "Runner live-test identity cannot be resolved",
            doctor_ok=True,
            sif_exists=True,
            sif_sha256=sif_sha256,
            build_provenance_current=True,
            build_provenance_digest=build_digest,
        )

    try:
        expected_uid = int(state.get("RUNNER_UID")) if state.get("RUNNER_UID") else None
        expected_gid = int(state.get("RUNNER_GID")) if state.get("RUNNER_GID") else None
        expected_scheduler_user = state.get("RUNNER_USERNAME") or None
    except (TypeError, ValueError):
        return _result(
            family,
            RunnerReadinessStatus.NOT_CONFIGURED,
            "CONFIGURATION_INVALID",
            "Configured Runner UID/GID are not numeric",
            doctor_ok=True,
            sif_exists=True,
            sif_sha256=sif_sha256,
            build_provenance_current=True,
            build_provenance_digest=build_digest,
        )
    expected_identity = {
        "build_provenance_digest": build_digest,
        "test_definition_digest": identity.plan.digest,
        "configuration_digest": identity.configuration_digest,
        "execution_uid": expected_uid,
        "execution_gid": expected_gid,
        "scheduler_user": expected_scheduler_user,
    }
    _actual_sha256, receipt = read_artifact_evidence(
        family, active, "receipt", receipt_identity=expected_identity
    )
    receipt_exists = artifact_receipt_exists(family, sif_sha256)
    if receipt is None and not receipt_exists:
        return _result(
            family,
            RunnerReadinessStatus.NOT_VALIDATED,
            "RECEIPT_MISSING",
            "Active Runner SIF has no live-test receipt",
            doctor_ok=True,
            sif_exists=True,
            sif_sha256=sif_sha256,
            build_provenance_current=True,
            build_provenance_digest=build_digest,
            required_smoke_cases=required,
        )

    passed = _passed_case_ids(receipt or {})
    valid = bool(receipt) and receipt_matches(
        receipt,
        sif_sha256=sif_sha256,
        build_provenance_digest=build_digest,
        test_definition_digest=identity.plan.digest,
        configuration_digest=identity.configuration_digest,
        required_case_ids=set(required),
        expected_execution_uid=expected_uid,
        expected_execution_gid=expected_gid,
        expected_scheduler_user=expected_scheduler_user,
    )
    common = {
        "sif_exists": True,
        "sif_sha256": sif_sha256,
        "build_provenance_current": True,
        "build_provenance_digest": build_digest,
        "receipt_exists": receipt_exists,
        "receipt_valid": valid,
        "receipt_tested_at": _string_field(receipt, "ended_at"),
        "receipt_sif_sha256": _string_field(receipt, "sif_sha256"),
        "receipt_configuration_digest": _string_field(receipt, "configuration_digest"),
        "receipt_test_definition_digest": _string_field(receipt, "test_definition_digest"),
        "required_smoke_cases": required,
        "passed_smoke_cases": passed,
    }
    if not valid:
        return _result(
            family,
            RunnerReadinessStatus.VALIDATION_STALE,
            "RECEIPT_STALE",
            "Live-test receipt does not match the active Runner identity",
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
                f"Live receipt: {live}",
                f"Last live validation: {item.receipt_tested_at or '-'}",
                f"Smoke cases: {smoke}",
                "",
                f"Reason: {item.message}",
                f"Next action: {item.next_action}",
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


def run_runner_status(state, *, runner: str | None, all_runners: bool, as_json: bool) -> list[RunnerReadiness]:
    families = load_instance_families(state)
    enabled = [family for family in families if runner_enabled(state, family.name)]
    selected = enabled if all_runners else [family for family in enabled if family.name == runner]
    if not selected and not all_runners:
        raise RegistryError(f"Unknown or disabled Runner Family: {runner}")
    readiness = [resolve_runner_readiness(state, family) for family in selected]
    print(format_readiness_json(readiness) if as_json else format_readiness_text(readiness, detailed=not all_runners))
    return readiness


def resolve_submission_readiness(state, runner_name: str) -> RunnerReadiness:
    """Resolve the current readiness evidence for a Runner used by a submission.

    This deliberately shares the exact resolver used by ``runner-status`` so
    the API cannot accept a Runner under a different definition of READY.
    Disabled or unknown families fail closed as NOT_CONFIGURED.
    """
    try:
        families = load_instance_families(state)
    except (OSError, RegistryError, ValueError):
        return RunnerReadiness(
            runner_family=runner_name,
            status=RunnerReadinessStatus.NOT_CONFIGURED,
            reason_code="RUNNER_UNAVAILABLE",
            message="Runner configuration cannot be resolved in this deployment",
            doctor_ok=False,
            sif_path="",
            next_action="doctor",
        )
    family = next((item for item in families if item.name == runner_name), None)
    if family is None or not runner_enabled(state, runner_name):
        return RunnerReadiness(
            runner_family=runner_name,
            status=RunnerReadinessStatus.NOT_CONFIGURED,
            reason_code="RUNNER_UNAVAILABLE",
            message="Runner is not configured or enabled in this deployment",
            doctor_ok=False,
            sif_path=family.slurm_image if family is not None else "",
            next_action="doctor",
        )
    return resolve_runner_readiness(state, family)


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
    """Clear readiness before deployment mutation, using the service identity."""
    _remove_host_attestation_files(state)
    server_root = Path(state.server_dir())
    if not any((server_root / name).exists() for name in ("readiness", ".readiness-publish")):
        return
    container_fs(
        state,
        "set -eu; rm -rf /srv/readiness /srv/.readiness-publish",
        [(state.server_dir(), "/srv")],
    )


def _publish_attestation(state, family: RuntimeFamily, payload: dict[str, Any]) -> None:
    filename = f"{family.name}.json"
    temporary = f"/srv/.readiness-publish/.{family.name}.json.$$"
    script = (
        "set -eu; umask 022; mkdir -p /srv/.readiness-publish; chmod 0755 /srv/.readiness-publish; "
        f"tmp=\"{temporary}\"; trap 'rm -f \"$tmp\"' EXIT; "
        "cat > \"$tmp\"; chmod 0644 \"$tmp\"; "
        f"mv -f \"$tmp\" /srv/.readiness-publish/{shlex.quote(filename)}; trap - EXIT"
    )
    container_fs(
        state,
        script,
        [(state.server_dir(), "/srv")],
        stdin_data=json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    )


def write_submission_attestation(state, families: list[RuntimeFamily]) -> None:
    """Publish complete readiness evidence as the configured service identity."""
    try:
        payloads = [
            (
                family,
                resolve_runner_readiness(state, family).as_dict(),
            )
            for family in families
            if runner_enabled(state, family.name)
        ]
        container_fs(
            state,
            "set -eu; umask 022; rm -rf /srv/.readiness-publish; mkdir -m 0755 /srv/.readiness-publish",
            [(state.server_dir(), "/srv")],
        )
        for family, payload in payloads:
            _publish_attestation(state, family, payload)
        container_fs(
            state,
            "set -eu; rm -rf /srv/readiness; mv /srv/.readiness-publish /srv/readiness; chmod 0755 /srv/readiness",
            [(state.server_dir(), "/srv")],
        )
    except BaseException:
        try:
            invalidate_deployment_attestations(state)
        except BaseException:
            pass
        raise
