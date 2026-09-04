# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Task and runtime-family registry.

Server code never needs to know about individual task types — a new task
type selects a shared runtime family, while the family owns the image,
entrypoint, Dockerfile, Apptainer definition, and machine-specific runner
configuration.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from revocompute.access_control import AccessPolicy, get_policy, load_policies, load_policy_documents, register_policies

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskParam:
    """A parameter the user can set when submitting a job."""

    name: str
    type: str = "str"  # "str" | "int" | "float" | "bool"
    default: Any = None
    required: bool = False
    description: str = ""
    label: str = ""
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""
    help: str = ""
    advanced: bool = False


@dataclass(frozen=True)
class InputCapability:
    """A safe, declarative input-workspace component.

    Capabilities select browser code that is already shipped with the server;
    registry YAML cannot supply executable code or remote plugin locations.
    """

    plugin: str
    id: str
    title: str = ""
    description: str = ""
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InputStep:
    """One meaningful, ordered step in the user-facing experiment protocol."""

    id: str
    title: str
    description: str
    capabilities: tuple[InputCapability, ...]


@dataclass(frozen=True)
class Category:
    """Server-owned presentation metadata for a scientific method group."""

    name: str
    label: str
    description: str
    order: int


@dataclass(frozen=True)
class ArtifactSelector:
    """A bounded server-side selector for manifest-approved result artifacts."""

    value: str
    is_glob: bool
    required: bool


@dataclass(frozen=True)
class ResultView:
    """A safe task-owned composition of local result-view plugins."""

    plugin: str
    id: str
    role: str
    title: str
    description: str
    sources: dict[str, tuple[ArtifactSelector, ...]]
    mapping: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeFamily:
    """Portable execution environment shared by one or more task types."""

    name: str
    docker_image: str
    entrypoint: tuple[str, ...]
    dockerfile: str
    definition: str
    slurm_image: str = ""
    access_policy: AccessPolicy | None = None
    root: str = ""


@dataclass(frozen=True)
class WorkflowStage:
    """One scheduler allocation in an ordered task workflow."""

    name: str
    display_name: str
    requires_gpu: bool
    runner_args: tuple[str, ...] = ()
    stage_markers: tuple[str, ...] = ()
    requires_network: bool = False


@dataclass(frozen=True)
class TaskType:
    """Portable user-facing task definition.

    Runtime implementation details live in RuntimeFamily. Machine-specific
    paths and resource limits live in RunnerConfig.
    """

    name: str
    display_name: str  # "PSSM-GREMLIN", "AlphaFold2"

    runtime: RuntimeFamily

    input_extension: str  # ".fasta", ".pdb"
    input_label: str  # "FASTA file", "PDB file"

    # Optional fields with defaults
    input_extensions: tuple[str, ...] = ()
    primary_input_extensions: tuple[str, ...] = ()
    allow_multiple_inputs: bool = False
    max_input_files: int = 1
    min_input_files: int = 1
    runner_args: tuple[str, ...] = ()
    gpus: bool = False
    requires_network: bool = False
    stage_markers: dict[str, str] = field(default_factory=dict)
    workflow: tuple[WorkflowStage, ...] = ()
    params: tuple[TaskParam, ...] = ()
    # Canonical JSON Schema for the task's parameter object.  Legacy
    # ``params`` metadata remains available for rendering and is converted to
    # this schema when a definition does not provide one explicitly.
    schema: dict[str, Any] = field(default_factory=dict)
    input_workspace: tuple[InputStep, ...] = ()
    result_workspace: tuple[ResultView, ...] = ()
    # Method citations: citation_dois is an ordered map (position -> DOI) —
    # projects with multiple papers (AF2, ColabFold, ESM) list them all. The
    # BibTeX is resolved from the DOIs by tools/resolve_citations.py (never
    # hand-guessed) and checked in as citation_bibtex. The server writes it
    # into every result dir as citations.bib at finalize.
    citation_dois: tuple[tuple[int, str, str], ...] = ()
    citation_bibtex: str = ""
    category: str = "other"
    summary: str = ""
    use_when: str = ""
    input_summary: str = ""
    output_summary: str = ""
    considerations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema:
            return
        properties: dict[str, Any] = {}
        required: list[str] = []
        type_map = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}
        for param in self.params:
            prop: dict[str, Any] = {"type": type_map[param.type]}
            if param.default is not None:
                prop["default"] = param.default
            if param.choices:
                prop["enum"] = list(param.choices)
            if param.minimum is not None:
                prop["minimum"] = param.minimum
            if param.maximum is not None:
                prop["maximum"] = param.maximum
            properties[param.name] = prop
            if param.required and param.default is None:
                required.append(param.name)
        schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            schema["required"] = required
        object.__setattr__(self, "schema", schema)


@dataclass(frozen=True)
class RunnerMount:
    """A bind mount from host into the runner container."""

    host_path: str  # "/srv/revodesign/databases/uniref30"
    container_path: str  # "/opt/db/uniref30"
    mode: str = "ro"  # "ro" | "rw"


