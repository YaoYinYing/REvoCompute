# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deterministic canonical payload builders for the frontend fixture harness.

Every builder returns the payload the production server would project for the
same state. The builders that build a response *body* validate it against a
canonical OpenAPI component before returning, so a fixture fails loudly when
that contract changes. The router hand-builds a few small bodies (access
policies, archive actions, task actions) that this check does not cover.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

from .models import (
    AccessState,
    ArchiveSpec,
    DEFAULT_SHA256,
    DEFAULT_TASK_ID,
    DEFAULT_SUBMITTED_AT,
    DEFAULT_FINISHED_AT,
    OutputCheckSpec,
    ParameterSpec,
    PreflightAdmission,
    PreflightInput,
    PreflightSpec,
    ReadinessState,
    RunnerDefinition,
)

# ---------------------------------------------------------------------------
# Canonical schema access
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def openapi_spec() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "revocompute" / "static" / "openapi.json").read_text(encoding="utf-8"))


def validate_payload(schema_name: str, payload: object) -> None:
    """Validate one fixture payload against a canonical OpenAPI component.

    The harness is the only thing that can drift here, so a mismatch is an
    assertion failure naming the schema and the first violation.
    """
    from jsonschema import Draft202012Validator

    spec = openapi_spec()
    validator = Draft202012Validator(
        {"$ref": f"#/components/schemas/{schema_name}", "components": spec["components"]},
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise AssertionError(f"{schema_name} fixture violates the canonical contract at {location}: {first.message}")


# ---------------------------------------------------------------------------
# Runner discovery: catalog, detail, parameters, workspace
# ---------------------------------------------------------------------------

# capability → (artifact preview, default media type). Preview is the manifest
# rendering hint; capabilities without an inline preview (plot, archive,
# download_only, unknown) must declare no preview.
_CAPABILITY_PREVIEW: dict[str, str | None] = {
    "molecular_structure": "structure",
    "table": "table",
    "text": "text",
    "image": "image",
    "plot": None,
    "archive": None,
    "download_only": None,
    "unknown": None,
}
_CAPABILITY_MEDIA_TYPE: dict[str, str] = {
    "molecular_structure": "chemical/x-pdb",
    "table": "text/csv",
    "text": "text/plain",
    "image": "image/png",
    "plot": "image/png",
    "archive": "application/zip",
    "download_only": "application/octet-stream",
    "unknown": "application/octet-stream",
}


def catalog_access_payload(access: AccessState) -> dict[str, Any]:
    if not access.restricted:
        return {"restricted": False, "granted": True, "request_status": None}
    return {"restricted": True, "granted": access.granted, "request_status": access.request_status}


def runner_access_payload(access: AccessState) -> dict[str, Any]:
    if not access.restricted:
        return {"restricted": False}
    payload: dict[str, Any] = {
        "restricted": True,
        "policy_id": access.policy_id,
        "label": access.label,
        "description": access.description,
        "requestable": access.requestable,
        "granted": access.granted,
        "request_status": access.request_status,
        "notice": {"title": access.notice_title, "summary": access.notice_summary},
        "license": {"name": access.license_name, "url": access.license_url},
    }
    return payload


def build_runner_summary(definition: RunnerDefinition) -> dict[str, Any]:
    payload = {
        "name": definition.name,
        "display_name": definition.display_name,
        "category": definition.category,
        "summary": definition.summary,
        "access": catalog_access_payload(definition.access),
        "detail_url": f"/compute/api/types/{definition.name}",
        "parameters_url": f"/compute/api/task-parameters/{definition.name}",
    }
    validate_payload("TaskTypeSummary", payload)
    return payload


def build_catalog(definitions: Sequence[RunnerDefinition]) -> dict[str, Any]:
    """Project an ordered Runner catalog, one category entry per used category."""
    categories: list[dict[str, str]] = []
    for definition in definitions:
        if not any(entry["name"] == definition.category for entry in categories):
            categories.append({"name": definition.category, "label": definition.category_label})
    payload = {
        "version": 3,
        "categories": categories,
        "task_types": [build_runner_summary(definition) for definition in definitions],
    }
    validate_payload("TaskCatalog", payload)
    return payload


def build_input_role(role: Any) -> dict[str, Any]:
    return {
        "id": role.id,
        "title": role.title,
        "type": role.logical_type,
        "formats": list(role.formats),
        "extensions": list(role.extensions),
        "accept": ",".join(role.extensions),
        "cardinality": {"min": role.minimum, "max": role.maximum},
        "description": role.description,
    }


def build_input_workspace(definition: RunnerDefinition) -> dict[str, Any]:
    payload = {
        "version": 3,
        "plugins": [],
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "description": step.description,
                "capabilities": [
                    {
                        "plugin": capability.plugin,
                        "id": capability.id,
                        "title": capability.title,
                        "description": capability.description,
                        "options": capability.option_map(),
                    }
                    for capability in step.capabilities
                ],
            }
            for step in definition.workspace_steps
        ],
    }
    return payload


