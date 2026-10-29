# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""A produced artifact reaches a consumer as a verified, bound stage input."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from revocompute import stage_state
from revocompute import task_runtime
from revocompute.db import TaskDatabase
from revocompute.execution_graph import compile_graph
from revocompute.job import STAGE_INPUTS_CONTAINER_DIR, STAGE_INPUTS_DOCUMENT_NAME
from revocompute.resource_policy import ResolvedResources
from revocompute.task_types import RuntimeFamily, StagePortSpec, TaskType, WorkflowStage


def _policy() -> ResolvedResources:
    return ResolvedResources(
        cpus=4,
        memory="8G",
        max_runtime_seconds=3600,
        partition="cpu",
        gres=None,
        nodes=1,
        ntasks=1,
        qos=None,
        account=None,
        constraint=None,
        exclusive=False,
        requires_gpu=False,
        sources={},
    )


def _task_type(producer_path: str = "features/*.dat") -> TaskType:
    runtime = RuntimeFamily("stage_input_runner", ("bash", "run.sh"), "runner.def", "image.sif")
    producer = WorkflowStage(
        "stage_input_runner.features", "Features", False, ("-s", "features"), ("msa",),
        outputs=(StagePortSpec("features", "features", path=producer_path),),
    )
    consumer = WorkflowStage(
        "stage_input_runner.model", "Model", False, ("-s", "model"), ("model",),
        inputs=(StagePortSpec("features", "features", source="stage_input_runner.features:features"),),
    )
    return TaskType(
        "stage_input_runner",
        "Staged synthetic calculation",
        runtime,
        (),
        stage_markers={"msa": "MSA", "model": "Model"},
        workflow=(consumer, producer),
    )


def _workspace(tmp_path) -> list[dict]:
    return [{"type": "workspace", "workspace_root": str(tmp_path / "workspace"), "workspace_key": "owner-key"}]


