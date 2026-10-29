# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Compile manifest workflows into a deterministic execution graph.

Fork, join, and independent roots are serialized in deterministic order.
A required consumer input implies a required producer output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

GRAPH_IR_VERSION = 1


class GraphValidationError(ValueError):
    """The workflow does not describe a valid graph."""


@dataclass(frozen=True)
class ArtifactPort:
    name: str
    type: str
    path: str | None = None
    required: bool = True


@dataclass(frozen=True)
class StageNode:
    id: str
    family: str
    runner_args: tuple[str, ...]
    requires_gpu: bool
    requires_network: bool
    stage_markers: tuple[str, ...]
    inputs: dict[str, str]
    outputs: tuple[ArtifactPort, ...]


@dataclass(frozen=True)
class CompiledGraph:
    nodes: tuple[StageNode, ...]
    graph_inputs: tuple[ArtifactPort, ...]
    execution_order: tuple[str, ...]
    digest: str
    document: dict[str, Any]
    ir_version: int = GRAPH_IR_VERSION


def compile_graph(task_type: Any) -> CompiledGraph:
    stages = tuple(task_type.workflow)
    if len(stages) > 32:
        raise GraphValidationError("graph exceeds node bound of 32")
    by_id = {}
    for stage in stages:
        if stage.name in by_id:
            raise GraphValidationError(f"duplicate node id: {stage.name}")
        by_id[stage.name] = stage
    graph_inputs = {}
    edges = {name: set() for name in by_id}
    nodes = {}
    for name, stage in by_id.items():
        outputs = tuple(ArtifactPort(port.name, port.type, port.path, port.required) for port in stage.outputs)
        bindings = {}
        for port in stage.inputs:
            binding = port.source or ""
            if not binding:
                if port.required:
                    raise GraphValidationError(f"required input {name}:{port.name} has no binding")
                continue
            bindings[port.name] = binding
            if binding.startswith("graph:"):
                role = binding[6:]
                role_types = {item.name: item.type for item in task_type.inputs}
                if role not in role_types:
                    raise GraphValidationError(f"unknown graph input: {role}")
                if role_types[role] != port.type:
                    raise GraphValidationError(f"artifact type mismatch: {binding} -> {name}:{port.name}")
                graph_inputs[role] = ArtifactPort(role, port.type)
                continue
            if ":" not in binding:
                raise GraphValidationError(f"invalid binding: {binding}")
            producer, output_name = binding.rsplit(":", 1)
            if producer not in by_id:
                raise GraphValidationError(f"edge to unknown node: {producer}")
            output = next((item for item in by_id[producer].outputs if item.name == output_name), None)
            if output is None:
                raise GraphValidationError(f"unknown port: {binding}")
            if output.type != port.type:
                raise GraphValidationError(f"artifact type mismatch: {binding} -> {name}:{port.name}")
            if port.required and not output.required:
                raise GraphValidationError(
                    f"required input {name}:{port.name} cannot bind optional output {binding}"
                )
            edges[producer].add(name)
        nodes[name] = StageNode(
            name,
            stage.family or task_type.runtime.name,
            stage.runner_args,
            stage.requires_gpu,
            stage.requires_network,
            stage.stage_markers,
            bindings,
            outputs,
        )
    declared_outputs = [
        (node.id, port.path) for node in nodes.values() for port in node.outputs if port.path is not None
    ]
    for position, (node_id, path) in enumerate(declared_outputs):
        for other_node, other_path in declared_outputs[position + 1:]:
            if node_id != other_node and _paths_overlap(path, other_path):
                raise GraphValidationError(
                    f"output paths overlap between {node_id} ({path}) and {other_node} ({other_path})"
                )
    for name, targets in edges.items():
        if len(targets) > 8:
            raise GraphValidationError(f"graph exceeds fan-out bound of 8 at {name}")
    predecessors = {name: {source for source, targets in edges.items() if name in targets} for name in nodes}
    order = []
    remaining = set(nodes)
    while remaining:
        ready = sorted(name for name in remaining if not predecessors[name] & remaining)
        if not ready:
            raise GraphValidationError("graph contains a cycle")
        order.append(ready[0])
        remaining.remove(ready[0])
    depth = {}
    for name in order:
        depth[name] = 1 + max((depth[parent] for parent in predecessors[name]), default=0)
        if depth[name] > 16:
            raise GraphValidationError("graph exceeds depth bound of 16")
    ordered_nodes = tuple(nodes[name] for name in order)
    inputs = tuple(graph_inputs[name] for name in sorted(graph_inputs))
    document = {"ir_version": GRAPH_IR_VERSION, "nodes": [asdict(node) for node in ordered_nodes],
                "graph_inputs": [asdict(port) for port in inputs], "execution_order": order}
    digest = canonical_digest(document)
    return CompiledGraph(ordered_nodes, inputs, tuple(order), digest, document)


def canonical_digest(document: dict[str, Any]) -> str:
    """The one digest definition shared by compilation and frozen-graph checks."""
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _paths_overlap(first: str | None, second: str | None) -> bool:
    """Conservatively decide whether two declared output patterns can collide."""
    if first is None or second is None:
        return True
    first_static = _static_prefix(first)
    second_static = _static_prefix(second)
    if first_static == second_static:
        return True
    shorter, longer = sorted((first_static, second_static), key=len)
    return len(shorter) < len(longer) and longer[: len(shorter)] == shorter


def _static_prefix(path: str) -> tuple[str, ...]:
    parts = []
    for part in path.split("/"):
        if any(character in part for character in "*?["):
            break
        parts.append(part)
    return tuple(parts)