def build_detail(definition: RunnerDefinition) -> dict[str, Any]:
    payload = {
        "name": definition.name,
        "display_name": definition.display_name,
        "category": definition.category,
        "summary": definition.summary,
        "use_when": definition.use_when,
        "input_summary": definition.input_summary,
        "output_summary": definition.output_summary,
        "considerations": list(definition.considerations),
        "access": runner_access_payload(definition.access),
        "detail_url": f"/compute/api/types/{definition.name}",
        "parameters_url": f"/compute/api/task-parameters/{definition.name}",
        "definition_version": 4,
        "runtime_family": definition.runtime_family,
        "gpus": definition.gpus,
        "requires_network": definition.requires_network,
        "inputs": [build_input_role(role) for role in definition.inputs],
        "citations": [
            {"num": citation.num, "doi": citation.doi, "title": citation.title, "url": citation.url}
            for citation in definition.citations
        ],
        "workflow": [
            {
                "name": stage.name,
                "display_name": stage.display_name,
                "requires_gpu": stage.requires_gpu,
                "requires_network": stage.requires_network,
                "stage_markers": list(stage.stage_markers),
            }
            for stage in definition.workflow
        ],
        "max_request_bytes": definition.max_request_bytes,
        "input_workspace": build_input_workspace(definition),
    }
    validate_payload("TaskTypeDetail", payload)
    return payload