@dataclass(frozen=True)
class RunnerConfig:
    """Deployment-specific settings for a task type.

    Loaded from each deployed runner family's ``runner.yaml`` at startup. Host paths are
    machine-specific — edit the YAML when deploying to a new node, never
    the global ``.env``.
    """

    mounts: tuple[RunnerMount, ...] = ()
    env: dict[str, str] = field(default_factory=dict)  # extra env vars → container
    max_runtime_seconds: int | None = None  # override task_type default if set
    defaults: dict[str, Any] = field(default_factory=dict)  # default param values


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: dict[str, tuple[TaskType, RunnerConfig]] = {}
_runtime_registry: dict[str, RuntimeFamily] = {}
_category_registry: dict[str, Category] = {}
_job_executor = "docker"
_container_runtime = "docker"
_plugin_manager = None


def _load_extensions(raw: Any, input_extension: str, task_id: str) -> tuple[str, ...]:
    """Normalize and validate accepted input extensions from a task manifest."""
    values = [input_extension] if raw is None else raw
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value.startswith(".") and len(value) > 1 for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"Task type {task_id!r} input extensions must be a non-empty list of unique dotted strings")
    return tuple(values)


def _load_task_params(raw: Any, schema: dict[str, Any], task_id: str) -> tuple[TaskParam, ...]:
    """Load UI parameter metadata, deriving a minimal form from JSON Schema when needed."""
    if raw is not None:
        if not isinstance(raw, list):
            raise ValueError(f"Task type {task_id!r} params must be a list")
        allowed = set(TaskParam.__dataclass_fields__)
        params: list[TaskParam] = []
        for item in raw:
            if not isinstance(item, dict) or set(item) - allowed:
                raise ValueError(f"Task type {task_id!r} contains invalid parameter metadata")
            data = dict(item)
            data["choices"] = tuple(data.get("choices", ()))
            params.append(TaskParam(**data))
        return tuple(params)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if not isinstance(properties, dict):
        raise ValueError(f"Task type {task_id!r} schema properties must be a mapping")
    required = set(schema.get("required", ())) if isinstance(schema, dict) else set()
    type_map = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}
    params = []
    for name, prop in properties.items():
        if not isinstance(name, str) or not isinstance(prop, dict):
            raise ValueError(f"Task type {task_id!r} schema properties must be named mappings")
        param_type = type_map.get(prop.get("type"), "str")
        params.append(
            TaskParam(
                name=name,
                type=param_type,
                default=prop.get("default"),
                required=name in required,
                description=str(prop.get("description") or ""),
                label=str(prop.get("title") or ""),
                choices=tuple(prop.get("enum", ())),
                minimum=prop.get("minimum"),
                maximum=prop.get("maximum"),
                step=prop.get("multipleOf"),
                unit=str(prop.get("x-unit") or ""),
                help=str(prop.get("x-help") or ""),
                advanced=bool(prop.get("x-advanced", False)),
            )
        )
    return tuple(params)


