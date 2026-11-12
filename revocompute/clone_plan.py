# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Read-only Clone & Reuse planning and its short-lived plan references.

A clone plan describes how one authorized, existing Task can seed a new draft.
It never mutates the source, derives a Task ID, reserves resources, or reads file
bytes: the plan carries the source's *recorded* parameter values and the digest
metadata of its immutable input snapshot, and every value is checked against the
Task's *current* schema. Incompatible values are reported, never coerced.

The plan reference is an opaque primary key into a short-lived, owner-scoped
store. The dashboard and result page only ever put that opaque reference in a
URL; the plan itself is re-resolved from the current registry when the draft
opens, so a schema change between the click and the fetch is observed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: How long a clone-plan reference stays resolvable. A draft is opened
#: immediately after the button click; the window only needs to cover that hop.
DEFAULT_TTL_SECONDS = 900

_PLAN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_TASK_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_ENTITY_JSON_TYPES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}


def plan_id_is_valid(value: str) -> bool:
    return bool(_PLAN_ID_PATTERN.fullmatch(value))


def task_id_is_valid(value: str) -> bool:
    return bool(_TASK_ID_PATTERN.fullmatch(value))


def schema_revision(schema: dict[str, Any]) -> str:
    """Canonical digest of one Task's parameter schema.

    The revision names the schema a draft is being filled against, so a client
    can distinguish two forms it otherwise renders identically. It is a digest,
    never a semantic version invented outside the owning ``task.yaml``.
    """
    encoded = json.dumps(schema, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ClonePlanReference:
    plan_id: str
    source_task_id: str
    user_id: int
    created_at: float
    expires_at: float


class ClonePlanStore:
    """Owner-scoped, expiring references to clone sources.

    Only the source Task ID is stored. The typed plan is rebuilt on every read,
    so this store cannot become a second, stale copy of the Task schema.
    """

    def __init__(self, path: str, *, default_ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.path = os.path.abspath(path)
        self.default_ttl_seconds = default_ttl_seconds
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS clone_plan_references ("
                "plan_id TEXT PRIMARY KEY, "
                "source_task_id TEXT NOT NULL, "
                "user_id INTEGER NOT NULL, "
                "created_at REAL NOT NULL, "
                "expires_at REAL NOT NULL)"
            )

    @contextmanager
    def _connection(self):
        # One short-lived connection per operation: the web process is threaded,
        # and a reference store this small gains nothing from a pooled handle.
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(
        self, *, source_task_id: str, user_id: int, ttl_seconds: int | None = None
    ) -> ClonePlanReference:
        now = time.time()
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        reference = ClonePlanReference(
            plan_id=secrets.token_urlsafe(24),
            source_task_id=source_task_id,
            user_id=int(user_id),
            created_at=now,
            expires_at=now + ttl,
        )
        with self._connection() as connection:
            connection.execute("DELETE FROM clone_plan_references WHERE expires_at <= ?", (now,))
            connection.execute(
                "INSERT INTO clone_plan_references "
                "(plan_id, source_task_id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (
                    reference.plan_id,
                    reference.source_task_id,
                    reference.user_id,
                    reference.created_at,
                    reference.expires_at,
                ),
            )
        return reference

    def get(self, plan_id: str, *, user_id: int, now: float | None = None) -> ClonePlanReference | None:
        if not plan_id_is_valid(plan_id):
            return None
        moment = time.time() if now is None else now
        with self._connection() as connection:
            row = connection.execute(
                "SELECT plan_id, source_task_id, user_id, created_at, expires_at "
                "FROM clone_plan_references WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                return None
            reference = ClonePlanReference(*row)
            if reference.expires_at <= moment:
                connection.execute("DELETE FROM clone_plan_references WHERE plan_id = ?", (plan_id,))
                return None
            # A reference is an entitlement, not a shareable link: another
            # signed-in caller learns nothing from a guessed or pasted ID.
            if reference.user_id != int(user_id):
                return None
            return reference


def _load_input_form(task: dict[str, Any]) -> dict[str, Any] | None:
    raw = task.get("input_form")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        form = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return form if isinstance(form, dict) else None


def _control_value(value: Any) -> str:
    """The string an owning parameter control holds for a recorded value.

    ``0`` and ``False`` are values, not absence: neither may collapse into an
    empty field just because it is falsy.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


def _property_types(property_schema: dict[str, Any]) -> set[str]:
    declared = property_schema.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return {item for item in declared if isinstance(item, str)}
    return set()


def _value_matches_type(value: Any, declared: set[str]) -> bool:
    if not declared:
        # A property that names no type is permissive in JSON Schema; the current
        # form still renders it, so the recorded value is carried and the
        # reconciliation panel states that its type could not be checked.
        return True
    if isinstance(value, bool):
        return "boolean" in declared
    if isinstance(value, int):
        return bool(declared & {"integer", "number"})
    if isinstance(value, float):
        return "number" in declared
    if isinstance(value, str):
        return "string" in declared
    if value is None:
        return "null" in declared
    return False


def _blocked(field: str, code: str, message: str, recorded_value: Any = None) -> dict[str, Any]:
    finding: dict[str, Any] = {"field": field, "code": code, "message": message}
    if recorded_value is not None:
        finding["recorded_value"] = recorded_value
    return finding


def _compatible_parameter(
    name: str,
    value: Any,
    property_schema: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Check one recorded value against the current property contract.

    Returns ``(parameter, None)`` when the value may be prefilled, or
    ``(None, blocked_field)`` when it may not. No branch coerces the value into a
    different type or substitutes another scientific choice.
    """
    declared = _property_types(property_schema)
    entity_type = property_schema.get("__recorded_type__")
    if entity_type is not None:
        historical = _ENTITY_JSON_TYPES.get(str(entity_type))
        if historical is None:
            return None, _blocked(name, "parameter_type_unknown", "The recorded parameter type is not understood.")
        if declared and historical not in declared:
            # ``integer`` is a valid ``number``: that is a widening, not a change
            # of scientific meaning. Everything else is a type change.
            if not (historical == "integer" and "number" in declared):
                return None, _blocked(
                    name,
                    "parameter_type_changed",
                    "The recorded value's type no longer matches the parameter's current type.",
                    _control_value(value),
                )
    if not _value_matches_type(value, declared):
        return None, _blocked(
            name,
            "parameter_type_changed",
            "The recorded value's type no longer matches the parameter's current type.",
            _control_value(value),
        )
    choices = property_schema.get("enum")
    if isinstance(choices, list) and not any(_json_equal(value, choice) for choice in choices):
        return None, _blocked(
            name,
            "parameter_choice_unavailable",
            "The recorded choice is not offered by the current parameter contract.",
            _control_value(value),
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(property_schema.get("minimum"), (int, float)) and value < property_schema["minimum"]:
            return None, _blocked(
                name,
                "parameter_range_invalid",
                "The recorded value is below the current minimum.",
                _control_value(value),
            )
        if isinstance(property_schema.get("maximum"), (int, float)) and value > property_schema["maximum"]:
            return None, _blocked(
                name,
                "parameter_range_invalid",
                "The recorded value is above the current maximum.",
                _control_value(value),
            )
        exclusive_minimum = property_schema.get("exclusiveMinimum")
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            return None, _blocked(
                name,
                "parameter_range_invalid",
                "The recorded value is not above the current exclusive minimum.",
                _control_value(value),
            )
        exclusive_maximum = property_schema.get("exclusiveMaximum")
        if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
            return None, _blocked(
                name,
                "parameter_range_invalid",
                "The recorded value is not below the current exclusive maximum.",
                _control_value(value),
            )
    if (
        property_schema.get("format") == "date"
        and isinstance(value, str)
        and value
        and not _ISO_DATE_PATTERN.fullmatch(value)
    ):
        return None, _blocked(
            name, "parameter_format_invalid", "The recorded value is not a calendar date.", value
        )
    return {"name": name, "value": _control_value(value), "source": "recorded"}, None


def _parameters(
    form: dict[str, Any] | None,
    current_schema: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve recorded parameter values and current defaults against the schema."""
    properties: dict[str, Any] = {}
    required: set[str] = set()
    if isinstance(current_schema, dict):
        raw_properties = current_schema.get("properties")
        if isinstance(raw_properties, dict):
            properties = {str(name): value for name, value in raw_properties.items() if isinstance(value, dict)}
        raw_required = current_schema.get("required")
        if isinstance(raw_required, list):
            required = {str(name) for name in raw_required}

    recorded: dict[str, dict[str, Any]] = {}
    for entity in (form or {}).get("entities", []) if isinstance(form, dict) else []:
        if not isinstance(entity, dict) or entity.get("type") == "file":
            continue
        name = entity.get("name")
        if not isinstance(name, str) or not name:
            continue
        recorded[name] = entity

    compatible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for name, entity in recorded.items():
        if name not in properties:
            blocked.append(
                _blocked(
                    name,
                    "parameter_removed",
                    "This parameter is no longer declared by the Task.",
                    _control_value(entity.get("verified_value", entity.get("value"))),
                )
            )
            continue
        value = entity.get("verified_value", entity.get("value"))
        if value is None:
            # A missing record is not a recorded value; it resolves below through
            # the current default like any other absent parameter.
            continue
        property_schema = dict(properties[name])
        property_schema["__recorded_type__"] = entity.get("type")
        parameter, finding = _compatible_parameter(name, value, property_schema)
        if parameter is not None:
            compatible.append(parameter)
        elif finding is not None:
            blocked.append(finding)

    blocked_names = {item["field"] for item in blocked}
    recorded_names = set(recorded)
    for name, property_schema in properties.items():
        if name in recorded_names or name in blocked_names:
            continue
        default = property_schema.get("default")
        if default is not None:
            compatible.append({"name": name, "value": _control_value(default), "source": "current_default"})
        elif name in required:
            warnings.append(
                {
                    "code": "required_parameter_unset",
                    "message": (
                        "This required parameter has no recorded value and no current default; "
                        "enter it explicitly."
                    ),
                    "field": name,
                }
            )
    return compatible, blocked, warnings


def _effective_cardinality(role: dict[str, Any], parameters: dict[str, str]) -> tuple[int, int]:
    """A role's min/max under the draft's current parameter values.

    A Task may declare a parameter-conditioned presence rule; the same rule is
    applied here so a required or forbidden role is described honestly before
    the reader uploads anything.
    """
    cardinality = role.get("cardinality") or {}
    minimum = int(cardinality.get("min", 0) or 0)
    maximum = int(cardinality.get("max", 0) or 0)
    presence = role.get("presence")
    if isinstance(presence, dict):
        selected = parameters.get(str(presence.get("parameter") or ""))
        if selected is not None:
            if selected in presence.get("required_when", []):
                minimum = max(minimum, 1)
            elif selected in presence.get("forbidden_when", []):
                maximum = 0
    return minimum, maximum


def _files(
    form: dict[str, Any] | None,
    current_roles: list[dict[str, Any]] | None,
    *,
    files_owned: bool,
    snapshot_root: str | None,
    parameters: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Describe each current role's source files without exposing any path."""
    warnings: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    for entity in (form or {}).get("entities", []) if isinstance(form, dict) else []:
        if not isinstance(entity, dict) or entity.get("type") != "file":
            continue
        entities.append(entity)

    current_ids = {str(role["id"]) for role in current_roles or []}
    source_roles = {str(entity.get("role")) for entity in entities if isinstance(entity.get("role"), str)}
    for role in sorted(source_roles - current_ids):
        warnings.append(
            {
                "code": "input_role_removed",
                "message": "This input role is no longer declared by the Task; its files were not carried over.",
                "field": role,
            }
        )

    reusable: list[dict[str, Any]] = []
    for role in current_roles or []:
        role_id = str(role["id"])
        minimum, maximum = _effective_cardinality(role, parameters)
        role_entities = [entity for entity in entities if str(entity.get("role") or "") == role_id]
        if maximum == 0:
            if role_entities:
                warnings.append(
                    {
                        "code": "input_role_not_applicable",
                        "message": (
                            "These inputs are not submitted under the draft's current settings; "
                            "the parameter selection forbids this role."
                        ),
                        "field": role_id,
                    }
                )
            role_entities = []
        files: list[dict[str, Any]] = []
        for entity in role_entities:
            sha256 = str(entity.get("hash") or "").strip().lower()
            size = entity.get("size")
            original_name = entity.get("value")
            item: dict[str, Any] = {
                "original_name": str(original_name) if isinstance(original_name, str) else "",
                "sha256": sha256 if _SHA256_PATTERN.fullmatch(sha256) else None,
                "size": int(size) if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None,
                "format": str(entity.get("format") or ""),
                # Core has no submission-time reference for a Task's input files,
                # so the browser re-uploads them and normal validation hashes the
                # bytes it receives. The plan only states whether the source
                # snapshot is still verifiable.
                "reuse": "reupload_required",
                "available": False,
                "reason": None,
            }
            digest_ok = item["sha256"] is not None and item["size"] is not None
            if not files_owned:
                item["reason"] = "not_owner"
            elif not digest_ok:
                # An incomplete recorded reference cannot be verified, so it is
                # never presented as available.
                item["reason"] = "record_invalid"
            else:
                path = entity.get("snapshot_path")
                available = False
                if isinstance(path, str) and path and snapshot_root and _within(path, snapshot_root):
                    available = os.path.isfile(path)
                item["available"] = available
                if not available:
                    item["reason"] = "snapshot_unavailable"
            if item["reason"] in {"snapshot_unavailable", "record_invalid"}:
                warnings.append(
                    {
                        "code": "input_snapshot_unavailable",
                        "message": (
                            "This input's immutable source snapshot cannot be verified; "
                            "re-upload the original file."
                        ),
                        "field": role_id,
                    }
                )
            files.append(item)
        if not files and minimum > 0:
            warnings.append(
                {
                    "code": "required_input_role_unset",
                    "message": "This required input role has no recorded source file; provide it before submitting.",
                    "field": role_id,
                }
            )
        reusable.append(
            {
                "role": role_id,
                "title": str(role.get("title") or role_id),
                "formats": [str(value) for value in role.get("formats", [])],
                "required": minimum > 0,
                "reuse": "reupload_required",
                "files": files,
            }
        )
    return reusable, warnings


def _within(path: str, root: str) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def _source_execution_mode(form: dict[str, Any] | None) -> str | None:
    graph = (form or {}).get("execution_graph") if isinstance(form, dict) else None
    if not isinstance(graph, dict):
        return None
    document = graph.get("document")
    if not isinstance(document, dict):
        return None
    mode = document.get("mode")
    return mode if isinstance(mode, str) and mode else None


def build_plan(
    source: dict[str, Any],
    *,
    current_type: Any | None,
    target_enabled: bool | None,
    files_owned: bool,
    snapshot_root: str | None,
    access_granted: bool | None = None,
    submission_available: bool | None = None,
) -> dict[str, Any]:
    """Build the bounded, typed clone plan for one authorized source Task."""
    task_id = str(source.get("md5sum") or "")
    source_type = str(source.get("task_type") or "")
    form = _load_input_form(source)

    current_schema = current_type.schema if current_type is not None else None
    revision = schema_revision(current_schema) if isinstance(current_schema, dict) else None
    roles = (
        [
            {
                "id": role.name,
                "title": role.title,
                "formats": list(role.formats),
                "cardinality": {"min": role.minimum, "max": role.maximum},
                **(
                    {"presence": role.presence.to_dict()}
                    if getattr(role, "presence", None) is not None
                    else {}
                ),
            }
            for role in current_type.inputs
        ]
        if current_type is not None
        else None
    )

    warnings: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    compatible: list[dict[str, Any]] = []
    reusable: list[dict[str, Any]] = []

    if form is None:
        warnings.append(
            {
                "code": "source_record_unreadable",
                "message": "The source Task's recorded inputs are unreadable; start from the current defaults.",
            }
        )
    else:
        compatible, blocked, parameter_warnings = _parameters(form, current_schema)
        warnings.extend(parameter_warnings)
        parameter_values = {item["name"]: item["value"] for item in compatible}
        reusable, input_warnings = _files(
            form,
            roles,
            files_owned=files_owned,
            snapshot_root=snapshot_root,
            parameters=parameter_values,
        )
        warnings.extend(input_warnings)
        # ``_files`` returns role-level warnings only; blocked fields stay in the
        # plan's parameter section so a client has one list to render.
        workspace = form.get("workspace")
        capabilities = workspace.get("capabilities") if isinstance(workspace, dict) else None
        if isinstance(capabilities, dict) and capabilities:
            warnings.append(
                {
                    "code": "workspace_state_not_reapplied",
                    "message": "Runner-owned workspace selections are not carried over; re-select them in the draft.",
                }
            )
        source_mode = _source_execution_mode(form)
        if source_mode is not None:
            allowed_modes = {mode.id for mode in current_type.execution_modes} if current_type is not None else set()
            if allowed_modes or source_mode != "full":
                if source_mode not in allowed_modes:
                    blocked.append(
                        _blocked(
                            "execution_mode",
                            "execution_mode_unavailable",
                            "The source Task's execution mode is no longer declared; choose an available mode.",
                            source_mode,
                        )
                    )

    # The source never recorded which schema revision produced its values, so
    # the plan says so instead of pretending the current schema is the old one.
    warnings.append(
        {
            "code": "source_schema_not_recorded",
            "message": (
                "The source Task does not record its schema revision; "
                "recorded values were checked against the current schema."
            ),
        }
    )
    warnings.append(
        {
            "code": "resources_rechecked",
            "message": (
                "Resource policy, entitlement, and Runner admission are re-evaluated "
                "when this draft is submitted."
            ),
        }
    )
    if current_type is None:
        blocked.append(
            _blocked(
                "task_type",
                "task_type_removed",
                "This Task type is no longer registered; the draft cannot be submitted.",
                source_type,
            )
        )
    elif target_enabled is False:
        blocked.append(
            _blocked(
                "task_type",
                "task_type_disabled",
                "This Task type is disabled for new submissions.",
                source_type,
            )
        )
    if access_granted is False:
        warnings.append(
            {
                "code": "runner_access_required",
                "message": "Runner access for this Task type is required before the draft can be submitted.",
            }
        )
    if submission_available is False:
        warnings.append(
            {
                "code": "target_submission_unavailable",
                "message": "This deployment currently cannot accept submissions for this Task type.",
            }
        )
    if current_type is not None and current_type.execution_modes:
        warnings.append(
            {
                "code": "execution_mode_not_preapplied",
                "message": (
                    "The source execution mode is reported but not selected; "
                    "choose the draft's execution mode explicitly."
                ),
            }
        )

    return {
        "source_task_id": task_id,
        "source_task_type": source_type,
        "source_submitted_at": iso_timestamp(source.get("uploaded_at")),
        "target_task_type": source_type,
        "target_display_name": str(current_type.display_name) if current_type is not None else source_type,
        "target_schema_revision": revision,
        "compatible_parameters": compatible,
        "reusable_inputs": reusable,
        "warnings": warnings,
        "blocked_fields": blocked,
        "can_submit": False,
    }


def iso_timestamp(value: Any) -> str | None:
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return None