def build_parameter_schema(definition: RunnerDefinition) -> dict[str, Any]:
    """Project declared Task parameters into the task-owned parameter schema."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in definition.parameters:
        properties[parameter.name] = parameter_property(parameter)
        if parameter.required:
            required.append(parameter.name)
    payload: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if required:
        payload["required"] = required
    validate_payload("TaskParameterSchema", payload)
    return payload


def parameter_property(parameter: ParameterSpec) -> dict[str, Any]:
    prop: dict[str, Any] = {"type": parameter.type}
    if parameter.has_default:
        prop["default"] = parameter.default
    if parameter.description:
        prop["description"] = parameter.description
    if parameter.choices:
        prop["enum"] = list(parameter.choices)
    if parameter.minimum is not None:
        prop["minimum"] = parameter.minimum
    if parameter.exclusive_minimum is not None:
        prop["exclusiveMinimum"] = parameter.exclusive_minimum
    if parameter.maximum is not None:
        prop["maximum"] = parameter.maximum
    if parameter.multiple_of is not None:
        prop["multipleOf"] = parameter.multiple_of
    if parameter.unit:
        prop["x-unit"] = parameter.unit
    if parameter.help:
        prop["x-help"] = parameter.help
    if parameter.advanced:
        prop["x-advanced"] = True
    if parameter.ui_control:
        prop["x-ui-control"] = dict(parameter.ui_control)
    return prop


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

def build_infrastructure(state: ReadinessState) -> dict[str, Any]:
    """Project infrastructure readiness with the component groups the UI reads.

    Capacity is reported per resource group: the aggregate status can be READY
    while the scheduler is BUSY or the GPU inventory is empty, and the UI keys
    its admission wording off the group, not the aggregate.
    """
    checked_at = f"{DEFAULT_SUBMITTED_AT}"
    groups: dict[str, dict[str, Any]] = {
        "infrastructure": {"label": "Infrastructure", "status": state.status, "stale": state.stale},
        "scheduler": {
            "label": "Scheduler",
            "status": state.status,
            "stale": state.stale,
            "capacity": state.scheduler_capacity,
        },
        "gpu": {"label": "GPU", "status": state.status, "stale": state.stale, "capacity": state.gpu_capacity},
        "worker": {"label": "Worker", "status": state.worker_status, "stale": state.stale},
        "storage": {"label": "Storage", "status": state.status, "stale": state.stale},
    }
    payload: dict[str, Any] = {
        "status": state.status,
        "checked_at": checked_at,
        "stale": state.stale,
        "summary": groups,
    }
    if state.include_components:
        payload["components"] = [
            _component(
                "celery_worker",
                state.worker_status,
                "worker_healthy" if state.worker_status == "READY" else "worker_unavailable",
                state,
            ),
            _component(
                "slurm_controller",
                state.status,
                "slurm_controller_healthy" if state.status == "READY" else "slurm_controller_unreachable",
                state,
                capacity=state.scheduler_capacity,
            ),
        ]
    validate_payload("InfrastructureReadiness", payload)
    return payload


def _component(component: str, status: str, reason_code: str, state: ReadinessState, *, capacity: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "component": component,
        "status": status,
        "reason_code": reason_code,
        "message": "Component evidence for the fixture scenario.",
        "checked_at": DEFAULT_SUBMITTED_AT,
        "duration_ms": 4,
        "failure_count": 0,
        "stale": state.stale,
    }
    if capacity is not None:
        payload["capacity"] = capacity
    return payload


# ---------------------------------------------------------------------------
# Preflight and submission
# ---------------------------------------------------------------------------

# Every preflight outcome names the response shape the server produces for it:
# a completed validation is 200, a rejected contract or security check is 400,
# a denied admission is 403, and an unavailable Runner or infrastructure is 503.
_PREFLIGHT_OUTCOMES: dict[str, dict[str, Any]] = {
    "valid": {"valid": True, "security": "passed", "contract": "passed", "http_status": 200},
    "warning": {"valid": True, "security": "passed", "contract": "passed", "http_status": 200},
    "invalid_security": {"valid": False, "security": "failed", "contract": "not_checked", "http_status": 400},
    "invalid_contract": {"valid": False, "security": "not_checked", "contract": "failed", "http_status": 400},
    "runner_not_ready": {"valid": False, "security": "not_checked", "contract": "not_checked", "http_status": 503},
    "infrastructure_not_ready": {"valid": False, "security": "not_checked", "contract": "not_checked", "http_status": 503},
    "access_denied": {"valid": False, "security": "not_checked", "contract": "not_checked", "http_status": 403},
    "capacity_busy": {"valid": True, "security": "passed", "contract": "passed", "http_status": 200},
    "gpu_credit_exhausted": {"valid": False, "security": "not_checked", "contract": "not_checked", "http_status": 403},
}

_PREFLIGHT_ERROR_CODES = {
    "invalid_security": "input_format_invalid",
    "invalid_contract": "contract_invalid",
    "runner_not_ready": "admission_unavailable",
    "infrastructure_not_ready": "infrastructure_unavailable",
    "access_denied": "admission_denied",
    "gpu_credit_exhausted": "gpu_credit_exhausted",
}


def preflight_fixture(
    kind: str,
    *,
    errors: Iterable[tuple[str, str]] = (),
    warnings: Iterable[tuple[str, str]] = (),
    error_message: str | None = None,
    warning_message: str | None = None,
) -> PreflightSpec:
    """Return a named preflight outcome with the canonical response code."""
    if kind not in _PREFLIGHT_OUTCOMES:
        raise KeyError(f"Unknown preflight fixture {kind!r}; available: {sorted(_PREFLIGHT_OUTCOMES)}")
    findings = list(errors)
    if error_message is not None:
        findings.append((_PREFLIGHT_ERROR_CODES.get(kind, "contract_invalid"), error_message))
    notices = list(warnings)
    if warning_message is not None:
        notices.append(("contract_warning", warning_message))
    return PreflightSpec(kind=kind, errors=tuple(findings), warnings=tuple(notices))


# Named preflight capabilities, resolvable by scenario and by test.
PREFLIGHT_FIXTURES: dict[str, PreflightSpec] = {
    "valid": preflight_fixture("valid"),
    "warning": preflight_fixture("warning", warning_message="Inputs will be re-numbered from 1."),
    "invalid_security": preflight_fixture("invalid_security", error_message="Uploaded input is not valid FASTA."),
    "invalid_contract": preflight_fixture("invalid_contract", error_message="Parameter 'iterations' must be at least 1."),
    "runner_not_ready": preflight_fixture("runner_not_ready", error_message="Runner is currently unavailable for new submissions"),
    "infrastructure_not_ready": preflight_fixture("infrastructure_not_ready", error_message="Compute infrastructure is currently unavailable for new submissions"),
    "access_denied": preflight_fixture("access_denied", error_message="Runner access approval is required."),
    "capacity_busy": preflight_fixture("capacity_busy", warning_message="The scheduler is busy; the task will queue."),
    "gpu_credit_exhausted": preflight_fixture("gpu_credit_exhausted", error_message="GPU credit balance is exhausted for the current UTC month"),
}


def _finding(code: str, message: str, *, blocking: bool) -> dict[str, Any]:
    return {"code": code, "message": message, "blocking": blocking}


def build_preflight(
    definition: RunnerDefinition,
    spec: PreflightSpec,
) -> tuple[dict[str, Any], int]:
    """Build one canonical preflight response and the HTTP status it carries."""
    outcome = _PREFLIGHT_OUTCOMES.get(spec.kind, _PREFLIGHT_OUTCOMES["valid"])
    errors = [_finding(code, message, blocking=True) for code, message in spec.errors]
    warnings = [_finding(code, message, blocking=False) for code, message in spec.warnings]
    admission_spec = spec.admission or _admission_for(spec.kind)
    admission: dict[str, Any] = {
        "allowed": admission_spec.allowed and not errors,
        "runner_ready": admission_spec.runner_ready,
        "infrastructure_ready": admission_spec.infrastructure_ready,
        "infrastructure_status": admission_spec.infrastructure_status,
        "scheduler_capacity": admission_spec.scheduler_capacity,
        "gpu_capacity": admission_spec.gpu_capacity,
    }
    # A completed validation echoes the Runner's resolved defaults and inputs;
    # a rejected admission/contract/security check returns before resolution, so
    # the server sends an empty normalization and no resolved inputs (its two
    # result fields default to ``{}``/``[]``). ``None`` means "use the shape
    # this outcome really produces"; an explicit value wins, so a test can pin
    # either an intentionally-empty or an overridden projection.
    if spec.normalized_params is not None:
        normalized_params = dict(spec.normalized_params)
    elif outcome["valid"]:
        normalized_params = {
            parameter.name: parameter.default for parameter in definition.parameters if parameter.has_default
        }
    else:
        normalized_params = {}
    if spec.inputs is not None:
        input_specs = spec.inputs
    elif outcome["valid"]:
        input_specs = _default_preflight_inputs(definition)
    else:
        input_specs = []
    payload: dict[str, Any] = {
        "valid": outcome["valid"] and not errors,
        "security": {"status": outcome["security"]},
        "contract": {"status": outcome["contract"]},
        "admission": admission,
        "normalized_params": normalized_params,
        "inputs": [{"role": item.role, "format": item.format, "path": item.path} for item in input_specs],
        "warnings": warnings,
        "errors": errors,
    }
    status = spec.http_status or int(outcome["http_status"])
    if not payload["valid"] and status < 400:
        status = 400
    validate_payload("TaskPreflight", payload)
    return payload, status


def _default_preflight_inputs(definition: RunnerDefinition) -> list[PreflightInput]:
    entries: list[PreflightInput] = []
    for role in definition.inputs:
        fmt = role.formats[0] if role.formats else "text"
        extension = role.extensions[0] if role.extensions else ".txt"
        entries.append(PreflightInput(role=role.id, format=fmt, path=f"sample{extension}"))
    return entries


def _admission_for(kind: str) -> PreflightAdmission:
    if kind in {"runner_not_ready"}:
        return PreflightAdmission(allowed=False, runner_ready=False, infrastructure_ready=True, infrastructure_status="READY")
    if kind in {"infrastructure_not_ready"}:
        return PreflightAdmission(
            allowed=False, runner_ready=True, infrastructure_ready=False, infrastructure_status="UNAVAILABLE",
        )
    if kind == "access_denied":
        return PreflightAdmission(allowed=False, runner_ready=True, infrastructure_ready=True, infrastructure_status="READY")
    if kind == "gpu_credit_exhausted":
        return PreflightAdmission(allowed=False, runner_ready=True, infrastructure_ready=True, infrastructure_status="READY")
    if kind == "capacity_busy":
        return PreflightAdmission(allowed=True, runner_ready=True, infrastructure_ready=True, infrastructure_status="READY", scheduler_capacity="BUSY")
    return PreflightAdmission()


def build_submit(task_id: str, definition: RunnerDefinition, *, status: str = "queued") -> tuple[dict[str, Any], int]:
    """Build the accepted-submission response the browser follows to the dashboard.

    The real endpoint answers 302 to the status URL for a freshly accepted Task.
    A fixture returns the server's 202 form instead: a followed redirect is
    resolved by the browser's network stack rather than by the route handler, so
    a fixture that returned 302 would leave the frontend with a failed fetch.
    The ``Location`` header is still set, because that is what the server sends.
    """
    payload = build_task_status(task_id, definition, status)
    return payload, 202


def build_task_status(
    task_id: str,
    definition: RunnerDefinition,
    status: str,
    *,
    result_available: bool = False,
    display_name: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": task_id,
        "md5sum": task_id,
        "task_type": definition.name,
        "display_name": display_name or _default_display_name(definition),
        "status": status,
        "terminal": _terminal(status),
        "status_url": f"/compute/api/running/{task_id}",
        "results_url": f"/compute/api/results/{task_id}",
        "result_available": result_available,
    }
    if error:
        payload["error"] = error
    validate_payload("TaskStatus", payload)
    return payload


def _terminal(status: str) -> bool:
    from revocompute.db import TaskDatabase

    return status in TaskDatabase.STOP_POLLING_STATUSES


def build_task_summary(
    task_id: str,
    definition: RunnerDefinition,
    *,
    status: str = "finished",
    result_available: bool = True,
    archive_ready: bool = False,
    owner: str | None = None,
    error: str | None = None,
    outcome: str | None = "SUCCESS",
    submitted_at: str = DEFAULT_SUBMITTED_AT,
    finished_at: str = DEFAULT_FINISHED_AT,
    walltime_seconds: float | None = 3.0,
    progress: Mapping[str, object] | None = None,
    input_preview: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build one dashboard task summary, including its authorized action URLs."""
    terminal = _terminal(status)
    cancellable = status in {"pending", "queued", "running"}
    payload: dict[str, Any] = {
        "task_id": task_id,
        "task_type": definition.name,
        "display_name": _default_display_name(definition),
        "status": status,
        "terminal": terminal,
        "submitted_at": submitted_at,
        "finished_at": finished_at if terminal else None,
        "walltime_seconds": walltime_seconds if terminal else None,
        "owner": owner,
        "progress": dict(progress) if progress else None,
        "outcome": outcome if status == "finished" else None,
        "error": error,
        "result": {
            "available": result_available,
            # A fixture that publishes nothing is in the ordinary not-yet state;
            # the vocabulary itself is server-owned and validated by the schema.
            "publication": "available" if result_available else "not_finalized",
            "page_url": f"/compute/results/{task_id}",
            "manifest_url": f"/compute/api/results/{task_id}",
            # Mirror the server: a result that is not available offers no archive
            # affordance at all, because every one of them would be refused.
            "archive_ready": archive_ready and result_available,
            "archive_request_allowed": status in {"finished", "failed"} and result_available and not archive_ready,
            "archive_request_url": f"/compute/api/results/{task_id}/archive",
            "download_url": f"/compute/api/download/{task_id}" if archive_ready and result_available else None,
        },
        "actions": {
            "cancel": {"allowed": cancellable, "url": f"/compute/api/cancel/{task_id}"},
            # Deletion is offered for every state the caller can see; only the
            # cleanup-claim states withdraw it, which no fixture reaches.
            "delete": {"allowed": True, "url": f"/compute/api/delete/{task_id}"},
        },
        "input_preview": dict(input_preview) if input_preview else None,
    }
    validate_payload("TaskSummary", payload)
    return payload


