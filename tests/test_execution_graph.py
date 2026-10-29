# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from types import SimpleNamespace

import pytest

from revocompute.execution_graph import GraphValidationError, canonical_digest, compile_graph
from revocompute.task_types import StagePortSpec, WorkflowStage


def stage(name, source=None, *, input_type="x", output_type="x"):
    inputs = (StagePortSpec("input", input_type, source=source),) if source is not None else ()
    return WorkflowStage(name, name, False, inputs=inputs, outputs=(StagePortSpec("out", output_type),))


def graph(*stages):
    return SimpleNamespace(workflow=stages, inputs=(SimpleNamespace(name="source", type="x"),))


def test_stable_digest_and_topological_order():
    task = graph(stage("b", "a:out"), stage("a", "graph:source"))
    compiled = compile_graph(task)
    assert compiled.execution_order == ("a", "b")
    assert compiled.digest == compile_graph(task).digest
    assert canonical_digest(compiled.document) == compiled.digest


@pytest.mark.parametrize(("stages", "message"), [
    ((stage("a"), stage("a")), "duplicate node id"),
    ((stage("a", "b:out"), stage("b", "a:out")), "cycle"),
    ((stage("a", "missing:out"),), "unknown node"),
    ((stage("a"), stage("b", "a:missing")), "unknown port"),
    ((stage("a"), stage("b", "a:out", input_type="y")), "type mismatch"),
    ((stage("a", "graph:source", input_type="y"),), "type mismatch"),
    ((WorkflowStage("a", "a", False, inputs=(StagePortSpec("input", "x"),)),), "no binding"),
])
def test_invalid_graph_rejected(stages, message):
    with pytest.raises(GraphValidationError, match=message):
        compile_graph(graph(*stages))


def test_declared_output_paths_must_not_overlap():
    first = WorkflowStage(
        "a", "a", False, outputs=(StagePortSpec("out", "x", path="features/*.dat"),),
    )
    second = WorkflowStage(
        "b", "b", False, outputs=(StagePortSpec("out", "x", path="features/result.dat"),),
    )
    with pytest.raises(GraphValidationError, match="output paths overlap"):
        compile_graph(graph(first, second))


def test_fork_join_and_diamond_compile_in_topological_order():
    fork = compile_graph(graph(stage("a"), stage("b", "a:out"), stage("c", "a:out")))
    assert fork.execution_order == ("a", "b", "c")

    def join_stage(name, sources):
        return WorkflowStage(
            name, name, False,
            inputs=tuple(StagePortSpec(f"input{index}", "x", source=source) for index, source in enumerate(sources)),
        )

    join = compile_graph(graph(stage("b"), stage("c"), join_stage("d", ["b:out", "c:out"])))
    assert join.execution_order == ("b", "c", "d")

    diamond = compile_graph(
        graph(stage("a"), stage("b", "a:out"), stage("c", "a:out"), join_stage("d", ["b:out", "c:out"]))
    )
    assert diamond.execution_order == ("a", "b", "c", "d")
    assert diamond.execution_order == compile_graph(
        graph(stage("a"), stage("b", "a:out"), stage("c", "a:out"), join_stage("d", ["b:out", "c:out"]))
    ).execution_order


def test_graph_bounds():
    with pytest.raises(GraphValidationError, match="node bound"):
        compile_graph(graph(*(stage(str(i)) for i in range(33))))
    with pytest.raises(GraphValidationError, match="fan-out"):
        compile_graph(graph(stage("a"), *(stage(str(i), "a:out") for i in range(9))))
    with pytest.raises(GraphValidationError, match="depth"):
        compile_graph(graph(stage("0"), *(stage(str(i), f"{i - 1}:out") for i in range(1, 17))))
