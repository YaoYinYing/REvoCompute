# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Immutable state records for the frontend fixture harness.

Every field here describes something the server owns on the wire: catalog
entries, Runner access policy state, Runner input roles, parameter declarations,
workflow stages, readiness, preflight outcomes, lifecycle transitions, and
result artifacts. The vocabulary is the canonical one — ``openapi.json`` and the
owning ``task.yaml`` files — so a fixture cannot silently invent a status,
capability, or view plugin that the frontend would reject.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


# Fixed identities. Browser fixtures are deterministic: every scenario derives
# its task id, timestamps, and preview size from these constants rather than
# from the clock.
DEFAULT_ORIGIN = "https://revocompute.example"
DEFAULT_TASK_ID = "0123456789abcdef0123456789abcdef"
DEFAULT_SUBMITTED_AT = "2026-09-29T00:00:00Z"
DEFAULT_FINISHED_AT = "2026-09-29T00:00:03Z"
DEFAULT_CREATED_AT = "2026-09-29T00:00:03Z"
DEFAULT_SHA256 = "a" * 64
DEFAULT_PREVIEW_BYTES = 24


@dataclass(frozen=True, slots=True)
class InputRole:
    """One named Task input role as the owning ``task.yaml`` declares it."""

    id: str
    title: str
    logical_type: str
    formats: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    description: str = ""
    minimum: int = 1
    maximum: int = 1


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """One declared Task parameter, projected into the parameter JSON Schema."""

    name: str
    type: str = "string"
    title: str | None = None
    default: object = None
    has_default: bool = False
    description: str = ""
    help: str = ""
    unit: str = ""
    choices: tuple[object, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    multiple_of: float | None = None
    advanced: bool = False
    required: bool = False

    @classmethod
    def integer(cls, name: str, **kwargs: object) -> ParameterSpec:
        return cls(name=name, type="integer", **kwargs)  # type: ignore[arg-type]

    @classmethod
    def number(cls, name: str, **kwargs: object) -> ParameterSpec:
        return cls(name=name, type="number", **kwargs)  # type: ignore[arg-type]

    @classmethod
    def boolean(cls, name: str, **kwargs: object) -> ParameterSpec:
        return cls(name=name, type="boolean", **kwargs)  # type: ignore[arg-type]

    @classmethod
    def enumeration(cls, name: str, choices: tuple[object, ...], **kwargs: object) -> ParameterSpec:
        return cls(name=name, type="string", choices=choices, **kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class Citation:
    num: int
    doi: str
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class WorkflowStage:
    name: str
    display_name: str
    requires_gpu: bool = False
    requires_network: bool = False
    stage_markers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceCapability:
    plugin: str
    id: str
    title: str
    description: str = ""
    options: tuple[tuple[str, object], ...] = ()

    def option_map(self) -> dict[str, object]:
        return dict(self.options)


@dataclass(frozen=True, slots=True)
class WorkspaceStep:
    id: str
    title: str
    description: str = ""
    capabilities: tuple[WorkspaceCapability, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspacePluginAsset:
    """A Runner-owned workspace plugin whose module the browser must load.

    The router serves the real descriptor and asset endpoints for these, so a
    plugin fixture passes the frontend's same-origin asset check instead of
    bypassing it.
    """

    plugin_id: str
    owner: str
    module_body: str
    stylesheet_body: str = ""


@dataclass(frozen=True, slots=True)
class AccessState:
    """Runner access as the server projects it, not as the frontend wishes it were."""

    restricted: bool = False
    granted: bool = True
    requestable: bool = False
    request_status: str | None = None
    policy_id: str = "academic-only"
    label: str = "Academic models"
    description: str = "Academic eligibility is required."
    notice_title: str = "Academic use only"
    notice_summary: str = "The upstream licence requires verified academic eligibility."
    license_name: str = "Upstream terms"
    license_url: str = "https://example.org/terms"

    @classmethod
    def open(cls) -> AccessState:
        return cls()

    @classmethod
    def requestable_policy(cls, **overrides: object) -> AccessState:
        return cls(restricted=True, granted=False, requestable=True, **overrides)  # type: ignore[arg-type]

    @classmethod
    def pending_policy(cls, **overrides: object) -> AccessState:
        return cls(  # type: ignore[arg-type]
            restricted=True, granted=False, requestable=True, request_status="pending", **overrides
        )

    @classmethod
    def granted_policy(cls, **overrides: object) -> AccessState:
        return cls(restricted=True, granted=True, requestable=False, **overrides)  # type: ignore[arg-type]

    @classmethod
    def denied_policy(cls, **overrides: object) -> AccessState:
        return cls(  # type: ignore[arg-type]
            restricted=True, granted=False, requestable=False, request_status="rejected", **overrides
        )


@dataclass(frozen=True, slots=True)
class RunnerDefinition:
    """One Runner as the frontend sees it in the catalog and on its detail page."""

    name: str
    display_name: str
    category: str
    category_label: str
    summary: str
    use_when: str = ""
    input_summary: str = ""
    output_summary: str = ""
    considerations: tuple[str, ...] = ()
    runtime_family: str = "example"
    gpus: bool = False
    requires_network: bool = False
    inputs: tuple[InputRole, ...] = ()
    parameters: tuple[ParameterSpec, ...] = ()
    workspace_steps: tuple[WorkspaceStep, ...] = ()
    workspace_plugins: tuple[WorkspacePluginAsset, ...] = ()
    workflow: tuple[WorkflowStage, ...] = ()
    citations: tuple[Citation, ...] = ()
    access: AccessState = field(default_factory=AccessState.open)
    max_request_bytes: int = 1_048_576

    def with_access(self, access: AccessState) -> RunnerDefinition:
        return replace(self, access=access)


@dataclass(frozen=True, slots=True)
class ReadinessState:
    """Process-wide infrastructure readiness plus per-resource capacity.

    ``status`` is one of the three values the aggregate projection supports;
    capacity is reported separately because a READY deployment can still have a
    busy scheduler or an empty GPU inventory.
    """

    status: str = "READY"
    stale: bool = False
    scheduler_capacity: str = "AVAILABLE"
    gpu_capacity: str = "AVAILABLE"
    worker_status: str = "READY"
    include_components: bool = False

    def with_status(self, status: str, **overrides: object) -> ReadinessState:
        return replace(self, status=status, **overrides)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PreflightSpec:
    """One canonical preflight outcome for a scenario's Runner.

    ``kind`` names the fixture the builder expands; ``errors`` and ``warnings``
    extend or replace its findings, and ``http_status`` is the response code the
    server uses for that outcome (400 for a rejection, 200 for a completed
    validation).
    """

    kind: str = "valid"
    errors: tuple[tuple[str, str], ...] = ()
    warnings: tuple[tuple[str, str], ...] = ()
    http_status: int | None = None
    admission: PreflightAdmission | None = None
    normalized_params: tuple[tuple[str, object], ...] = ()
    inputs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PreflightAdmission:
    allowed: bool = True
    runner_ready: bool = True
    infrastructure_ready: bool = True
    infrastructure_status: str = "READY"
    scheduler_capacity: str = "AVAILABLE"
    gpu_capacity: str = "AVAILABLE"


@dataclass(frozen=True, slots=True)
class LifecycleSpec:
    """The deterministic task lifecycle a scenario advances by request count.

    ``statuses`` is consumed one entry per status poll, in order; polling keeps
    returning the last entry once it is reached. Status is derived from
    ``TaskDatabase.STOP_POLLING_STATUSES`` rather than a private list, so a
    fixture cannot disagree with the server about which states are terminal.
    """

    statuses: tuple[str, ...] = ("finished",)
    poll_ms: int = 15_000

    @property
    def initial(self) -> str:
        return self.statuses[0]

    def at(self, poll_index: int) -> str:
        index = min(max(poll_index, 0), len(self.statuses) - 1)
        return self.statuses[index]

    @staticmethod
    def is_terminal(status: str) -> bool:
        from revocompute.db import TaskDatabase

        return status in TaskDatabase.STOP_POLLING_STATUSES


@dataclass(frozen=True, slots=True)
class ArchiveSpec:
    """Result archive state: not built yet, or already available for download."""

    requested: bool = False


@dataclass(frozen=True, slots=True)
class OutputCheckSpec:
    """The manifest's own output-integrity projection."""

    state: str = "not_configured"
    checks: tuple[tuple[tuple[str, object], ...], ...] = ()
    problems: tuple[str, ...] = ()

    def check_maps(self) -> list[dict[str, object]]:
        return [dict(check) for check in self.checks]


@dataclass(frozen=True, slots=True)
class StoryboardSpec:
    identifier: str
    entrypoint: str
    requires: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    module_body: str = ""


@dataclass(frozen=True, slots=True)
class ResultArtifactSpec:
    """One manifest artifact, described by capability rather than by runner."""

    path: str
    role: str = "artifact"
    capability: str = "text"
    size: int = DEFAULT_PREVIEW_BYTES
    media_type: str | None = None
    preview: str | None = None
    confidence_encoding: str | None = None
    body: str | None = None
    columns: tuple[str, ...] = ()
    table: tuple[tuple[object, ...], ...] = ()
    projection: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkerView:
    """One item of a runner's per-item work manifest."""

    id: str
    status: str
    attempts: int = 1
    output_path: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResultFixture:
    """A complete canonical ResultManifest fixture for one rendering class.

    ``logical_files`` declares the Expected File Tree identities the manifest
    publishes; each id maps an artifact path (or several, for a ``many``
    cardinality) into the ``result.files`` projection a storyboard reads.
    """

    name: str
    artifacts: tuple[ResultArtifactSpec, ...] = ()
    logical_files: tuple[tuple[str, tuple[str, ...]], ...] = ()
    views: tuple[tuple[tuple[str, object], ...], ...] = ()
    status: str = "finished"
    outcome: str | None = "SUCCESS"
    error: str | None = None
    output_check: OutputCheckSpec = field(default_factory=OutputCheckSpec)
    limitations: tuple[str, ...] = ()
    storyboard: StoryboardSpec | None = None
    archive: ArchiveSpec | None = None
    created_at: str = DEFAULT_CREATED_AT
    run_inputs: tuple[tuple[str, str, str], ...] = ()
    run_parameters: tuple[tuple[str, str, object, str], ...] = ()
    work_items: tuple[WorkerView, ...] = ()
    task_type: str = "example"

    def view_maps(self) -> list[dict[str, object]]:
        return [dict(view) for view in self.views]

    def logical_file_paths(self) -> dict[str, tuple[str, ...]]:
        return dict(self.logical_files)