def _default_display_name(definition: RunnerDefinition) -> str:
    role = definition.inputs[0] if definition.inputs else None
    extension = role.extensions[0] if role and role.extensions else ".fasta"
    return f"sample{extension}"


# ---------------------------------------------------------------------------
# Result manifests
# ---------------------------------------------------------------------------


def _artifact(spec: ResultArtifactSpec, task_id: str) -> dict[str, Any]:
    capability = spec.capability
    preview = spec.preview if spec.preview is not None else _CAPABILITY_PREVIEW.get(capability)
    payload: dict[str, Any] = {
        "path": spec.path,
        "size": spec.size,
        "sha256": DEFAULT_SHA256,
        "media_type": spec.media_type or _CAPABILITY_MEDIA_TYPE.get(capability, "application/octet-stream"),
        "preview": preview,
        "capability": capability,
        "role": spec.role,
        "url": f"/compute/api/results/{task_id}/artifacts/{quote(spec.path, safe='/')}",
    }
    if spec.confidence_encoding:
        payload["confidence_encoding"] = spec.confidence_encoding
    if capability == "table":
        payload["table_url"] = f"/compute/api/results/{task_id}/tables/{quote(spec.path, safe='/')}"
    if Path(spec.path).suffix.lower() in {".csv", ".json", ".npy", ".npz", ".tsv"}:
        payload["ndarray_url"] = f"/compute/api/results/{task_id}/ndarrays/{quote(spec.path, safe='/')}"
    return payload