def discover_plugins(runners_dir: str, enabled: set[str] | None = None) -> None:
    """Load runner families and task contributions from deployed manifests.

    This is the sole production discovery path.  Manifests are intentionally
    small and declarative; task-specific schemas remain in each task directory.
    """
    global _job_executor, _container_runtime, _plugin_manager
    _registry.clear(); _runtime_registry.clear(); _category_registry.clear()
    _job_executor, _container_runtime = "slurm", "apptainer"
    root = os.path.abspath(runners_dir)
    load_policies(os.path.join(root, "__no_global_policies__"))
    from revocompute.plugins import PluginManager
    manager = PluginManager()
    manifests = manager.discover(root, enabled=enabled)
    _plugin_manager = manager
    capability_schemas: dict[str, dict[str, Any]] = {}
    workspace_schemas_by_owner: dict[str, dict[str, dict[str, Any]]] = {}
    for discovered in manifests:
        for descriptor in discovered.workspace_plugins.values():
            module_path = descriptor.asset_path(descriptor.module)
            if not module_path.is_file():
                raise ValueError(f"Workspace plugin module is missing: {descriptor.global_id}")
            for style in descriptor.styles:
                if not descriptor.asset_path(style).is_file():
                    raise ValueError(f"Workspace plugin stylesheet is missing: {descriptor.global_id}")
            if descriptor.configuration_schema:
                schema_path = descriptor.asset_path(descriptor.configuration_schema)
                if not schema_path.is_file():
                    raise ValueError(f"Workspace plugin schema is missing: {descriptor.global_id}")
                schema = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
                Draft202012Validator.check_schema(schema)
                workspace_schemas_by_owner.setdefault(discovered.runner_family or discovered.id, {})[descriptor.id] = schema
        raw_schemas = discovered.configuration_schemas
        if not isinstance(raw_schemas, dict):
            raise ValueError(f"Plugin {discovered.id!r} configuration_schemas must be a mapping")
        for kind, declarations in raw_schemas.items():
            if not isinstance(declarations, dict):
                raise ValueError(f"Plugin {discovered.id!r} schema declarations must be mappings")
            for identifier, schema in declarations.items():
                if not isinstance(schema, dict):
                    raise ValueError(f"Configuration schema for {identifier!r} must be a mapping")
                if identifier in capability_schemas:
                    raise ValueError(f"Duplicate configuration schema contribution: {identifier!r}")
                Draft202012Validator.check_schema(schema)
                capability_schemas[str(identifier)] = schema
    # Plugin identity comes from plugin.yaml, never from the storage directory.
    for manifest_obj in manifests:
        family_dir = manifest_obj.path
        family_id = manifest_obj.id
        policy_refs = manifest_obj.access_policies
        for policy_ref in policy_refs:
            policy_path = Path(str(policy_ref))
            if policy_path.is_absolute() or ".." in policy_path.parts:
                raise ValueError(f"Access policy path must be relative to plugin root: {policy_ref}")
            policies = load_policy_documents(family_dir / policy_path)
            for policy_id, policy in policies.items():
                manager.register_contribution(family_id, "access_policies", policy_id, policy)
            register_policies(policies)
        runtime_data = dict(manifest_obj.runtime)
        if not isinstance(runtime_data, dict):
            raise ValueError(f"Plugin runtime must be a mapping: {manifest_path}")
        for field_name in ("definition", "dockerfile"):
            runtime_path = Path(str(runtime_data.get(field_name, "")))
            if runtime_path.is_absolute() or ".." in runtime_path.parts:
                raise ValueError(f"Plugin runtime {field_name} must be relative to plugin root: {runtime_path}")
        runner_yaml = family_dir / "runner.yaml"
        if runner_yaml.is_file():
            with runner_yaml.open(encoding="utf-8") as stream:
                runtime_data = {**(yaml.safe_load(stream) or {}), **runtime_data}
        legacy_image = str(runtime_data.get("image", ""))
        docker_image = str(runtime_data.get("docker_image") or "")
        slurm_image = str(runtime_data.get("slurm_image") or "")
        image_artifact = str(runtime_data.get("image_artifact") or "")
        if not docker_image:
            if legacy_image.startswith("/"):
                raise ValueError(f"Plugin runtime for {family_id!r} must declare docker_image")
            docker_image = legacy_image
        if not slurm_image:
            slurm_image = os.path.join(os.environ.get("REVOCOMPUTE_IMAGE_DIR", "/mnt/data/srv/revodesign/server-slurm/images"), image_artifact) if image_artifact else ""
        runtime = RuntimeFamily(
            name=family_id,
            docker_image=docker_image or family_id,
            entrypoint=tuple(runtime_data.get("entrypoint", ())),
            dockerfile=str(runtime_data.get("dockerfile", "Dockerfile")),
            definition=str(runtime_data.get("definition", f"{family_id}.def")),
            slurm_image=slurm_image or family_id,
            access_policy=get_policy(str(runtime_data["access_policy"])) if runtime_data.get("access_policy") else None,
            root=str(family_dir),
        )
        _runtime_registry[family_id] = runtime
        manager.register_contribution(family_id, "runtime_families", family_id, runtime)
        task_refs = manifest_obj.tasks
        for ref in task_refs:
            ref_path = Path(str(ref))
            if ref_path.is_absolute() or ".." in ref_path.parts:
                raise ValueError(f"Task path must be relative to plugin root: {ref}")
            task_path = family_dir / ref_path
            with task_path.open(encoding="utf-8") as stream:
                raw = yaml.safe_load(stream) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"Task manifest must be a mapping: {task_path}")
            task_id = str(raw.get("id") or raw.get("name") or task_path.parent.name)
            schema = dict(raw.get("schema") or raw.get("parameters") or {})
            params = _load_task_params(raw.get("params"), schema, task_id)
            input_extension = str(raw.get("input_extension", ".json"))
            input_extensions = _load_extensions(raw.get("input_extensions"), input_extension, task_id)
            primary_input_extensions = _load_extensions(
                raw.get("primary_input_extensions"), input_extension, task_id
            )
            if not set(primary_input_extensions).issubset(input_extensions):
                raise ValueError(f"Task type {task_id!r} primary input extensions must be accepted input extensions")
            workspace_owner = manifest_obj.runner_family or family_id
            owner_schemas = {**capability_schemas, **workspace_schemas_by_owner.get(workspace_owner, {})}
            owner_plugin_ids = set(workspace_schemas_by_owner.get(workspace_owner, {}))
            owner_plugin_ids.update(
                descriptor.id for descriptor in manager.workspace_plugins() if descriptor.owner == workspace_owner
            )
            task = TaskType(
                name=task_id,
                display_name=str(raw.get("display_name", task_id)),
                runtime=runtime,
                input_extension=input_extension,
                input_label=str(raw.get("input_label", "Input file")),
                input_extensions=input_extensions,
                primary_input_extensions=primary_input_extensions,
                gpus=bool(raw.get("gpus", False)),
                requires_network=bool(raw.get("requires_network", False)),
                stage_markers=dict(raw.get("stage_markers", {})),
                workflow=_load_workflow(raw.get("workflow"), task_id, dict(raw.get("stage_markers", {}))),
                runner_args=tuple(raw.get("runner_args", ())),
                allow_multiple_inputs=bool(raw.get("allow_multiple_inputs", False)),
                max_input_files=int(raw.get("max_input_files", 1)),
                min_input_files=int(raw.get("min_input_files", 1)),
                params=params,
                schema=schema,
                input_workspace=_load_input_workspace(
                    raw.get("input_workspace"), capability_schemas=owner_schemas,
                    plugin_ids=owner_plugin_ids, workspace_owner=workspace_owner,
                ) if "input_workspace" in raw else (),
                result_workspace=_load_result_workspace(raw.get("result_workspace")) if "result_workspace" in raw else (),
                citation_dois=_load_citation_dois(raw.get("citation_dois"), task_id),
                citation_bibtex=str(raw.get("citation_bibtex", "")),
                category=str(raw.get("category", "other")),
                summary=str(raw.get("summary", "")),
                use_when=str(raw.get("use_when", "")),
                input_summary=str(raw.get("input_summary", "")),
                output_summary=str(raw.get("output_summary", "")),
                considerations=tuple(raw.get("considerations", ())),
            )
            # Categories are part of the task contribution when the central
            # registry is absent.  Preserve a deterministic fallback order so
            # independently materialized plugin trees remain renderable.
            if task.category not in _category_registry:
                _category_registry[task.category] = Category(
                    name=task.category,
                    label=str(raw.get("category_label", task.category.replace("_", " ").title())),
                    description=str(raw.get("category_description", "")),
                    order=len(_category_registry),
                )
            runner_file = family_dir / "runner.yaml"
            runner_cfg = _load_runner_config(str(runner_file)) if runner_file.is_file() else RunnerConfig()
            _registry[task_id] = (task, runner_cfg)
            manager.register_contribution(family_id, "tasks", task_id, task)
            manager.register_contribution(family_id, "runner_configs", task_id, runner_cfg)

