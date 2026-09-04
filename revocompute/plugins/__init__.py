# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Small kernel for trusted, server-provisioned REvoCompute plugins.

The kernel deliberately deals only in plugin identity, lifecycle, and typed
contributions.  Scientific/task semantics remain owned by the contributing
runner family and task modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or not value.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"Plugin manifest {field_name} must be a valid identifier")
    return value.strip()


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Validated metadata loaded from a plugin's ``plugin.yaml`` file."""

    id: str
    version: str
    path: Path
    name: str = ""
    runner_family: str | None = None
    contributions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    configuration_schemas: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    workspace_plugins: Mapping[str, "WorkspacePluginDescriptor"] = field(default_factory=dict)
    api_version: str = "1"
    runtime: Mapping[str, Any] = field(default_factory=dict)
    tasks: tuple[str, ...] = ()
    access_policies: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, path: str | Path = ".") -> "PluginManifest":
        if not isinstance(raw, Mapping):
            raise ValueError("Plugin manifest must be a mapping")
        plugin_id = _identifier(raw.get("id"), "id")
        version = raw.get("version", "0.0.0")
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"Plugin manifest {plugin_id!r} version must be non-empty text")
        runner = raw.get("runner_family")
        if runner is not None:
            runner = _identifier(runner, "runner_family")
        raw_contributions = raw.get("contributions", {})
        if not isinstance(raw_contributions, Mapping):
            raise ValueError(f"Plugin manifest {plugin_id!r} contributions must be a mapping")
        contributions: dict[str, tuple[str, ...]] = {}
        workspace_plugins: dict[str, WorkspacePluginDescriptor] = {}
        for kind, values in raw_contributions.items():
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError("Plugin contribution kind must be non-empty text")
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, Iterable) or isinstance(values, (bytes, Mapping)):
                raise ValueError(f"Plugin contribution {kind!r} must be a list of identifiers")
            normalized: list[str] = []
            for value in values:
                if kind == "input_workspace_plugins" and isinstance(value, Mapping):
                    identifier = _identifier(value.get("id"), f"contribution {kind}")
                    workspace_plugins[identifier] = WorkspacePluginDescriptor.from_mapping(
                        identifier, value, owner=runner or plugin_id, root=Path(path)
                    )
                    normalized.append(identifier)
                else:
                    normalized.append(_identifier(value, f"contribution {kind}"))
            contributions[kind] = tuple(normalized)
        # Contribution configuration schemas are declarative plugin metadata.
        # Keep them available to consumers without teaching Core their vocabulary.
        raw_schemas = raw.get("configuration_schemas", {})
        if not isinstance(raw_schemas, Mapping):
            raise ValueError(f"Plugin manifest {plugin_id!r} configuration_schemas must be a mapping")
        configuration_schemas = {
            str(kind): dict(declarations) if isinstance(declarations, Mapping) else declarations
            for kind, declarations in raw_schemas.items()
        }
        api_version = raw.get("api_version", "1")
        if not isinstance(api_version, (str, int)):
            raise ValueError(f"Plugin manifest {plugin_id!r} api_version must be text or integer")
        runtime = raw.get("runtime", {})
        if not isinstance(runtime, Mapping):
            raise ValueError(f"Plugin manifest {plugin_id!r} runtime must be a mapping")
        def _paths(field_name: str) -> tuple[str, ...]:
            values = raw.get(field_name, ())
            if isinstance(values, str):
                values = (values,)
            if not isinstance(values, Iterable) or isinstance(values, (bytes, Mapping)):
                raise ValueError(f"Plugin manifest {plugin_id!r} {field_name} must be a list")
            result = tuple(str(value) for value in values)
            return result
        tasks = _paths("tasks")
        access_policies = _paths("access_policies")
        known = {"api_version", "id", "version", "name", "runner_family", "runtime", "tasks", "access_policies", "contributions", "configuration_schemas"}
        metadata = {key: value for key, value in raw.items() if key not in known}
        return cls(
            plugin_id, version.strip(), Path(path), str(raw.get("name") or plugin_id), runner, contributions,
            configuration_schemas, metadata, workspace_plugins, str(api_version), dict(runtime), tasks, access_policies
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "PluginManifest":
        manifest_path = Path(path)
        with manifest_path.open(encoding="utf-8") as stream:
            raw = yaml.safe_load(stream) or {}
        return cls.from_mapping(raw, path=manifest_path.parent)


@dataclass(frozen=True, slots=True)
class ContributionEntry:
    """A contribution plus its owning plugin identity."""

    plugin_id: str
    value: Any


@dataclass(frozen=True, slots=True)
class WorkspacePluginDescriptor:
    """Validated, runner-owned browser assets for an input workspace plugin."""

    id: str
    owner: str
    module: str
    styles: tuple[str, ...] = ()
    configuration_schema: str | None = None
    root: Path = Path(".")
    backend: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, identifier: str, raw: Mapping[str, Any], *, owner: str, root: Path) -> "WorkspacePluginDescriptor":
        module = raw.get("module")
        if not isinstance(module, str) or not module.strip():
            raise ValueError(f"Workspace plugin {identifier!r} must declare a module asset")
        styles = raw.get("styles", ())
        if isinstance(styles, str):
            styles = (styles,)
        if not isinstance(styles, Iterable) or isinstance(styles, (bytes, Mapping)):
            raise ValueError(f"Workspace plugin {identifier!r} styles must be a list")
        styles = tuple(styles)
        if not all(isinstance(item, str) and item.strip() for item in styles):
            raise ValueError(f"Workspace plugin {identifier!r} styles must contain paths")
        schema = raw.get("configuration_schema", raw.get("schema"))
        if schema is not None and (not isinstance(schema, str) or not schema.strip()):
            raise ValueError(f"Workspace plugin {identifier!r} configuration_schema must be a path")
        paths = [module, *styles, *([schema] if schema else [])]
        for asset in paths:
            if not isinstance(asset, str) or "\\" in asset:
                raise ValueError(f"Workspace plugin {identifier!r} asset path must be a POSIX relative path")
            candidate = Path(str(asset))
            if candidate.is_absolute() or ".." in candidate.parts or "" in candidate.parts:
                raise ValueError(f"Workspace plugin {identifier!r} asset path must stay within plugin root")
        backend = raw.get("backend", {})
        if backend and (not isinstance(backend, Mapping) or any(not isinstance(v, str) for v in backend.values())):
            raise ValueError(f"Workspace plugin {identifier!r} backend must map names to entrypoints")
        for entrypoint in backend.values():
            module_path = str(entrypoint).rsplit(":", 1)[0]
            candidate = Path(module_path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ValueError(f"Workspace plugin {identifier!r} backend path must stay within plugin root")
        return cls(identifier, owner, module.strip(), tuple(str(item) for item in styles), schema.strip() if schema else None, root, dict(backend))

    @property
    def global_id(self) -> str:
        return f"{self.owner}:{self.id}"

    def asset_path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("Workspace plugin asset escapes plugin root")
        return candidate


class ContributionRegistry:
    """Typed ``kind -> id -> object`` registry with duplicate protection."""

    def __init__(self) -> None:
        self._values: dict[str, dict[str, ContributionEntry]] = {}

    def register(self, kind: str, identifier: str, value: Any, *, plugin_id: str | None = None) -> Any:
        kind = _identifier(kind, "contribution kind")
        identifier = _identifier(identifier, "contribution id")
        bucket = self._values.setdefault(kind, {})
        if identifier in bucket:
            owner = bucket[identifier].plugin_id
            suffix = f" (already provided by {owner!r})"
            raise ValueError(f"Duplicate {kind} contribution: {identifier!r}{suffix}")
        bucket[identifier] = ContributionEntry(plugin_id or "", value)
        return value

    def get(self, kind: str, identifier: str) -> Any | None:
        entry = self._values.get(kind, {}).get(identifier)
        return entry.value if entry is not None else None

    def resolve(self, kind: str, identifier: str) -> Any:
        value = self.get(kind, identifier)
        if value is None:
            raise KeyError(f"Unknown {kind} contribution: {identifier!r}")
        return value

    def items(self, kind: str) -> tuple[tuple[str, Any], ...]:
        return tuple((key, entry.value) for key, entry in self._values.get(kind, {}).items())

    def discard_plugin(self, plugin_id: str) -> None:
        for kind, values in self._values.items():
            self._values[kind] = {key: entry for key, entry in values.items() if entry.plugin_id != plugin_id}


@dataclass(slots=True)
class PluginContext:
    manifest: PluginManifest
    contributions: ContributionRegistry
    services: Mapping[str, Any] = field(default_factory=dict)


class PluginManager:
    """Discover and manage trusted plugins supplied with a server instance."""

    def __init__(self, *, services: Mapping[str, Any] | None = None) -> None:
        self.contributions = ContributionRegistry()
        self.services = services or {}
        self._plugins: dict[str, PluginContext] = {}
        self._disposers: dict[str, Callable[[], Any]] = {}
        self._disabled: set[str] = set()
        self._workspace_plugins: dict[str, WorkspacePluginDescriptor] = {}

    @property
    def plugins(self) -> tuple[PluginManifest, ...]:
        return tuple(context.manifest for context in self._plugins.values())

    def discover(self, directory: str | Path, *, enabled: set[str] | None = None) -> tuple[PluginManifest, ...]:
        root = Path(directory)
        manifests = sorted(root.glob("*/plugin.yaml")) if root.exists() else []
        enabled_ids = set(enabled or ())
        for path in manifests:
            manifest = PluginManifest.from_file(path)
            if enabled_ids and manifest.id not in enabled_ids:
                continue
            self.register_manifest(manifest)
        return self.plugins

    def register_manifest(self, manifest: PluginManifest) -> PluginContext:
        if manifest.id in self._plugins:
            raise ValueError(f"Duplicate plugin: {manifest.id!r}")
        context = PluginContext(manifest, self.contributions, self.services)
        self._plugins[manifest.id] = context
        for descriptor in manifest.workspace_plugins.values():
            if descriptor.global_id in self._workspace_plugins:
                raise ValueError(f"Duplicate input workspace plugin: {descriptor.global_id!r}")
            self._workspace_plugins[descriptor.global_id] = descriptor
        return context

    def workspace_plugin(self, identifier: str, *, owner: str | None = None) -> WorkspacePluginDescriptor | None:
        """Resolve a runner-owned workspace plugin by local or namespaced ID."""
        if ":" in identifier:
            return self._workspace_plugins.get(identifier)
        matches = [item for item in self._workspace_plugins.values() if item.id == identifier and (owner is None or item.owner == owner)]
        return matches[0] if len(matches) == 1 else None

    def workspace_plugins(self) -> tuple[WorkspacePluginDescriptor, ...]:
        return tuple(self._workspace_plugins.values())

    def get(self, plugin_id: str) -> PluginContext | None:
        """Return a plugin context, or ``None`` when it is not installed."""
        return self._plugins.get(plugin_id)

    def disable(self, plugin_id: str) -> None:
        """Disable a plugin and dispose any active resources."""
        if plugin_id not in self._plugins:
            raise KeyError(f"Unknown plugin: {plugin_id!r}")
        self._disabled.add(plugin_id)
        self.deactivate(plugin_id)

    def enable(self, plugin_id: str) -> None:
        """Enable an installed plugin; activation remains explicit."""
        if plugin_id not in self._plugins:
            raise KeyError(f"Unknown plugin: {plugin_id!r}")
        self._disabled.discard(plugin_id)

    def register_contribution(self, plugin_id: str, kind: str, identifier: str, value: Any) -> Any:
        context = self._plugins.get(plugin_id)
        if context is None:
            raise KeyError(f"Unknown plugin: {plugin_id!r}")
        declared = context.manifest.contributions.get(kind)
        if declared is not None and identifier not in declared:
            raise ValueError(f"Plugin {plugin_id!r} did not declare {kind} contribution {identifier!r}")
        return self.contributions.register(kind, identifier, value, plugin_id=plugin_id)

    def activate(self, plugin_id: str, activate: Callable[[PluginContext], Any]) -> None:
        if plugin_id in self._disabled:
            raise RuntimeError(f"Plugin {plugin_id!r} is disabled")
        context = self._plugins[plugin_id]
        disposer = activate(context)
        if callable(disposer):
            self._disposers[plugin_id] = disposer

    def deactivate(self, plugin_id: str) -> None:
        disposer = self._disposers.pop(plugin_id, None)
        if disposer:
            disposer()
        self.contributions.discard_plugin(plugin_id)
        context = self._plugins.get(plugin_id)
        owners = {plugin_id}
        if context and context.manifest.runner_family:
            owners.add(context.manifest.runner_family)
        self._workspace_plugins = {key: value for key, value in self._workspace_plugins.items() if value.owner not in owners}

    def dispose(self) -> None:
        for plugin_id in reversed(tuple(self._plugins)):
            self.deactivate(plugin_id)


__all__ = ["ContributionEntry", "ContributionRegistry", "PluginContext", "PluginManager", "PluginManifest", "WorkspacePluginDescriptor"]