def _logical_file(file_id: str, entry: Mapping[str, Any], index: int, task_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": file_id,
        "name": Path(str(entry["path"])).name,
        "media_type": entry["media_type"],
        "size": entry["size"],
        "role": entry["role"],
        "cardinality": entry.get("cardinality", "one"),
        "viewer": entry.get("viewer") or entry["preview"] or "download",
        "preview": entry["preview"],
        "capability": entry["capability"],
        "url": f"/compute/api/results/{task_id}/files/{file_id}?index={index}",
    }
    if entry.get("confidence_encoding"):
        payload["confidence_encoding"] = entry["confidence_encoding"]
    if entry["capability"] == "table":
        payload["table_url"] = f"/compute/api/results/{task_id}/tables/{quote(str(entry['path']), safe='/')}"
    if Path(str(entry["path"])).suffix.lower() in {".csv", ".json", ".npy", ".npz", ".tsv"}:
        payload["ndarray_url"] = f"/compute/api/results/{task_id}/ndarrays/{quote(str(entry['path']), safe='/')}"
    return payload


def _run_record(fixture: ResultFixture, definition: RunnerDefinition | None) -> dict[str, Any]:
    display_name = definition.display_name if definition else "Example method"
    return {
        "method": {
            "id": definition.name if definition else fixture.task_type,
            "name": display_name,
            "summary": definition.summary if definition else "",
            "output_summary": definition.output_summary if definition else "",
        },
        "inputs": [
            {"role": role, "path": path, "sha256": DEFAULT_SHA256, "format": fmt, "logical_type": fmt}
            for role, path, fmt in fixture.run_inputs
        ],
        "parameters": [
            {"name": name, "label": label, "value": value, "unit": unit}
            for name, label, value, unit in fixture.run_parameters
        ],
        "submitted_at": DEFAULT_SUBMITTED_AT,
        "started_at": DEFAULT_SUBMITTED_AT,
        "finished_at": DEFAULT_FINISHED_AT,
        "walltime_seconds": 3.0,
        "citations": [
            {"num": citation.num, "doi": citation.doi, "title": citation.title, "url": citation.url}
            for citation in (definition.citations if definition else ())
        ],
    }