_INPUT_CAPABILITY_PLUGINS = {
    "files",
    "sequence",
    "structure",
    "regions",
    "jaag-builder",
    "parameters",
    "review",
}
_INPUT_CAPABILITY_OPTION_KEYS = {
    "files": {"primary_required"},
    "sequence": set(),
    "structure": {"source", "select_chains", "select_residues"},
    "regions": {"source", "fields", "syntax", "modes"},
    "jaag-builder": {"target"},
    "parameters": set(),
    "review": {"show_paths"},
}

_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[^\s]+$")


def _load_citation_dois(raw: Any, name: str) -> tuple[tuple[int, str, str], ...]:
    """Validate the ordered citation_dois list. Each entry is
    {num, doi, title}: the DOI identifies the paper and the declared title
    enables human checks (the resolver verifies it against the fetched
    BibTeX). BibTeX is resolved from the DOIs by
    tools/resolve_citations.py — never hand-guessed."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"Task type {name!r} citation_dois must be a list of {{num, doi, title}}")
    ordered: list[tuple[int, str, str]] = []
    seen: set[int] = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {"num", "doi", "title"}:
            raise ValueError(f"Task type {name!r} citation entries must be exactly {{num, doi, title}}")
        num = entry["num"]
        if not isinstance(num, int) or isinstance(num, bool) or num in seen:
            raise ValueError(f"Task type {name!r} has an invalid citation num: {num!r}")
        seen.add(num)
        doi = entry["doi"]
        title = entry.get("title", "")
        if not isinstance(doi, str) or not _DOI_PATTERN.fullmatch(doi.strip()):
            raise ValueError(f"Task type {name!r} has an invalid citation DOI: {doi!r}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Task type {name!r} citation {num} must declare the paper title")
        ordered.append((num, doi.strip(), title.strip()))
    return tuple(sorted(ordered))


_RESULT_VIEW_SOURCE_KEYS = {
    "candidate-collection": {"candidates", "supporting"},
    "entity-table": {"table", "structure"},
    "evidence-bundle": {"items"},
    "alignment": {"alignment"},
    "trajectory": {"topology", "coordinates"},
    "metric-series": {"series"},
    "matrix": {"matrices"},
    "scalar-summary": {"data"},
}
_RESULT_VIEW_MAPPING_KEYS = {
    "candidate-collection": {"confidence_encoding"},
    "entity-table": {
        "entity",
        "key_columns",
        "label_column",
        "chain_column",
        "residue_column",
        "numbering",
        "evidence_columns",
    },
    "evidence-bundle": set(),
    "alignment": {"format", "numbering"},
    "trajectory": {"coordinate_format", "frame_unit", "timestep", "alignment", "association"},
    "metric-series": {
        "format",
        "x_column",
        "value_columns",
        "value_path",
        "x_label",
        "y_label",
        "unit",
        "direction",
        "missing",
        "y_min",
        "y_max",
    },
    "matrix": {
        "format",
        "value_path",
        "row_labels_column",
        "x_label",
        "y_label",
        "unit",
        "direction",
        "scale",
        "scale_min",
        "scale_max",
        "center",
    },
    "scalar-summary": {"fields"},
}
_RESULT_VIEW_ROLES = {"primary", "evidence"}
_RESULT_ENTITIES = {"residue", "mutation", "candidate"}
_RESULT_NUMBERINGS = {"label_seq_id", "auth_seq_id"}
_RESULT_CONFIDENCE_ENCODINGS = {"plddt_bfactor"}
_RESULT_DATA_FORMATS = {"csv", "json"}
_RESULT_DIRECTIONS = {"higher", "lower", "neutral"}
_RESULT_MATRIX_SCALES = {"sequential", "diverging"}
_RESULT_TRAJECTORY_FORMATS = {"pdb", "xtc", "dcd"}


def register(task_type: TaskType, runner: RunnerConfig) -> None:
    """Register a task type + runner config pair."""
    _registry[task_type.name] = (task_type, runner)
    if _plugin_manager is not None:
        _plugin_manager.contributions.register("tasks", task_type.name, task_type, plugin_id="test")
        _plugin_manager.contributions.register("runner_configs", task_type.name, runner, plugin_id="test")


def get(name: str) -> tuple[TaskType, RunnerConfig]:
    """Look up a registered task type + runner config."""
    if _plugin_manager is not None:
        try:
            return (
                _plugin_manager.contributions.resolve("tasks", name),
                _plugin_manager.contributions.resolve("runner_configs", name),
            )
        except KeyError:
            raise KeyError(f"Unknown task type: {name!r}") from None
    if name not in _registry:
        raise KeyError(f"Unknown task type: {name!r}")
    return _registry[name]


def list_types() -> list[TaskType]:
    """Return all registered task types (for ``GET /api/types``)."""
    if _plugin_manager is not None:
        return [value for _identifier, value in _plugin_manager.contributions.items("tasks")]
    return [tt for tt, _ in _registry.values()]


def default_task_type() -> str:
    """Return the first discovered task when a caller omits an explicit type."""
    types = list_types()
    if not types:
        raise KeyError("No task types are enabled")
    return types[0].name


def list_runtimes() -> list[RuntimeFamily]:
    """Return all runtime families loaded from the portable registry."""
    if _plugin_manager is not None:
        return [value for _identifier, value in _plugin_manager.contributions.items("runtime_families")]
    return list(_runtime_registry.values())


def list_categories() -> list[Category]:
    """Return scientific categories in their server-owned display order."""
    return sorted(_category_registry.values(), key=lambda category: (category.order, category.name))


def iter_capabilities(task_type: TaskType) -> tuple[InputCapability, ...]:
    """Flatten one task's semantic steps into deterministic plugin order."""
    return tuple(capability for step in task_type.input_workspace for capability in step.capabilities)