def _prepare(
    tmp_path, monkeypatch, *, producer_path: str = "features/*.dat"
) -> tuple[TaskDatabase, str, TaskType, Path]:
    database = TaskDatabase(str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(task_runtime, "task_store", database)
    task_type = _task_type(producer_path)
    monkeypatch.setattr(task_runtime, "_get_task_type", lambda name: (task_type, None))
    monkeypatch.setattr(task_runtime, "_get_family", lambda name: (task_type.runtime, None))
    task_id = "c" * 32
    database.upsert_task(
        task_id,
        filename="input.fasta",
        file_path="/tmp/input.fasta",
        uploaded_at=time.time(),
        status="queued",
        is_binary=0,
        task_type=task_type.name,
        storage_key="owner-key",
        submitted_by_user_id=0,
    )
    graph = compile_graph(task_type)
    database.update_task(
        task_id,
        input_form=json.dumps({
            "execution_graph": {"ir_version": graph.ir_version, "digest": graph.digest, "document": graph.document},
        }),
    )
    output = tmp_path / "output"
    output.mkdir()
    return database, task_id, task_type, output


def _run(database, task_id, task_type, output, entities) -> str:
    return task_runtime._run_compute_workflow(
        task_id,
        database.get_task(task_id),
        task_type,
        entities,
        str(output),
        {stage.name: _policy() for stage in task_type.workflow},
        lambda _stage: None,
    )


class _Job:
    """A scheduler-free stand-in that publishes the producer's declared output."""

    def __init__(self, stage_tt, output: Path):
        self.stage_tt = stage_tt
        self.output = output

    def submit(self) -> str:
        return "42"

    def poll(self):
        if self.stage_tt.name.endswith("features"):
            (self.output / "features").mkdir(exist_ok=True)
            (self.output / "features" / "2KL8.dat").write_text("features", encoding="utf-8")
        return task_runtime.JobState.COMPLETED


def test_the_consumer_reads_a_verified_copy_named_by_a_server_document(tmp_path, monkeypatch):
    database, task_id, task_type, output = _prepare(tmp_path, monkeypatch)
    staged: dict[str, str | None] = {}

    def _create_job(_task_id, stage_tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        staged[stage_tt.name] = kwargs.get("stage_inputs_dir")
        return _Job(stage_tt, output)

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = _run(database, task_id, task_type, output, _workspace(tmp_path))

    assert result == task_runtime.JobState.COMPLETED
    # A stage whose inputs are all graph-role uploads stages nothing.
    assert staged["stage_input_runner-features"] is None
    directory = Path(staged["stage_input_runner-model"])
    assert directory == tmp_path / "workspace" / "stage_inputs" / "stage_input_runner.model"
    document = json.loads((directory / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["stage"] == "stage_input_runner.model"
    assert document["inputs"] == {
        "features": {
            "path": f"{STAGE_INPUTS_CONTAINER_DIR}/features/2KL8.dat",
            "files": [
                {
                    "path": f"{STAGE_INPUTS_CONTAINER_DIR}/features/2KL8.dat",
                    "source_path": "features/2KL8.dat",
                    "sha256": hashlib.sha256(b"features").hexdigest(),
                    "size": 8,
                }
            ],
            "producer": "stage_input_runner.features",
            "producer_attempt": 1,
        }
    }
    # The bytes the consumer is handed are the copy, not the shared output tree,
    # so the consumer's own outputs can never rewrite its input.
    assert (directory / "features" / "2KL8.dat").read_text(encoding="utf-8") == "features"


def test_a_changed_producer_artifact_never_becomes_a_consumer_input(tmp_path, monkeypatch):
    database, task_id, task_type, output = _prepare(tmp_path, monkeypatch)
    (output / "features").mkdir()
    (output / "features" / "2KL8.dat").write_text("features", encoding="utf-8")
    index = next(i for i, stage in enumerate(task_type.workflow) if stage.name == "stage_input_runner.features")
    attempt = database.begin_stage_attempt(
        task_id=task_id, stage_index=index, stage_name="stage_input_runner.features"
    )
    identity = task_runtime._stage_output_identity(str(output), task_type.workflow[1].outputs)
    assert identity is not None
    assert database.finish_stage_attempt(
        task_id=task_id,
        stage_name="stage_input_runner.features",
        attempt=attempt["attempt"],
        status=stage_state.COMPLETED,
        reason_code="completed",
        output_identity=identity,
    )
    (output / "features" / "2KL8.dat").write_text("tampered", encoding="utf-8")

    def _create_job(*_args, **_kwargs):
        raise AssertionError("a consumer must not run on an artifact the Server cannot verify")

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = _run(database, task_id, task_type, output, _workspace(tmp_path))

    assert result == task_runtime.JobState.FAILED
    diagnostics = database.get_task_diagnostics(task_id) or {}
    assert diagnostics.get("reason_code") == "stage_output_invalid"
    assert not (tmp_path / "workspace" / "stage_inputs").exists()


def test_a_consumer_without_an_execution_workspace_is_refused_before_any_allocation(tmp_path, monkeypatch):
    database, task_id, task_type, output = _prepare(tmp_path, monkeypatch)
    created: list[str] = []

    def _create_job(_task_id, stage_tt, _runner, _entities, _output, stage_callback=None, **kwargs):
        created.append(stage_tt.name)
        return _Job(stage_tt, output)

    monkeypatch.setattr(task_runtime, "_create_job", _create_job)

    result = _run(database, task_id, task_type, output, [])

    assert result == task_runtime.JobState.FAILED
    # The producer still ran; only the consumer, which has nowhere to be handed
    # its verified artifact, was refused.
    assert created == ["stage_input_runner-features"]
    diagnostics = database.get_task_diagnostics(task_id) or {}
    assert diagnostics.get("reason_code") == "stage_input_unavailable"
    assert diagnostics.get("stage_id") == "stage_input_runner.model"


def _producer_run(
    tmp_path, monkeypatch, files: dict[str, str], *, producer_path: str = "features/*.dat"
) -> tuple[str, str, dict, dict]:
    database, task_id, task_type, output = _prepare(tmp_path, monkeypatch, producer_path=producer_path)
    for relative, content in files.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    graph = compile_graph(task_type)
    identity = task_runtime._stage_output_identity(str(output), task_type.workflow[1].outputs)
    assert identity is not None
    latest = {"stage_input_runner.features": {"status": stage_state.COMPLETED, "output_identity": identity, "attempt": 1}}
    nodes = {node.id: node for node in graph.nodes}
    return str(output), task_id, nodes, latest


def test_a_multi_file_producer_port_is_staged_as_a_role_directory(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(
        tmp_path, monkeypatch, {"features/a.dat": "a", "features/b.dat": "b"}
    )
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    assert task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest) is None

    document = json.loads((stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    entry = document["inputs"]["features"]
    # The port's static prefix is the role directory, so a role that is a set of
    # files names that directory rather than inventing a single-file identity.
    assert entry["path"] == f"{STAGE_INPUTS_CONTAINER_DIR}/features"
    assert [item["source_path"] for item in entry["files"]] == ["features/a.dat", "features/b.dat"]
    assert sorted(path.name for path in (stage_inputs / "features").iterdir()) == ["a.dat", "b.dat"]


def test_a_recorded_digest_that_no_longer_matches_the_bytes_is_refused(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(tmp_path, monkeypatch, {"features/2KL8.dat": "features"})
    stale = json.loads(latest["stage_input_runner.features"]["output_identity"])
    stale["files"][0]["sha256"] = "0" * 64
    latest["stage_input_runner.features"]["output_identity"] = json.dumps(stale)
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    refusal = task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest)

    assert refusal == "stage_input_invalid"
    assert not (stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).exists()


def test_an_upstream_stage_that_never_completed_stages_nothing(tmp_path, monkeypatch):
    output, _task_id, nodes, _latest = _producer_run(tmp_path, monkeypatch, {"features/2KL8.dat": "features"})
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    assert task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, {}) == (
        "stage_input_unavailable"
    )
    assert not (stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).exists()


def test_a_nested_producer_port_keeps_its_layout_below_the_static_prefix(tmp_path, monkeypatch):
    output, _task_id, nodes, latest = _producer_run(
        tmp_path,
        monkeypatch,
        {"features/1abc/a_data.json": "a", "features/1abc/b_data.json": "b"},
        producer_path="features/*/*_data.json",
    )
    node = nodes["stage_input_runner.model"]
    stage_inputs = tmp_path / "workspace" / "stage_inputs" / node.id

    assert task_runtime._materialize_stage_inputs(str(stage_inputs), output, node, nodes, latest) is None

    document = json.loads((stage_inputs / STAGE_INPUTS_DOCUMENT_NAME).read_text(encoding="utf-8"))
    entry = document["inputs"]["features"]
    assert entry["path"] == f"{STAGE_INPUTS_CONTAINER_DIR}/features"
    assert [item["path"] for item in entry["files"]] == [
        f"{STAGE_INPUTS_CONTAINER_DIR}/features/1abc/a_data.json",
        f"{STAGE_INPUTS_CONTAINER_DIR}/features/1abc/b_data.json",
    ]
    assert (stage_inputs / "features" / "1abc" / "b_data.json").read_text(encoding="utf-8") == "b"