def _work_item_projection(items: Sequence[WorkerView]) -> dict[str, Any]:
    """Derive the standardized outcome and progress counts from item states.

    The vocabulary mirrors ``resolve_work_item_projection``: item states are
    Runner-owned, and the aggregate outcome is derived rather than reported.
    """
    from revocompute.resource_observations import derive_outcome, progress_counts

    projection = [
        {"id": item.id, "status": item.status, "attempts": item.attempts, "output_path": item.output_path, "error": item.error}
        for item in items
    ]
    return {
        "outcome": derive_outcome(projection),
        "work_items": projection,
        "progress": progress_counts(projection),
    }


def build_result_manifest(
    fixture: ResultFixture,
    definition: RunnerDefinition | None = None,
    *,
    task_id: str = DEFAULT_TASK_ID,
) -> dict[str, Any]:
    """Build one canonical ResultManifest for a rendering-class fixture."""
    artifacts = [_artifact(spec, task_id) for spec in fixture.artifacts]
    by_path = {artifact["path"]: artifact for artifact in artifacts}
    logical: dict[str, list[dict[str, Any]]] = {}
    for file_id, paths in fixture.logical_file_paths().items():
        entries = []
        for index, path in enumerate(paths):
            artifact = by_path[path]
            entry = {**artifact, "cardinality": "many" if len(paths) > 1 else "one", "viewer": artifact["preview"] or "download"}
            entries.append(_logical_file(file_id, entry, index, task_id))
        logical[file_id] = entries
    archive_spec = fixture.archive or ArchiveSpec()
    # ``task_type`` is manifest identity, so it must agree with the mounted
    # Runner (``run.method.id``). A reusable rendering fixture keeps its own
    # ``task_type`` only when it is mounted standalone with no definition.
    manifest: dict[str, Any] = {
        "schema_version": 3,
        "task_id": task_id,
        "task_type": definition.name if definition is not None else fixture.task_type,
        "created_at": fixture.created_at,
        "status": fixture.status,
        "terminal": True,
        "error": fixture.error,
        "run": _run_record(fixture, definition),
        "output_check": {
            "state": fixture.output_check.state,
            "checks": fixture.output_check.check_maps(),
            "problems": list(fixture.output_check.problems),
        },
        "limitations": list(fixture.limitations),
        "views": fixture.view_maps(),
        "artifacts": artifacts,
        "result": {"files": logical},
        "storyboard": None,
        "outcome": fixture.outcome,
        "total_size": sum(artifact["size"] for artifact in artifacts),
        "archive": {
            "ready": archive_spec.requested,
            "request_url": f"/compute/api/results/{task_id}/archive",
            "download_url": f"/compute/api/download/{task_id}" if archive_spec.requested else None,
        },
    }
    if fixture.storyboard is not None:
        manifest["storyboard"] = {
            "identifier": fixture.storyboard.identifier,
            "entrypoint": fixture.storyboard.entrypoint,
            "entrypoint_url": f"/compute/api/results/{task_id}/storyboard/{fixture.storyboard.entrypoint}",
            "requires": list(fixture.storyboard.requires),
            "optional": list(fixture.storyboard.optional),
        }
    if fixture.work_items:
        projection = _work_item_projection(fixture.work_items)
        manifest["outcome"] = projection["outcome"]
        manifest["work_items"] = projection["work_items"]
        manifest["progress"] = projection["progress"]
    validate_payload("ResultManifest", manifest)
    return manifest