def workspace_plugin_descriptor(identifier: str, *, owner: str | None = None):
    """Return a validated deployed workspace plugin descriptor."""
    return _plugin_manager.workspace_plugin(identifier, owner=owner) if _plugin_manager is not None else None


def workspace_backend(identifier: str, *, owner: str | None = None):
    """Resolve a runner-owned workspace backend from the active plugin graph."""
    return _plugin_manager.workspace_backend(identifier, owner=owner) if _plugin_manager is not None else None


def get_job_executor() -> str:
    """Return the executor selected once for the active registry."""
    return _job_executor


def get_container_runtime() -> str:
    """Return the container runtime selected once for the active registry."""
    return _container_runtime


def _valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.replace("_", "").replace("-", "").isalnum()


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _load_input_capability(
    entry: Any, seen_ids: set[str], *, capability_schemas: dict[str, dict[str, Any]] | None = None,
    plugin_ids: set[str] | None = None, workspace_owner: str | None = None,
) -> InputCapability:
    if not isinstance(entry, dict):
        raise ValueError("Each input workspace capability must be a mapping")
    unknown = set(entry) - {"plugin", "id", "title", "description", "options"}
    if unknown:
        raise ValueError(f"Unknown input workspace capability fields: {sorted(unknown)}")
    plugin = entry.get("plugin")
    capability_id = entry.get("id")
    local_plugin = str(plugin).split(":", 1)[-1] if isinstance(plugin, str) else plugin
    if plugin not in _INPUT_CAPABILITY_PLUGINS and plugin not in (plugin_ids or set()) and local_plugin not in (plugin_ids or set()):
        raise ValueError(f"Unknown input workspace plugin: {plugin!r}")
    if not _valid_identifier(capability_id):
        raise ValueError(f"Invalid input workspace capability id: {capability_id!r}")
    if capability_id in seen_ids:
        raise ValueError(f"Duplicate input workspace capability id: {capability_id!r}")
    options = entry.get("options", {})
    if not isinstance(options, dict):
        raise ValueError(f"Options for input workspace capability {capability_id!r} must be a mapping")
    allowed_options = _INPUT_CAPABILITY_OPTION_KEYS.get(local_plugin, set())
    schema = (capability_schemas or {}).get(local_plugin)
    if schema is not None:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(options)
        allowed_options = set(options)
    unknown_options = set(options) - allowed_options
    if unknown_options:
        raise ValueError(f"Unknown options for input workspace plugin {plugin!r}: {sorted(unknown_options)}")
    seen_ids.add(capability_id)
    return InputCapability(
        plugin=(f"{workspace_owner}:{local_plugin}" if workspace_owner and local_plugin not in _INPUT_CAPABILITY_PLUGINS else local_plugin),
        id=capability_id,
        title=str(entry.get("title") or ""),
        description=str(entry.get("description") or ""),
        options=options,
    )