# ---------------------------------------------------------------------------
# Bounded result sub-resources
# ---------------------------------------------------------------------------


def view_entry(
    plugin: str,
    view_id: str,
    title: str,
    sources: Mapping[str, Sequence[str]],
    *,
    role: str = "primary",
    description: str = "",
    **mapping: object,
) -> tuple[tuple[str, object], ...]:
    """One ResultView entry, in the tuple form a manifest fixture stores."""
    return (
        ("id", view_id),
        ("plugin", plugin),
        ("role", role),
        ("title", title),
        ("description", description),
        ("sources", {name: list(paths) for name, paths in sources.items()}),
        ("mapping", dict(mapping)),
    )


def build_table_page(columns: Sequence[str], rows: Sequence[Sequence[object]], *, offset: int = 0) -> dict[str, Any]:
    payload = {
        "columns": [str(column) for column in columns],
        "rows": [[str(value) for value in row] for row in rows],
        "offset": offset,
        "limit": 100,
        "has_more": False,
    }
    validate_payload("TablePage", payload)
    return payload


def build_matrix_projection(values: Sequence[float], *, shape: Sequence[int] | None = None, key: str | None = None) -> dict[str, Any]:
    """Build a bounded numeric projection for a matrix- or series-capable artifact."""
    dimensions = list(shape) if shape is not None else [len(values)]
    payload = {
        "kind": "numeric",
        "dtype": "<f8",
        "shape": dimensions,
        "key": key,
        "total_elements": len(values),
        "data": [float(value) for value in values],
    }
    validate_payload("ArrayProjection", payload)
    return payload


def build_categorical_projection(values: Sequence[str], *, key: str | None = None) -> dict[str, Any]:
    payload = {
        "kind": "categorical",
        "dtype": "string",
        "shape": [len(values)],
        "key": key,
        "total_elements": len(values),
        "data": [str(value) for value in values],
    }
    validate_payload("ArrayProjection", payload)
    return payload


__all__ = [
    "PREFLIGHT_FIXTURES",
    "build_catalog",
    "build_categorical_projection",
    "build_detail",
    "build_infrastructure",
    "build_input_role",
    "build_input_workspace",
    "build_matrix_projection",
    "build_parameter_schema",
    "build_preflight",
    "build_result_manifest",
    "build_runner_summary",
    "build_submit",
    "build_table_page",
    "view_entry",
    "build_task_status",
    "build_task_summary",
    "catalog_access_payload",
    "openapi_spec",
    "preflight_fixture",
    "runner_access_payload",
    "validate_payload",
]