def _load_input_workspace(
    raw: Any, *, capability_schemas: dict[str, dict[str, Any]] | None = None,
    plugin_ids: set[str] | None = None, workspace_owner: str | None = None
) -> tuple[InputStep, ...]:
    if raw is None:
        raise ValueError("Every task type must declare input_workspace")
    if not isinstance(raw, dict) or set(raw) != {"steps"}:
        raise ValueError("input_workspace must contain only a steps list")
    entries = raw["steps"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("input_workspace.steps must be a non-empty list")
    steps: list[InputStep] = []
    step_ids: set[str] = set()
    capability_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"id", "title", "description", "capabilities"}:
            raise ValueError("Each input workspace step must contain id, title, description, and capabilities")
        step_id = entry.get("id")
        if not _valid_identifier(step_id) or step_id in step_ids:
            raise ValueError(f"Invalid or duplicate input workspace step id: {step_id!r}")
        raw_capabilities = entry.get("capabilities")
        if not isinstance(raw_capabilities, list) or not raw_capabilities:
            raise ValueError(f"Input workspace step {step_id!r} must contain capabilities")
        step_ids.add(step_id)
        steps.append(
            InputStep(
                id=step_id,
                title=_required_text(entry.get("title"), f"Input workspace step {step_id!r} title"),
                description=str(entry.get("description") or "").strip(),
                capabilities=tuple(
                    _load_input_capability(
                        item, capability_ids, capability_schemas=capability_schemas,
                        plugin_ids=plugin_ids, workspace_owner=workspace_owner,
                    )
                    for item in raw_capabilities
                ),
            )
        )
    capabilities = tuple(capability for step in steps for capability in step.capabilities)
    if capabilities[0].plugin not in {"files", "sequence"}:
        raise ValueError("The first input workspace capability must collect files or a sequence")
    if capabilities[-1].plugin != "review":
        raise ValueError("The last input workspace capability must be review")
    known_ids = {capability.id for capability in capabilities}
    for capability in capabilities:
        source = capability.options.get("source")
        if source and source not in known_ids:
            raise ValueError(f"Input workspace capability {capability.id!r} references unknown source {source!r}")
    return tuple(steps)


def _load_artifact_selector(raw: Any, view_id: str) -> ArtifactSelector:
    if not isinstance(raw, dict) or set(raw) not in ({"path", "required"}, {"glob", "required"}):
        raise ValueError(f"Result view {view_id!r} selectors require exactly path or glob plus required")
    key = "glob" if "glob" in raw else "path"
    value = raw[key]
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"Unsafe result workspace artifact selector: {value!r}")
    if not isinstance(raw["required"], bool):
        raise ValueError(f"Result view {view_id!r} selector required must be a boolean")
    return ArtifactSelector(value=value, is_glob=key == "glob", required=raw["required"])


def _string_list(value: Any, field_name: str, *, required: bool = False) -> list[str]:
    if value is None and not required:
        return []
    if (
        not isinstance(value, list)
        or (required and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    return value


def _validate_result_mapping(plugin: str, mapping: Any, view_id: str) -> dict[str, Any]:
    if not isinstance(mapping, dict) or set(mapping) - _RESULT_VIEW_MAPPING_KEYS[plugin]:
        raise ValueError(f"Invalid mapping for result workspace plugin {plugin!r}")
    if plugin == "candidate-collection":
        confidence = mapping.get("confidence_encoding")
        if confidence is not None and confidence not in _RESULT_CONFIDENCE_ENCODINGS:
            raise ValueError(f"Invalid confidence encoding for result view {view_id!r}")
    elif plugin == "entity-table":
        if mapping.get("entity") not in _RESULT_ENTITIES:
            raise ValueError(f"Invalid entity for result view {view_id!r}")
        _string_list(mapping.get("key_columns"), f"Result view {view_id!r} key_columns", required=True)
        _string_list(mapping.get("evidence_columns", []), f"Result view {view_id!r} evidence_columns")
        for key in ("label_column", "chain_column", "residue_column"):
            if key in mapping and (not isinstance(mapping[key], str) or not mapping[key]):
                raise ValueError(f"Result view {view_id!r} {key} must be non-empty text")
        numbering = mapping.get("numbering")
        if numbering is not None and numbering not in _RESULT_NUMBERINGS:
            raise ValueError(f"Invalid numbering for result view {view_id!r}")
        if ("chain_column" in mapping or "residue_column" in mapping or numbering) and not {
            "chain_column",
            "residue_column",
            "numbering",
        }.issubset(mapping):
            raise ValueError(f"Incomplete structure mapping for result view {view_id!r}")
    elif plugin == "alignment":
        if mapping.get("format") not in {"a3m", "fasta", "stockholm"}:
            raise ValueError(f"Invalid alignment format for result view {view_id!r}")
        if mapping.get("numbering") not in {"sequence", "alignment"}:
            raise ValueError(f"Invalid alignment numbering for result view {view_id!r}")
    elif plugin == "trajectory":
        if mapping.get("coordinate_format") not in _RESULT_TRAJECTORY_FORMATS:
            raise ValueError(f"Invalid trajectory coordinate format for result view {view_id!r}")
        if not isinstance(mapping.get("frame_unit"), str) or not mapping["frame_unit"]:
            raise ValueError(f"Result view {view_id!r} frame_unit must be non-empty text")
        if not isinstance(mapping.get("timestep"), (int, float)) or isinstance(mapping["timestep"], bool):
            raise ValueError(f"Result view {view_id!r} timestep must be numeric")
        if "alignment" in mapping and (not isinstance(mapping["alignment"], str) or not mapping["alignment"]):
            raise ValueError(f"Result view {view_id!r} alignment must be non-empty text")
        if mapping.get("association") not in {"single", "stem-prefix"}:
            raise ValueError(f"Invalid trajectory association for result view {view_id!r}")
    elif plugin in {"metric-series", "matrix"}:
        if mapping.get("format") not in _RESULT_DATA_FORMATS:
            raise ValueError(f"Invalid data format for result view {view_id!r}")
        if mapping.get("direction") not in _RESULT_DIRECTIONS:
            raise ValueError(f"Invalid metric direction for result view {view_id!r}")
        for key in ("x_label", "y_label", "unit"):
            if key in mapping and not isinstance(mapping[key], str):
                raise ValueError(f"Result view {view_id!r} {key} must be text")
        if plugin == "metric-series":
            _string_list(mapping.get("value_columns", []), f"Result view {view_id!r} value_columns")
            if mapping["format"] == "csv" and not mapping.get("value_columns"):
                raise ValueError(f"CSV metric series {view_id!r} must declare value_columns")
            if mapping["format"] == "json" and not isinstance(mapping.get("value_path"), str):
                raise ValueError(f"JSON metric series {view_id!r} must declare value_path")
        else:
            if mapping.get("scale") not in _RESULT_MATRIX_SCALES:
                raise ValueError(f"Invalid matrix scale for result view {view_id!r}")
            if mapping["format"] == "json" and not isinstance(mapping.get("value_path"), str):
                raise ValueError(f"JSON matrix {view_id!r} must declare value_path")
        for key in ("y_min", "y_max", "scale_min", "scale_max", "center"):
            if key in mapping and (not isinstance(mapping[key], (int, float)) or isinstance(mapping[key], bool)):
                raise ValueError(f"Result view {view_id!r} {key} must be numeric")
    elif plugin == "scalar-summary":
        fields = mapping.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError(f"Result view {view_id!r} fields must be a non-empty list")
        for scalar_field in fields:
            if not isinstance(scalar_field, dict) or set(scalar_field) != {"path", "label", "unit", "direction"}:
                raise ValueError(f"Result view {view_id!r} scalar fields require path, label, unit, and direction")
            if not all(isinstance(scalar_field[key], str) and scalar_field[key] for key in ("path", "label")):
                raise ValueError(f"Result view {view_id!r} scalar field path and label must be non-empty text")
            if not isinstance(scalar_field["unit"], str) or scalar_field["direction"] not in _RESULT_DIRECTIONS:
                raise ValueError(f"Result view {view_id!r} scalar field has invalid unit or direction")
    return mapping


def _load_result_workspace(raw: Any) -> tuple[ResultView, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, dict) or set(raw) != {"views"} or not isinstance(raw["views"], list):
        raise ValueError("result_workspace must contain only a views list")
    views: list[ResultView] = []
    seen: set[str] = set()
    for entry in raw["views"]:
        if not isinstance(entry, dict) or set(entry) != {
            "plugin",
            "id",
            "role",
            "title",
            "description",
            "sources",
            "mapping",
        }:
            raise ValueError(
                "Result workspace views require plugin, id, role, title, description, sources, and mapping"
            )
        plugin = entry.get("plugin")
        view_id = entry.get("id")
        if plugin not in _RESULT_VIEW_SOURCE_KEYS:
            raise ValueError(f"Unknown result workspace plugin: {plugin!r}")
        if not _valid_identifier(view_id) or view_id in seen:
            raise ValueError(f"Invalid or duplicate result workspace view id: {view_id!r}")
        role = entry.get("role")
        if role not in _RESULT_VIEW_ROLES:
            raise ValueError(f"Invalid role for result workspace view {view_id!r}")
        sources = entry.get("sources")
        if not isinstance(sources, dict) or not sources or set(sources) - _RESULT_VIEW_SOURCE_KEYS[plugin]:
            raise ValueError(f"Invalid sources for result workspace plugin {plugin!r}")
        required_source_keys = {
            "candidate-collection": {"candidates"},
            "entity-table": {"table"},
            "evidence-bundle": {"items"},
            "alignment": {"alignment"},
            "trajectory": {"topology", "coordinates"},
            "metric-series": {"series"},
            "matrix": {"matrices"},
            "scalar-summary": {"data"},
        }[plugin]
        if not required_source_keys.issubset(sources):
            raise ValueError(f"Incomplete sources for result workspace view {view_id!r}")
        normalized_sources: dict[str, tuple[ArtifactSelector, ...]] = {}
        for source_name, selectors in sources.items():
            if not isinstance(selectors, list) or not selectors:
                raise ValueError(f"Result view {view_id!r} source {source_name!r} must contain selectors")
            normalized_sources[source_name] = tuple(_load_artifact_selector(item, view_id) for item in selectors)
        seen.add(view_id)
        views.append(
            ResultView(
                plugin=plugin,
                id=view_id,
                role=role,
                title=_required_text(entry.get("title"), f"Result view {view_id!r} title"),
                description=_required_text(entry.get("description"), f"Result view {view_id!r} description"),
                sources=normalized_sources,
                mapping=_validate_result_mapping(plugin, entry.get("mapping"), view_id),
            )
        )
    if sum(view.role == "primary" for view in views) > 1:
        raise ValueError("result_workspace may declare at most one primary view")
    return tuple(views)


def _load_workflow(raw: Any, task_name: str, stage_markers: dict[str, str]) -> tuple[WorkflowStage, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError(f"Task type {task_name!r} workflow must contain at least two stages")
    stages: list[WorkflowStage] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) - {
            "name",
            "display_name",
            "requires_gpu",
            "requires_network",
            "runner_args",
            "stage_markers",
        }:
            raise ValueError(f"Task type {task_name!r} has an invalid workflow stage")
        name = entry.get("name")
        requires_gpu = entry.get("requires_gpu", False)
        requires_network = entry.get("requires_network", False)
        runner_args = entry.get("runner_args", ())
        raw_markers = entry.get("stage_markers", ())
        if not isinstance(name, str) or not name.replace("_", "").isalnum() or name in seen:
            raise ValueError(f"Task type {task_name!r} has an invalid or duplicate workflow stage name")
        if not isinstance(requires_gpu, bool):
            raise ValueError(f"Workflow stage {task_name}.{name} requires_gpu must be a boolean")
        if not isinstance(requires_network, bool):
            raise ValueError(f"Workflow stage {task_name}.{name} requires_network must be a boolean")
        if not isinstance(runner_args, list) or not all(isinstance(arg, str) for arg in runner_args):
            raise ValueError(f"Workflow stage {task_name}.{name} runner_args must be a list of strings")
        if not isinstance(raw_markers, list) or not all(isinstance(marker, str) for marker in raw_markers):
            raise ValueError(f"Workflow stage {task_name}.{name} stage_markers must be a list of strings")
        markers = tuple(raw_markers)
        if not markers or not set(markers).issubset(stage_markers):
            raise ValueError(f"Workflow stage {task_name}.{name} must reference declared stage markers")
        seen.add(name)
        stages.append(
            WorkflowStage(
                name=f"{task_name}.{name}",
                display_name=str(entry.get("display_name") or name.replace("_", " ").title()),
                requires_gpu=requires_gpu,
                requires_network=requires_network,
                runner_args=tuple(runner_args),
                stage_markers=markers,
            )
        )
    return tuple(stages)


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


# PTC-W6004: operator-provisioned runner YAML path, not user input
def _load_runner_config(path: str) -> RunnerConfig:  # skipcq: PTC-W6004
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return RunnerConfig(
        mounts=tuple(
            RunnerMount(
                host_path=m["host_path"],
                container_path=m["container_path"],
                mode=m.get("mode", "ro"),
            )
            for m in data.get("mounts", [])
        ),
        env=data.get("env", {}),
        max_runtime_seconds=data.get("max_runtime_seconds"),
        defaults=data.get("defaults", {}),
    )
